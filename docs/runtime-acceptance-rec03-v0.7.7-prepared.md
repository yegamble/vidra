# REC-03 / A38 for v0.7.5 → v0.7.7 — PREPARED, NOT EXECUTED

> **Nothing in this file has run.** No host or runner has been used, no image
> pulled, no migration applied, no rollback attempted. This is the invocation and
> the expected reading of it, written before the run so the driver can be
> reviewed while it is still free to be wrong. Every "expected" below is a
> prediction from source; none of it is evidence. The record of a real run
> belongs in `docs/runtime-acceptance-rec03-v0.7.7.md`, written from the logs,
> and may contradict this page.

Driver: [`tests/rec03-upgrade-rollback.sh`](../tests/rec03-upgrade-rollback.sh);
its guards are unit-tested in [`tests/rec03_script_test.py`](../tests/rec03_script_test.py).
**Why v0.7.7, not v0.7.6.** vidra-core v0.7.6 was published on 2026-10-03 from a
meta checkout 54 commits behind main, so its deployment bundle was built without
the deploy fixes this release carries (the backup plaintext refusal among them),
and vidra-user v0.7.6 was never created. v0.7.6 is withdrawn and never gets a
record; the same core and user source is cut as v0.7.7 from main's tip, and
`release.sh` now refuses a meta checkout that is behind origin/main. The council
ruling keeps its v0.7.6 name below; its decisions apply to v0.7.7 unchanged.

Council ruling v0.7.6, D3: this drill **gates the merge of `releases/v0.7.7.json`**
(the switch that publishes v0.7.7 to installers), not the tags. It runs on the
published v0.7.7 images, on a GitHub runner or a multipass VM; it needs no bucket.

## The pair

| | core | user | search | core schema | search schema |
|---|---|---|---|---|---|
| OLD `v0.7.5` (`releases/v0.7.5.json`) | v0.7.5 | v0.7.3 | v0.7.3 | 150 | 18 |
| NEW `v0.7.7` (hand-assembled record, ruling D1) | v0.7.7 | v0.7.7 | **v0.7.3** | 151 | 18 |

**v0.7.7 pairs search at v0.7.3** (ruling D1: core and user are tagged, search
is not). So neither side is one tag, and the driver now pins every phase per
component from the record — the previous driver would have pinned
`vidra-user:v0.7.5`, which was never built, at the first phase.

The only migration in the pair is `0151_mail_config`: one `CREATE TABLE
mail_config (…)`, no `IF NOT EXISTS`, no column to clash on. Hence
`REC03_INJECT=table`. Core moves 150 → 151 and search stays at 18, so
`REC03_SAME_SCHEMA` **stays unset** and `restore-refuse` has a real input.

## The invocation

Once per host, before `install`:

```
scp tests/rec03-envfix.py deploy/release-mapping.py root@HOST:/root/
```

Then, per phase (on a runner that already has Docker, add `REC03_ALLOW_DOCKER=1`
inside the quotes):

```
ssh root@HOST "REC03_OLD=v0.7.5 REC03_NEW=v0.7.7 REC03_INSTALL=bundle \
REC03_INJECT=table REC03_INJECT_TABLE=mail_config \
REC03_RECORD_REF=<record-PR-branch> bash -s -- <phase>" < tests/rec03-upgrade-rollback.sh
```

`REC03_RECORD_REF` is the branch of **yegamble/vidra** carrying the unmerged
`releases/v0.7.7.json` (a branch on a fork is not reachable at that URL). It is
passed on to install/deploy/rollback as `VIDRA_RECORD_BASE_URL`, so they verify
the pairing against the same record the driver pinned from; their logs will
carry the non-canonical-source WARNING, which is expected here.

Phases, in order: `install → data → fp <label> → backup → inject → upgrade-fail →
recover → backup2 → rollback → restore-refuse → repin → restore-ok → split → report`.

## What each phase is expected to show

| Phase | Expected |
|---|---|
| `install` | meta main's `install.sh --ref v0.7.5 --yes` (no `--git`); `/opt/vidra` is NOT a checkout and `vidra-bundle.manifest` says `tag=v0.7.5`; setup pins core v0.7.5 / user v0.7.3 / search v0.7.3; `deploy.sh` exit 0; ledgers **150 / 18**; facts `install_mode=bundle`, `pairing=v0.7.5 v0.7.3 v0.7.3` |
| `data`, `fp` | fixture published; the fingerprint recorded and identical at every later checkpoint |
| `backup` | pre-upgrade dump at 150; `pre_core_version=150`, `pre_search_version=18` |
| `inject` | `CREATE TABLE mail_config (rec03_injected BOOLEAN)` succeeds; facts `undo=DROP TABLE mail_config`; ledger still 150 clean |
| `upgrade-fail` | the manual bundle upgrade of vidra-docs `install/upgrading.md`, "If the script is older than this release": `vidra-bundle_v0.7.7.tar.gz` checksum OK, unpacked as `vidra`, pins v0.7.7 / v0.7.7 / v0.7.3; `deploy.sh` takes its pre-deploy dump, then aborts in the migrate step on `relation "mail_config" already exists`, **no restart**; ledger **151 dirty**; v0.7.5 still serving; probes 200 |
| `recover` | `migrate version` → 151 dirty; `force_target 150 151` → **150**; `DROP TABLE mail_config`; `force 150`; re-run applies 0151; ledger **151 / 18**; `post_core_version=151` |
| `backup2` | post-upgrade dump at 151 + the marker rename |
| `rollback` | **`rollback.sh --core v0.7.5 --user v0.7.3 --search v0.7.3`**, `rollback_exit=0` on ledger 151. The v0.7.5 migrator should log that schema 151 is newer than its newest migration (150) and apply nothing — the coexistence CI already showed (rollback-floor run 35506583432, schema-compat run 35506583352), now on a host |
| `restore-refuse` | the 151 dump REFUSED under v0.7.5 pins before any drop, counts unchanged; facts carry 150→151 and 18→18 |
| `repin` | v0.7.7 / v0.7.7 / v0.7.3 again; `deploy.sh` → already at 151 |
| `restore-ok` | the 150 dump restored under v0.7.7 pins (the forward path): 0151 applied, ledger 151, marker gone, fingerprint equal to the pre-upgrade one |
| `split` | OPS-01 subset: worker profile, second upload transcoded by the worker |
| `report` | every `facts/*.json`; the log line names `install=bundle record_ref=<branch> inject=table` |

## What the D3 acceptance needs that this drill cannot show

- **`mail_config` decryptable after a restore.** `restore-ok` restores the
  *pre-upgrade* dump (schema 150), which has no `mail_config` at all, and the
  drill never saves a mail config. That proof is the recovery drill's: on the
  v0.7.7 stage, `recovery-release-acceptance.mjs mfa-enroll` saves a sealed
  mail-config before the backup, `recovery_release_acceptance.py` fingerprints
  the row with its secret reduced to its `enc:` class (catalogue entry 151), and
  `verify-restore` asserts `secret_status` is `ok` on the replacement host. That
  half has been parsed, not run.
- **The v0.7.5 `vidra update`** — by design it refuses this half-cut release
  before touching the host (ruling D1); its `--check` on beta is the owner's.
- **Replacing the CLI** (`install.sh --ref v0.7.7 --no-setup`, upgrade-notes
  step 2): not done, so `report`'s `vidra doctor` is the v0.7.5 CLI's.
- Off-site backups and the age/crypt refusal (D4), ACME/DNS, S3 storage, arm64,
  browser decode, and migration timing on a populated database.
