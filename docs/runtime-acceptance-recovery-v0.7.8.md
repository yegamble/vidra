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

The second attempt reported `/readyz` 200 and actual healthy API, search,
frontend, PostgreSQL and Redis containers before entering the API fixture.
The private route and strict health checks did not establish successful MFA
enrollment, stored mail/OIDC configuration, backup or decryption after restore.

A local diagnostic reproduced a separate concrete fixture timeout defect: the
15-second HTTP signal was created before waiting for the next unused TOTP step.
A 28.498-second wait reached the real published API with an already-aborted
signal. That finding is a fixture correction, not retrospective acceptance of
the hosted source failure.

## Required acceptance still outstanding

The source must create the synthetic owner, enable MFA, save sealed dummy SMTP
and disabled OIDC secrets through their real APIs, fingerprint the catalogue,
and run unchanged published backup scripts. After stopping that source, a
different VM with empty Docker state must restore the hash-bound encrypted
handoff using unchanged published restore scripts and original configuration.

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
