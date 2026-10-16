# Source-pinned release stack CI

`stack-e2e` runs the same boot, multi-chunk upload, transcode, HLS-byte and
search assertions in two independent matrix lanes:

- `stack-e2e` checks out each component's floating `main`.
- `pinned-release-e2e` selects the newest validated `releases/*.json`, calls
  `deploy/release-mapping.py resolve`, and checks out its recorded immutable
  component commits. It refuses the deployment resolver's unverified fallback.

The pinned lane verifies each actual checkout SHA and the core/search migration
ceilings before boot. Both lanes upload separate artifacts containing their
selected refs and actual checkout commits. The newest release changes only
when a real release record lands; CI never invents a release or digest.

This is source compatibility evidence. The frontend checkout supplies the
Compose build context; this driver exercises the API/media/search chain and
does not run a frontend browser. Neither lane tests published image digests,
browser decode, production rate limits, malware scanning, or runtime recovery.
The lanes remain outside the merge-required manifest, as the existing media
lane was; a malformed workflow still fails the required workflow guard.

Local selection of the real current release:

```sh
python3 scripts/ci/resolve-stack-refs.py select --mode release --evidence /tmp/stack-source-refs.json
python3 -m unittest discover -s tests -p pinned_release_ci_test.py
```

Workflow tests use PyYAML 6.0.3, which meta CI ensures is available before the
unit suite. The deployment resolver itself remains Python standard library only.

## Required configuration and boot lanes

`meta-ci` also runs `pinned-release-validate` and `pinned-release-boot`, both
required in `.github/required-checks.txt`. They share the complete step sequences
of the existing floating `validate` and `boot` jobs through YAML anchors. Each
job has its own source mode and artifact name, so adding an assertion to the
floating lane also adds it to its recorded-release counterpart.

Before Compose validation or boot, all three checkouts must match the newest
record's immutable commits and the core/search migration ceilings must match
that record. Bootstrap's release-mode update uses the same three recorded SHAs,
then verifies them again before evidence is uploaded. Its floating mode retains
the default branch update path.

The pinned boot lane additionally reads both database migration ledgers after
the service-image migration checks. Each must contain exactly one clean row at
the recorded version; wrong versions, dirty or absent rows, and duplicate rows
fail the lane. Selected refs, checked-out commits and applied versions are saved
in `stack-source-refs.json`, alongside raw ledger rows and Compose logs in the
separate `meta-pinned-release-validate` / `meta-pinned-release-boot` artifacts.
These remain source compatibility checks, without publishing a release or
qualifying its image digests, recovery drills, browser playback or stopwatch tests.

## Remaining release and operational prerequisites

At preparation on 2026-10-16 the newest committed record is v0.7.7: core/user
v0.7.7, search v0.7.3, schema ceilings 151/18. There is no v0.7.8 record.
Before publishing v0.7.8, merge the P0 slices and obtain green required checks
on main in all four repositories. Run release.sh from meta main at origin/main,
then freeze real published image digests with release-preflight.py, land the
complete migration inventory and matching env-template pins, and retain the
actual preflight evidence. This CI change performs none of those release acts.

The v0.7.7 REC-03 document remains explicitly PREPARED, NOT EXECUTED; its
predictions cannot be promoted into acceptance results. REC-03 needs a named
disposable Ubuntu lab host, reachable published OLD/NEW release records and
images, and an injection chosen from the first pending migration. Replacement
restore needs a distinct clean host with no existing deployment or containers,
the transferred backup/config evidence, and the saved sealing-key chain. A
shared development Docker daemon does not meet that replacement-host condition.

The stopwatch protocol separately requires three real testers, a blank server
and SSH access for each, and preconfigured DNS (or an explicitly recorded
plain-HTTP run). No stopwatch results or executed v0.7.7 REC-03/recovery records
are present at preparation. See `runtime-acceptance-rec03-v0.7.7-prepared.md`,
`install-stopwatch-test.md` and the replacement-host guards in
`tests/recovery_release_acceptance.py`; source-pinned CI cannot supply those
external hosts, people or measurements.
