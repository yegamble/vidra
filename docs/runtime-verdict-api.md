# Reading sanitized runtime verdicts

REC03 and sealed recovery publish an informational Check Run named
`runtime-verdict/KIND/RUN_ID/ATTEMPT` on the exact tool commit. Read it through
`GET /repos/yegamble/vidra/commits/TOOL_SHA/check-runs?filter=all`, then
`GET /repos/yegamble/vidra/check-runs/CHECK_ID`. Its `output.summary` contains
only validated verdicts, actual input-byte SHA256 hashes, job results and the
record/run/attempt identities. Verify those identities against the dispatched run.

The check always concludes **neutral** and is never a merge or runtime gate.
The original workflow jobs remain authoritative. Missing verdicts report
**INCOMPLETE**; invalid or private fields prevent publication. Only exact
current-attempt verdict artifacts enter the reporter. Encrypted handoffs,
environment files and raw logs never enter this API transport.

Use full workflow reruns: failed-job reruns can lack current-attempt verdicts
and therefore produce **INCOMPLETE** rather than reusing earlier artifacts.

Same-repository pull requests changing `releases/v0.7.8.json` run both drills
through `release-runtime-qualification.yml`; manual dispatch remains available.
The record identity is the PR head commit, while the tool identity is the
immutable PR merge commit (`github.sha`). A green source CI run alone does not
establish either runtime verdict.
