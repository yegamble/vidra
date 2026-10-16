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
