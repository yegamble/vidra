#!/usr/bin/env bash
#
# Stop hook — enforces AGENTS.md "Git hygiene — finished means merged".
#
# WHY: the repo's binding rule is that unpushed work does not exist and a task
# is finished only when merged to main. Nothing enforced it, so a session could
# end with edits sitting in the working tree and still report "done". This hook
# refuses the stop while the tree says otherwise.
#
# Contract (docs: code.claude.com/docs/en/hooks):
#   exit 0 -> allow the stop      exit 2 -> block it and continue
# Anything else is a non-blocking error. This script FAILS OPEN: any internal
# problem exits 0, because a broken hook that exits 2 would trap the session.
#
# NOT set -e: an unexpected non-zero from any probe must not become an exit 2.
set -uo pipefail

MAX_BLOCKS=3

payload="$(cat)"
session_id="$(jq -r '.session_id // "unknown"' <<<"$payload" 2>/dev/null)" || exit 0
[ -n "$session_id" ] || session_id=unknown

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
[ -d "$root/.git" ] || exit 0

state_dir="$root/.claude/hooks/.state"
mkdir -p "$state_dir" 2>/dev/null || exit 0
state_file="$state_dir/$session_id"

# Bound the loop. An unbounded Stop hook is an infinite loop.
blocks=0
[ -f "$state_file" ] && blocks="$(cat "$state_file" 2>/dev/null || echo 0)"
case "$blocks" in ''|*[!0-9]*) blocks=0 ;; esac
[ "$blocks" -ge "$MAX_BLOCKS" ] && exit 0

# Collect unfinished work. Tracked changes only — untracked files are ignored
# on purpose so env/*.env (rule 6: never commit secrets) can never trip this.
unfinished=""
for repo in "$root" "$root"/vidra-core "$root"/vidra-user "$root"/vidra-search; do
  [ -d "$repo/.git" ] || continue
  name="$(basename "$repo")"

  branch="$(git -C "$repo" symbolic-ref --quiet --short HEAD 2>/dev/null)"
  # Detached HEAD is the NORMAL, correct state for the nested checkouts (they
  # are pinned at release tags). Never nag about it.
  [ -z "$branch" ] && continue

  if ! git -C "$repo" diff --quiet --ignore-submodules 2>/dev/null ||
     ! git -C "$repo" diff --cached --quiet --ignore-submodules 2>/dev/null; then
    unfinished+="  - $name: uncommitted changes to tracked files on '$branch'"$'\n'
  fi

  if git -C "$repo" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    ahead="$(git -C "$repo" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
    [ "${ahead:-0}" -gt 0 ] &&
      unfinished+="  - $name: $ahead commit(s) on '$branch' not pushed"$'\n'
  else
    [ -n "$(git -C "$repo" log --oneline -1 2>/dev/null)" ] &&
      unfinished+="  - $name: branch '$branch' has no upstream — never pushed"$'\n'
  fi
done

if [ -z "$unfinished" ]; then
  rm -f "$state_file" 2>/dev/null
  exit 0
fi

echo $((blocks + 1)) > "$state_file" 2>/dev/null

reason="AGENTS.md — 'Git hygiene: finished means merged' — is not satisfied:

$unfinished
Unpushed work does not exist, and a task is finished only once merged to main.

If this IS your work: commit it, push it, open the PR, and merge once CI is
green. If you cannot merge (no permission, review requested, red CI), report
the task as 'open — awaiting merge', never as done.

If this is NOT your work — the user only asked a question, or these changes
predate this session — do NOT commit or push them. Say so plainly in one line
and stop. Committing someone else's uncommitted work is worse than stopping
with a dirty tree. This check gives up after $MAX_BLOCKS attempts (this was $((blocks + 1)))."

jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "Stop",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'
exit 2
