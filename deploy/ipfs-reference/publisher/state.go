package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

var errUnpinned = errors.New("approved root has no recursive pin; rerun publication to restage it")
var errApprovalLost = errors.New("approval was withdrawn or its generation is no longer eligible")

type receipt struct {
	Approval string `json:"approval_sha256"`
	Root     string `json:"root"`
	State    string `json:"state"`
	// Existing manual pins and pins shared by separate video approvals survive a withdrawal.
	Owned bool `json:"owned"`
}

type journal struct {
	dir   *os.File
	Items map[string]receipt `json:"videos"`
	// An interrupted request can take effect after pin/ls reports it absent.
	// Keep watching on later reconciles until its removal or ownership transfer.
	Watch map[string][]string `json:"uncertain_withdrawals,omitempty"`
}

func approvalHash(m manifest) string {
	raw, _ := json.Marshal(m) // The approval contains only strings, integers and slices.
	return fmt.Sprintf("%x", sha256.Sum256(raw))
}

func (p publisher) withJournal(ctx context.Context, operation func(*journal) error) error {
	if p.stateDir == "" {
		return errors.New("publication state directory is required")
	}
	if err := os.Mkdir(p.stateDir, 0700); err == nil {
		parent, err := os.Open(filepath.Dir(filepath.Clean(p.stateDir)))
		if err != nil {
			return err
		}
		err = parent.Sync()
		parent.Close()
		if err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrExist) {
		return err
	}
	info, err := os.Lstat(p.stateDir)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return errors.New("state directory must be private and owned by the publisher")
	}
	if stat, ok := info.Sys().(*syscall.Stat_t); !ok || stat.Uid != uint32(os.Geteuid()) {
		return errors.New("unexpected state directory owner")
	}
	dir, err := os.Open(p.stateDir)
	if err != nil {
		return err
	}
	defer dir.Close()
	for {
		err = syscall.Flock(int(dir.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
		if err == nil {
			break
		}
		if !errors.Is(err, syscall.EWOULDBLOCK) {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(50 * time.Millisecond):
		}
	}
	j := &journal{dir: dir, Items: make(map[string]receipt)}
	if err := readJournal(filepath.Join(p.stateDir, "publications.json"), j); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return operation(j)
}

func readJournal(name string, j *journal) error {
	info, err := os.Lstat(name)
	if err == nil {
		if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 16<<20 {
			return errors.New("invalid publication journal")
		}
		raw, err := os.ReadFile(name)
		if err != nil {
			return err
		}
		// Check for an absent or null map as well as malformed documents. An
		// unreadable registry must never grant authority to remove a shared pin.
		j.Items = nil
		if err := json.Unmarshal(raw, j); err != nil || j.Items == nil {
			return errors.New("unreadable publication journal")
		}
		for video, r := range j.Items {
			if !uuidPattern.MatchString(video) || !directoryCID(r.Root) || !hashPattern.MatchString(r.Approval) ||
				(r.State != "pending" && r.State != "pinned" && r.State != "withdrawing") {
				return errors.New("invalid publication receipt")
			}
		}
		for video, roots := range j.Watch {
			if !uuidPattern.MatchString(video) {
				return errors.New("invalid withdrawal watch")
			}
			for _, root := range roots {
				if !directoryCID(root) {
					return errors.New("invalid withdrawal root")
				}
			}
		}
	} else {
		return err
	}
	return nil
}

func (j *journal) save() error {
	raw, err := json.Marshal(j)
	if err != nil {
		return err
	}
	if len(raw) > 16<<20 {
		return errors.New("publication journal is full")
	}
	f, err := os.CreateTemp(j.dir.Name(), ".publications-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err := os.Rename(f.Name(), filepath.Join(j.dir.Name(), "publications.json")); err != nil {
		return err
	}
	return j.dir.Sync()
}

// recursivePin reads a complete list from this dedicated reference node. A
// missing member in a valid, bounded result proves absence. An HTTP error or
// incomplete result leaves ownership and the pending receipt intact.
func (p publisher) recursivePin(ctx context.Context, root string) (bool, error) {
	pins, err := p.pinSet(ctx, "recursive")
	_, present := pins[root]
	return present, err
}

func (p publisher) pinSet(ctx context.Context, kind string) (map[string]struct{}, error) {
	resp, err := p.rpcRequest(ctx, "pin/ls?type="+kind+"&stream=false", nil, "")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var fields map[string]json.RawMessage
	if err := parseRPC(resp, 16<<20, &fields); err != nil || fields == nil {
		return nil, errors.New("cannot verify the recursive pin set")
	}
	// Kubo v0.43 omits Keys when the selected pin type has zero members.
	if len(fields) == 0 {
		return map[string]struct{}{}, nil
	}
	var keys map[string]struct{ Type string }
	if len(fields) != 1 || json.Unmarshal(fields["Keys"], &keys) != nil || keys == nil {
		return nil, errors.New("invalid recursive pin response")
	}
	result := make(map[string]struct{}, len(keys))
	for cid, pin := range keys {
		if pin.Type != kind {
			return nil, errors.New("unexpected entry in recursive pin set")
		}
		result[cid] = struct{}{}
	}
	return result, nil
}

func parseRPC(resp *http.Response, maximum int64, out any) error {
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maximum+1))
	if err != nil || int64(len(raw)) > maximum || resp.Trailer.Get("X-Stream-Error") != "" {
		return errors.New("incomplete Kubo RPC response")
	}
	return json.Unmarshal(raw, out)
}

func (p publisher) changePin(ctx context.Context, command, root string) error {
	resp, err := p.rpcRequest(ctx, "pin/"+command+"?recursive=true&arg="+url.QueryEscape(root), nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var result struct{ Pins []string }
	if err := parseRPC(resp, 65536, &result); err != nil || len(result.Pins) != 1 || result.Pins[0] != root {
		return errors.New("no matching Kubo pin confirmation")
	}
	return nil
}

func (j *journal) clearWatch(video, root string) {
	roots := j.Watch[video]
	for i, candidate := range roots {
		if candidate == root {
			roots = append(roots[:i], roots[i+1:]...)
			break
		}
	}
	if len(roots) == 0 {
		delete(j.Watch, video)
	} else {
		j.Watch[video] = roots
	}
}

func (p publisher) checkWithdrawals(ctx context.Context, j *journal, video string) error {
	for _, root := range append([]string(nil), j.Watch[video]...) {
		shared := false
		for _, r := range j.Items {
			if r.Root == root && r.State != "withdrawing" {
				shared = true
				break
			}
		}
		if !shared {
			pinned, err := p.recursivePin(ctx, root)
			if err != nil {
				return err
			}
			if !pinned {
				continue
			}
			if err := p.changePin(ctx, "rm", root); err != nil {
				return err
			}
		}
		j.clearWatch(video, root)
		if err := j.save(); err != nil {
			return err
		}
	}
	return nil
}

func (p publisher) retire(ctx context.Context, j *journal, video string) error {
	r := j.Items[video]
	if r.State == "pending" && r.Owned {
		if j.Watch == nil {
			j.Watch = make(map[string][]string)
		}
		j.Watch[video] = append(j.Watch[video], r.Root)
	}
	r.State = "withdrawing"
	j.Items[video] = r
	if err := j.save(); err != nil {
		return err
	}
	shared := false
	for other, entry := range j.Items {
		if other != video && entry.Root == r.Root {
			shared = true
			break
		}
	}
	if r.Owned && !shared {
		pinned, err := p.recursivePin(ctx, r.Root)
		if err != nil {
			return err
		}
		if pinned {
			if err := p.changePin(ctx, "rm", r.Root); err != nil {
				return err // A subsequent reconcile checks the actual outcome.
			}
			j.clearWatch(video, r.Root)
		}
	} else {
		j.clearWatch(video, r.Root)
	}
	delete(j.Items, video)
	return j.save()
}

func (p publisher) stillApproved(ctx context.Context, filename, expected string) error {
	m, files, err := readApproval(filename)
	if err != nil {
		return errors.Join(errApprovalLost, err)
	}
	if approvalHash(m) != expected {
		return errApprovalLost
	}
	return p.stream(ctx, m, files["master.m3u8"], io.Discard)
}

func (p publisher) reconcile(ctx context.Context, filename string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	video, ok := strings.CutSuffix(filepath.Base(filename), ".json")
	if !ok || !uuidPattern.MatchString(video) {
		return "", errors.New("need the original video UUID.json approval path")
	}
	root := ""
	err := p.withJournal(ctx, func(j *journal) error {
		r, found := j.Items[video]
		if found && r.State == "withdrawing" {
			return p.retire(ctx, j, video)
		}
		if err := p.checkWithdrawals(ctx, j, video); err != nil {
			return err
		}
		if !found {
			return nil
		}
		if err := p.stillApproved(ctx, filename, r.Approval); err != nil {
			if errors.Is(err, errApprovalLost) {
				return p.retire(ctx, j, video)
			}
			return err
		}
		pinned, err := p.recursivePin(ctx, r.Root)
		if err != nil {
			return err
		}
		if !pinned {
			return errUnpinned
		}
		if r.State != "pinned" {
			r.State = "pinned"
			j.Items[video] = r
			if err := j.save(); err != nil {
				return err
			}
		}
		root = r.Root
		return nil
	})
	return root, err
}

func (p publisher) commitPin(ctx context.Context, filename string, m manifest, root string) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	return p.withJournal(ctx, func(j *journal) error {
		approval := approvalHash(m)
		if err := p.stillApproved(ctx, filename, approval); err != nil {
			return err
		}
		r, exists := j.Items[m.Video]
		if exists && (r.State == "withdrawing" || r.Approval != approval || r.Root != root) {
			if err := p.retire(ctx, j, m.Video); err != nil {
				return err
			}
			exists = false
		}
		pinned, err := p.recursivePin(ctx, root)
		if err != nil {
			return err
		}
		if !exists {
			r = receipt{Approval: approval, Root: root, Owned: !pinned}
			for video, watched := range j.Watch {
				for _, cid := range watched {
					if cid == root {
						r.Owned = true
						j.clearWatch(video, root)
						break
					}
				}
			}
			for _, other := range j.Items {
				if other.Root == root {
					r.Owned = other.Owned
					break
				}
			}
		}
		r.State = "pending"
		j.Items[m.Video] = r
		if err := j.save(); err != nil {
			return err
		}
		var pinErr error
		if !pinned {
			pinErr = p.changePin(ctx, "add", root)
		}
		if err := p.stillApproved(ctx, filename, approval); err != nil {
			if errors.Is(err, errApprovalLost) {
				return errors.Join(err, p.retire(ctx, j, m.Video))
			}
			return err
		}
		if pinErr != nil {
			pinned, err = p.recursivePin(ctx, root)
			if err != nil || !pinned {
				return errors.Join(pinErr, err)
			}
		}
		r.State = "pinned"
		j.Items[m.Video] = r
		return j.save()
	})
}
