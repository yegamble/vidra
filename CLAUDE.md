# CLAUDE.md — vidra (meta repo)

The agent rules for this repo live in AGENTS.md — the single source of truth,
imported below. Do not duplicate rules here; edit AGENTS.md instead.

Pay particular attention to **"Git hygiene — finished means merged"**: commit
early and push often; a task is finished only when its work is merged to
`main` and pushed (a blocked merge is "open — awaiting merge", never "done");
after a merge, delete the work branch locally and remotely and sweep any
branch already merged into `origin/main`. The nested component checkouts
(vidra-core, vidra-user, vidra-search) are separate git repos with their own
AGENTS.md — the same hygiene applies inside each of them.

@AGENTS.md
