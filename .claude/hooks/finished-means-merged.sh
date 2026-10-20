#!/usr/bin/env bash
# Stop hook: exit 2 blocks stopping; a clean, verified main exits 0.
# MAX_BLOCKS bounds the reminder counter, NEVER the checks. Repeating Stop must
# not convert an unmerged branch or failed verification into apparent success.
set -uo pipefail
MAX_BLOCKS=6

payload="$(cat)"
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
unfinished=""
if ! git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
  echo 'Cannot verify finished-means-merged: project root is not a git checkout.' >&2
  exit 2
fi

# Hash the untrusted session id before using it as a filename; malformed hook
# payloads share an unknown-session counter but never bypass verification.
session_key="$(python3 -c 'import hashlib,json,sys
try: value = str(json.load(sys.stdin).get("session_id", "unknown"))
except (ValueError, AttributeError): value = "unknown"
print(hashlib.sha256(value.encode()).hexdigest())' <<<"$payload")" || exit 2
state_dir="$root/.claude/hooks/.state"
state_file="$state_dir/$session_key"
blocks=0
if mkdir -p "$state_dir" 2>/dev/null; then
  [ -f "$state_file" ] && blocks="$(cat "$state_file" 2>/dev/null)"
  case "$blocks" in ''|*[!0-9]*) blocks=0 ;; esac
else
  unfinished+="  - cannot persist Stop reminder counter"$'\n'
fi

repos=("$root")
all_present=true
for component in core user search; do
  # macOS ships bash 3.2, which has no ${var^^}; a bad substitution there
  # aborts the hook before it checks anything.
  variable="VIDRA_$(printf %s "$component" | tr "[:lower:]" "[:upper:]")_ROOT"
  repo="${!variable:-}"
  if [ -z "$repo" ]; then
    repo="$root/vidra-$component"
    [ -e "$repo/.git" ] || repo="$(dirname "$root")/vidra-$component"
  fi
  if [ -e "$repo/.git" ]; then
    repos+=("$repo")
  else
    all_present=false
    unfinished+="  - vidra-$component: required development source checkout missing at $repo; configure $variable before SessionStart."$'\n'
  fi
  case "$component" in
    core) core_root="$repo" ;;
    user) user_root="$repo" ;;
  esac
done

for repo in "${repos[@]}"; do
  name="$(basename "$repo")"
  branch="$(git -C "$repo" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  # Detached release pins can have valid ancestry, but cannot certify latest-main
  # completeness when stale. Worktrees use a .git FILE, not a directory.
  if ! git -C "$repo" diff --quiet --ignore-submodules 2>/dev/null ||
     ! git -C "$repo" diff --cached --quiet --ignore-submodules 2>/dev/null; then
    unfinished+="  - $name: uncommitted changes to tracked files"$'\n'
  fi
  if [ -n "$branch" ]; then
    if [ "$branch" != main ]; then
      unfinished+="  - $name: Work is on an unmerged branch '$branch'; merge to main (or explicitly report 'open — awaiting merge') before stopping."$'\n'
    fi
    if git -C "$repo" rev-parse --verify '@{u}' >/dev/null 2>&1; then
      ahead="$(git -C "$repo" rev-list --count '@{u}..HEAD' 2>/dev/null)" || ahead=unknown
      if [ "$ahead" != 0 ]; then
        unfinished+="  - $name: $ahead commit(s) not pushed to upstream"$'\n'
      fi
    else
      unfinished+="  - $name: branch '$branch' has no upstream"$'\n'
    fi
  fi
  # Refresh the actual remote branch. A stale origin/main must not certify
  # containment after a force-push or when the remote could not be contacted.
  if ! git -C "$repo" fetch --quiet origin '+refs/heads/main:refs/remotes/origin/main' 2>/dev/null; then
    unfinished+="  - $name: cannot refresh origin/main; merge containment is unverified"$'\n'
  elif ! git -C "$repo" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    unfinished+="  - $name: HEAD is not contained in origin/main; merge to main (or explicitly report 'open — awaiting merge') before stopping."$'\n'
  elif ! git -C "$repo" merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
    unfinished+="  - $name: source checkout is stale (behind refreshed origin/main); it cannot certify latest-main completeness. Use current development audit worktrees, with CLAUDE_PROJECT_DIR and VIDRA_*_ROOT configured before SessionStart. Update dedicated development sources if they fall behind; preserve deployment/release pins."$'\n'
  fi
done

if [ "$all_present" = true ]; then
  # Compare to immutable session-start SHAs: merging a backend PR during the
  # session must not bless its missing frontend. No snapshot means full audit.
  # bash 3.2 (macOS) calls an empty "${arr[@]}" unbound under set -u, hence
  # the ${arr[@]+...} guard where it is expanded.
  baseline_args=()
  baseline_file="$state_dir/$session_key.baseline.json"
  if [ -f "$baseline_file" ]; then
    baseline_args=(--baseline-file "$baseline_file")
  fi
  if ! completeness="$(python3 "$root/scripts/ci/check-vertical-slice-completeness.py" \
      --root "$root" --core-root "$core_root" --user-root "$user_root" \
      ${baseline_args[@]+"${baseline_args[@]}"} 2>&1)"; then
    unfinished+="  - cross-repo completeness failed:"$'\n'"$completeness"$'\n'
  fi
fi

if [ -z "$unfinished" ]; then
  rm -f "$state_file" 2>/dev/null
  exit 0
fi
if [ "$blocks" -lt "$MAX_BLOCKS" ]; then
  blocks=$((blocks + 1))
fi
printf '%s\n' "$blocks" > "$state_file" 2>/dev/null || true
reason="AGENTS.md — finished means merged — is not satisfied:

$unfinished
Commit and push authorized work, open the PR, and merge once CI is green.
If merge is blocked, report 'open — awaiting merge'. Do not commit changes
that predate this task or belong to someone else. This hook remains blocking;
reminder $blocks/$MAX_BLOCKS is not an automatic permission to declare done."

python3 -c 'import json,sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "permissionDecision": "deny", "permissionDecisionReason": sys.argv[1]}}))' "$reason"
# On exit 2 Claude Code relays STDERR only; the stdout JSON alone arrived as
# "No stderr output" (2026-10-12, again 2026-10-20), hiding every finding.
printf '%s\n' "$reason" >&2
exit 2
