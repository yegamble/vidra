# Published sealed-secret recovery: v0.7.8

Date: 2026-10-16. **Verdict: PASS for the synthetic sealed-secret subset below.**
Scope: published-image synthetic cross-VM sealed-secret subset, executed on two
fresh GitHub-hosted Ubuntu 24.04 VMs.
No production data, media bucket, delivery endpoint or DNS record was used.

Immutable release record: `da049b6e07f59d2e5e51d7152ade4857f3d89bf6`.
Successful tool commit: `198391e335d756f656d4049e6ec39ca336b91657`.
Published component bytes are pinned by [the release record](../releases/v0.7.8.json).

## Actual attempts

| Run | Tool | Source | Replacement | Accepted boundary |
| --- | --- | --- | --- | --- |
| [38933537741](https://github.com/yegamble/vidra/actions/runs/38933537741) | `fabaac46` | FAIL at `fixture` | skipped | Fixture failed before backup. |
| [38940385591](https://github.com/yegamble/vidra/actions/runs/38940385591) | `8950662a` | FAIL at `api-fixture` | skipped | All five services healthy; API fixture creation failed. |
| [38943219095](https://github.com/yegamble/vidra/actions/runs/38943219095) | `cce26c92` | PASS, complete | FAIL at `restore` | Source backup and stop accepted; replacement reported PostgreSQL/Redis starting and no application containers. |
| [38945689909](https://github.com/yegamble/vidra/actions/runs/38945689909) | `198391e3` | PASS, complete | PASS, complete | Source backup and configuration restored on a different fresh VM; secret and key controls passed. |

The second attempt reported `/readyz` 200 and actual healthy API, search,
frontend, PostgreSQL and Redis containers before entering the API fixture.
The private route and strict health checks did not establish successful MFA
enrollment, stored mail/OIDC configuration, backup or decryption after restore.

A local diagnostic reproduced a separate concrete fixture timeout defect: the
15-second HTTP signal was created before waiting for the next unused TOTP step.
A 28.498-second wait reached the real published API with an already-aborted
signal. That finding is a fixture correction, not retrospective acceptance of
the hosted source failure.

## Earlier restore failure and fixture correction

The third source job passed its full fixed verdict: synthetic owner/MFA, sealed
dummy SMTP and disabled OIDC configuration through real APIs, catalogue
fingerprint, unchanged published backup, configuration capture and stopped
source services at schemas 182/18. Its original verdict SHA-256 is
`5bfa64470d1d733c684a40cf73ced102c7aade688ba351eb8c80913a9908db11`.

The replacement job failed at the broad restore milestone, which includes
starting database services, copying the fixture, binding the readiness relay
and invoking the unchanged restore command. The finite diagnostics do not
establish which substep failed or that any database reload occurred. Its original
verdict SHA-256 is
`37a59f35d7ead9c68770cd69917790f36b2284a2585f6763577e9cb4e83a2926`.

A controlled local diagnostic using an explicit initialization delay reproduced
a missing fixture precondition: the unchanged restore script reached its first
database operation while fresh PostgreSQL was still starting. The same operation
succeeded after PostgreSQL became healthy. This does not identify the third
hosted attempt's exact failing substep.

The fourth run required actual healthy PostgreSQL and Redis containers, with
current identities and exact fixture project/service labels, before restore.
Its finite failure phases distinguish `restore-infrastructure`, `restore-relay`
and `restore` for the unchanged command. The final five-service health, image,
schema, catalogue and authentication checks remained required.

## Successful fourth attempt

Run `38945689909`, attempt `1`, used the exact record and tool commits above.
Both jobs and the overall workflow concluded success. Both verdicts are `PASS`
at `phase: complete`, with `synthetic_only: true`,
`external_delivery_blocked: true` and schemas **182/18**.

The source created only synthetic owner/MFA, dummy SMTP and disabled OIDC
fixtures. It captured the catalogue and configuration, ran the unchanged
published backup script and stopped its services before exporting the encrypted
handoff. The replacement had a different kernel boot identity and no existing
deployment, containers or volumes. It restored the hash-bound handoff and
original configuration using the unchanged published restore script.

The replacement's complete proof contains:

| Field | Accepted value and boundary |
| --- | --- |
| `different_runner_boot`, `empty_destination` | Both `true`; separate fresh hosted VM, not another container on the source host. |
| `backup_hash_match` | `true`; the encrypted handoff matched its source hash. |
| `schema_and_catalogue_match` | `true`; exact ledgers 182/18 and classified catalogue fingerprint matched. Restored configuration bytes also matched their source archive hashes. |
| `mfa_wrong_code_refused`, `mfa_correct_code_accepted` | Both `true`; wrong TOTP rejected and fresh correct TOTP accepted. |
| `mail_secret_status`, `oidc_secret_status`, `oidc_disabled` | `ok`, `ok`, `true`; stored SMTP and disabled-provider secrets decrypt. No delivery or external IdP login was exercised. |
| `wrong_key_refused` | `true`; wrong application `MFA_KEY_KEK` made mail/OIDC secrets undecryptable and refused correct-code MFA. Restoring the original key passed the positive checks again. |

Published backup, restore and library script hashes remained unchanged across
hosts. Digest-pinned application images, isolated internal Docker networking and
a readiness-only loopback relay were fixture adaptations; this does not qualify
production port exposure or public routing. The handoff used a public test-only
wrapping identity for synthetic data, not production backup key custody.

The original allowlisted verdict SHA-256 values are:

| Role | SHA-256 |
| --- | --- |
| Source | `629323b05fcea9a42ced0c04f707a10ffc6a5c0df3046f3458afd23d8e526334` |
| Replacement | `777765e066ecb9ed8193600bf75859b98110cd81ca31581898baee89bcefbf91` |

Independent verification checked exact repository/run/attempt/record/tool
context, actual job conclusions, every required proof field and both hashes
reconstructed from the original verdict writer's bytes. The neutral
`runtime-verdict/sealed/38945689909/1` Check is informational evidence transport.
Observed source and replacement job durations were 108 and 105 seconds; these
are not off-site recovery objectives or human installation stopwatch results.

[The complete sanitized attempt record](evidence/release-v0.7.8-verification/runtime-attempts.json)
retains real job results, immutable context and original allowlisted verdict
hashes. Private logs, handoff contents, ciphertext and credentials are excluded.

This successful run establishes only the synthetic published-image sealed-secret
subset. It does not establish media restoration, off-site RPO/RTO,
representative PeerTube fidelity, B2/S3 backup retrieval, trusted public TLS or
three human blank-host installs. Overall [readiness remains NO-GO](release-readiness.md).
