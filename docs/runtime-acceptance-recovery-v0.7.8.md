# Published sealed-secret recovery: v0.7.8

Date: 2026-10-16. **Verdict: INCOMPLETE; replacement restore is not accepted.**
Scope: synthetic sealed-secret fixtures planned across two fresh hosted VMs.
No production data, media bucket, delivery endpoint or DNS record was used.

Immutable release record: `da049b6e07f59d2e5e51d7152ade4857f3d89bf6`.
Published component bytes are pinned by [the release record](../releases/v0.7.8.json).

## Actual attempts

| Run | Tool | Source | Replacement | Accepted boundary |
| --- | --- | --- | --- | --- |
| [38933537741](https://github.com/yegamble/vidra/actions/runs/38933537741) | `fabaac46` | FAIL at `fixture` | skipped | Fixture failed before backup. |
| [38940385591](https://github.com/yegamble/vidra/actions/runs/38940385591) | `8950662a` | FAIL at `api-fixture` | skipped | All five services healthy; API fixture creation failed. |
| [38943219095](https://github.com/yegamble/vidra/actions/runs/38943219095) | `cce26c92` | PASS, complete | FAIL at `restore` | Source backup and stop accepted; replacement reported PostgreSQL/Redis starting and no application containers. |

The second attempt reported `/readyz` 200 and actual healthy API, search,
frontend, PostgreSQL and Redis containers before entering the API fixture.
The private route and strict health checks did not establish successful MFA
enrollment, stored mail/OIDC configuration, backup or decryption after restore.

A local diagnostic reproduced a separate concrete fixture timeout defect: the
15-second HTTP signal was created before waiting for the next unused TOTP step.
A 28.498-second wait reached the real published API with an already-aborted
signal. That finding is a fixture correction, not retrospective acceptance of
the hosted source failure.

## Source acceptance and replacement requirements

The third source job passed its full fixed verdict: synthetic owner/MFA, sealed
dummy SMTP and disabled OIDC configuration through real APIs, catalogue
fingerprint, unchanged published backup, configuration capture and stopped
source services at schemas182/18. Its original verdict SHA-256 is
`5bfa64470d1d733c684a40cf73ced102c7aade688ba351eb8c80913a9908db11`.

The replacement job failed at the broad restore milestone, which includes
starting database services, copying the fixture, binding the readiness relay
and invoking the unchanged restore command. The finite diagnostics do not
establish which substep failed or that any database reload occurred. Its original
verdict SHA-256 is
`37a59f35d7ead9c68770cd69917790f36b2284a2585f6763577e9cb4e83a2926`.

A different VM with empty Docker state must still restore the hash-bound
encrypted handoff using unchanged published restore scripts and original
configuration.

The replacement must verify exact schemas and catalogue/configuration bytes,
positive mail/OIDC decryption, MFA login, wrong-code refusal, wrong-key refusal
for all three secret uses, and successful recovery with the original key. No
such replacement verdict exists in the attempts recorded here.

[The complete sanitized attempt record](evidence/release-v0.7.8-verification/runtime-attempts.json)
retains real job results, immutable context and original allowlisted verdict
hashes. Private logs, handoff contents, ciphertext and credentials are excluded.

A successful future run would establish only the synthetic published-image
sealed-secret subset. It would not establish media restoration, off-site RPO/RTO,
representative PeerTube fidelity, B2/S3 backup retrieval, trusted public TLS or
three human blank-host installs. Overall [readiness remains NO-GO](release-readiness.md).
