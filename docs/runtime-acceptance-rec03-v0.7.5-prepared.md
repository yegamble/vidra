# REC-03 / A38 for v0.6.6 → v0.7.5 — PREPARED, NOT EXECUTED

> **Nothing in this file has run.** No host has been rented, no image pulled, no
> migration applied, no rollback attempted. This is the invocation and the
> expected reading of it, written down *before* the host exists so the driver can
> be reviewed while it is still free to be wrong. Every "expected" below is a
> prediction derived from source; none of it is evidence. The record of an actual
> run belongs in a separate `docs/runtime-acceptance-rec03-v0.7.5.md`, written
> from the logs, and may contradict this page.

Driver: [`tests/rec03-upgrade-rollback.sh`](../tests/rec03-upgrade-rollback.sh).
Its guards are unit-tested in [`tests/rec03_script_test.py`](../tests/rec03_script_test.py)
(the drill needs a host; the parameter validation does not).

## Why this pair, and why now

Beta already runs v0.7.5, and no rollback across the four migrations that
separate it from v0.6.6 has ever been rehearsed. v0.6.6 → v0.7.5 is also the
first *migrating* pair since v0.6.3 → v0.6.4: core schema **146 → 150** (search
stays at 18). That makes it the only pair for which `restore-refuse` — restore.sh
refusing a dump that is AHEAD of the pinned binary — has a real input; the
v0.6.4 → v0.6.5 run recorded it not applicable and v0.6.6 inherited that by delta.

v0.7.4 → v0.7.5 is not worth a host: both embed 150, so it degenerates into the
dirty-ledger shape v0.6.5 already covered.

## The invocation

```
REC03_OLD=v0.6.6 \
REC03_NEW=v0.7.5 \
REC03_INJECT=column \
REC03_INJECT_TABLE=federation_deliveries \
REC03_INJECT_COLUMN=authored_remote_comment_id \
REC03_INJECT_TYPE=UUID \
  ssh root@HOST 'bash -s -- <phase>' < tests/rec03-upgrade-rollback.sh
```

`REC03_SAME_SCHEMA` **must stay unset**: 146 ≠ 150. The driver now refuses the
contradiction in both directions — setting it on this pair aborts `backup2` with
the captured `146 -> 150` in the message, so the ahead-of-binary refusal cannot be
skipped by accident, and leaving it unset on a non-migrating pair aborts for the
mirror-image reason.

Phases, in order: `install → data → fp <label> → backup → inject → upgrade-fail →
recover → backup2 → rollback → restore-refuse → repin → restore-ok → split →
report`.

## The injected failure, and why this column

The injection must clash with a column one of 0147–0150 adds **without**
`IF NOT EXISTS`, on a table that already exists at schema 146 — otherwise the
pre-creation itself errors and the drill fails at the wrong step. Read at tag
`v0.7.5`:

| Migration | Shape | As an injection target |
|---|---|---|
| `0147_authored_remote_comments` | new table + two nullable FK columns + a widened CHECK | **chosen** — see below |
| `0148_ipfs_control` | two new tables + one index; adds no column at all | no candidate |
| `0149_ipfs_admission` | 11 columns on `media_ipfs_pins` (exists since 0071), two indexes, new table `ipfs_capacity` | usable, but lands the failure at the *third* pending migration |
| `0150_ipfs_copy_cleanup` | new table + 5 columns on `ipfs_capacity` | unusable: `ipfs_capacity` does not exist at 146 |

None of the four uses `IF NOT EXISTS`, so the column shape applies and no
fallback (a pre-created table or index name) is needed.

Chosen: **`federation_deliveries.authored_remote_comment_id`**, from
`migrations/0147_authored_remote_comments.up.sql:72-74` at tag `v0.7.5`:

```sql
ALTER TABLE federation_deliveries
    ADD COLUMN authored_remote_comment_id UUID
        REFERENCES authored_remote_comments (id) ON DELETE SET NULL;
```

`federation_deliveries` is created by `0038_federation_deliveries.up.sql`, so it
is present at 146, and `authored_remote_comment_id` appears in no migration ≤ 0146
(checked over the whole v0.6.6 migration set). 0149 would work too, but 0147 is
the **first** pending migration, which is what makes the recovery target derivable
rather than guessed — see below.

The driver builds both halves from the three parameters, so they cannot drift:

```
inject      ALTER TABLE federation_deliveries ADD COLUMN authored_remote_comment_id UUID
undo        ALTER TABLE federation_deliveries DROP COLUMN authored_remote_comment_id
```

The injected column is deliberately bare `UUID` — no `REFERENCES`, no `NOT NULL`.
The clash the migrator must hit is on the column **name**, and accepting a type
field rich enough to carry a `REFERENCES` clause would mean accepting operator SQL.

## Expected ledger after the failed upgrade, and the recovery `force`

golang-migrate stamps the ledger at N and marks it **dirty before** running
migration N, clearing the flag on success — `Status.Dirty` in vidra-core
`internal/dbmigrate/dbmigrate.go` ("golang-migrate marks the ledger dirty before
running each step and clears it on success, so a dirty row means the schema is in
an unknown state and needs a human"), and `Up` refuses outright on a pre-existing
dirty ledger. So:

- **Expected after `upgrade-fail`:** core ledger **147 dirty**, search 18 clean,
  v0.6.6 containers still serving, all probes 200, fingerprint unchanged, and
  `deploy.sh` exit 1 with `CORE MIGRATION FAILED … The stack has NOT been
  restarted`.
- **Expected recovery `force`: `146`** — the newest *fully applied* migration,
  which for a failure at the first pending migration is exactly the pre-upgrade
  version. The driver does not take that as a literal: `backup` reads the clean
  ledger off the host and `force_target()` refuses unless the dirty version is
  exactly pre+1, because a failure at (say) 0149 would mean 0147 and 0148 had
  already applied and forcing back to 146 would re-run them. `migrate force` runs
  **no SQL** (`Force` in the same file), so naming the wrong version strands the
  database — which is why it is derived and then checked rather than typed.
- **`--yes-i-know` stays operator-invoked**, per `cmd/api/migrate.go`; no down
  migration runs anywhere in the drill.

**One expectation this PR did not verify, to check on the host before the force.**
0147's clashing `ALTER` is its *fourth* statement: `CREATE TABLE
authored_remote_comments` and two indexes precede it. golang-migrate's postgres
driver executes a migration file as a single multi-statement `Exec`, which
PostgreSQL runs as one implicit transaction, so the expectation is that the whole
of 0147 rolls back and the generated `DROP COLUMN` is the only undo needed. That
was **not** proven here. During `recover`, before forcing: confirm
`authored_remote_comments` does **not** exist. If it does, the file was not
atomic — drop it (its two indexes go with it) and note the finding, because the
re-run would otherwise die on `CREATE TABLE … already exists`.

## What each phase is expected to show

| Phase | Expected |
|---|---|
| `install` | v0.6.6 installed from its released `install.sh` via the git path, `deploy.sh` exit 0, ledgers **146 / 18** |
| `data` | fixture published, fingerprint recorded (original + HLS master + first segment) |
| `fp <label>` | the same fingerprint at every later checkpoint — the drill's "no data was harmed" assertion |
| `backup` | pre-upgrade dump at 146; `pre_core_version=146` captured into the facts (this is what `recover` forces back to) |
| `inject` | the `ADD COLUMN` above succeeds; ledger still 146 clean |
| `upgrade-fail` | deploy aborts in the migrate step, **no restart**; ledger 147 dirty; v0.6.6 still serving |
| `recover` | `migrate version` → `version=147 dirty=true`; undo; `force 146`; re-run applies 147–150; ledger **150 / 18**; `post_core_version=150` |
| `backup2` | post-upgrade dump at 150 + a marker rename, so the two later restores are distinguishable |
| `rollback` | `rollback.sh v0.6.6` exit 0 on schema 150 — **the claim the owner needs.** The v0.6.6 migrator should log `schema version 150 is newer than this binary's newest migration 146; nothing to apply` (`LedgerAheadMessage`) and change nothing. This is the one-release schema-compat policy being exercised rather than inferred; 0147–0150 are all additive (new tables, nullable or defaulted columns, one *widened* CHECK), so v0.6.6 code has nothing renamed, dropped or narrowed under it |
| `restore-refuse` | the 150 dump refused under v0.6.6 pins **before** the drop, counts byte-identical, stack still serving. First time this case has had an input since v0.6.3 → v0.6.4 |
| `repin` | back to v0.7.5, `deploy.sh` → already at 150 |
| `restore-ok` | the 146 dump restored under v0.7.5, migrations applied 146 → 150, marker rename gone, fingerprint identical |
| `split` | OPS-01 subset: `EXTRA_COMPOSE_PROFILES=worker` + `API_ROLE=api`, second upload transcoded by the worker |

Only a real run can turn any of these into a verdict. In particular the
additive-migration reading above is a reading of four `.up.sql` files, not a
rehearsal — which is exactly what REC-03 exists to replace.

## The two historical runs, restated in this parameter shape

The driver no longer defaults to anything, so the recorded runs need their env
spelled out. These reproduce the same drills; the records themselves
([v0.6.4](runtime-acceptance-rec03-v0.6.4.md),
[v0.6.5](runtime-acceptance-rec03-v0.6.5.md)) are unchanged and remain the
evidence.

```
# v0.6.3 -> v0.6.4  (core 144 -> 146; the column-conflict injection)
REC03_OLD=v0.6.3 REC03_NEW=v0.6.4 REC03_INJECT=column \
REC03_INJECT_TABLE=storage_migrations REC03_INJECT_COLUMN=paused_reason REC03_INJECT_TYPE=TEXT

# v0.6.4 -> v0.6.5  (core 146 -> 146; nothing to migrate, so a dirty ledger)
REC03_OLD=v0.6.4 REC03_NEW=v0.6.5 REC03_INJECT=dirty REC03_SAME_SCHEMA=1
```

Two honest differences from what those runs actually executed:

- The v0.6.4 run injected `… ADD COLUMN paused_reason TEXT NOT NULL DEFAULT ''`.
  The parameter shape produces bare `TEXT`, because the type field is an
  allowlist rather than free SQL. The migrator fails identically — the clash is on
  the column name — but the DDL is not byte-identical to the `inject.log` line.
- Its recovery `force 144` was a literal; it is now derived from the ledger
  `backup` captured. For that pair the derived value is the same 144.

## Not covered by this drill, whatever it shows

The bundle (no-git) upgrade path; S3 storage and the media half of a restore
across stores; a search-ledger change (18 throughout); ACME / public DNS; browser
decode (segments are fetched and hashed through the api proxy); migration timing
against populated tables (a one-video catalogue); and the rest of OPS-01
(settings propagation, kill-mid-transcode, dependency outage, leader failover, a
second worker or host).
