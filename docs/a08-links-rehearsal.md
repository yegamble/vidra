# A08 disposable links rehearsal (partial)

This harness is restricted to a successful A03 disposable VM and retained A04
accounts/A06 upload. It changes the retained video's privacy and restores it to
public. A passing subset is not full A08 acceptance; see release-readiness.md.
Never point it at production. Private output directories contain diagnostics and
must remain untracked.

Prerequisites: Multipass, Docker, Node >=24, the frontend Playwright dependency
and Chromium, Python 3, and an A03 result with successful recovery. The original
v0.6.2 core lacks stored short codes, so prepare an exact-source schema-127 lab
fixture first. Build pristine git archives using the component Dockerfiles;
record each full commit/archive SHA256 in `source.json` and the Docker image IDs
under keys `vidra-core:a08-source` and `vidra-user:a08-source` in `images.json`.
The source directory must also contain that exact core's migrations directory.

Generate the bundle normally with `deploy/make-bundle.sh --core <core checkout>
--tag v999.8.0 --out <bundle.tar.gz>`. Do not edit its manifest. Save both local
images into one Docker archive. These are lab-only artifacts, not releases.

```sh
python3 tests/prepare-link-fixture.py   A03_OUTPUT SOURCE_DIRECTORY BUNDLE_TAR_GZ IMAGES_TAR NEW_PREPARE_OUTPUT
node tests/links-smoke.mjs   A03_OUTPUT A04_ACTORS A06_MP4 NEW_PREPARE_OUTPUT NEW_LINKS_OUTPUT
```

Preparation preserves existing data/search images, adjusts only the lab's image
transport/platform and two-CPU resource limit, and executes the generated normal
deploy script. A failed dump, pull, migrator, ledger check or health probe fails
the preparation. Do not bypass it. The result names the new guest installation;
subsequent lab operations must use it instead of the original A03 tree. This
advances the database; restoring old images is not a schema rollback.

The browser checks exact running image IDs, the same A06 media hash/video ID and
stored code, actual playback on canonical/legacy/timestamp routes, and the Share
dialog/embed. The private-owner phase independently probes bearer, owner-native
and anonymous asset requests and requires actual private playback. No requests
are intercepted. It emits failure screenshots privately and records cleanup
status. A failed restore is a failed run: use a fresh authenticated session to
restore privacy and verify the database before continuing.

The archived before result is deliberately FAIL. Passwords, expiry, downloaded
bytes/revocation, embed origins, source UUID mappings and discovery/metadata
surfaces remain follow-up phases; do not report zero missing acceptance from
this reproduction slice.


After the link/private subset, run `node tests/password-links-smoke.mjs` with
the same five arguments (A03, A04, MP4, prepared result, new private output).
It requires the retained video to be public with no existing passwords, creates
one temporary password, tests wrong/correct unlock and actual watch/embed
playback, and probes original/thumbnail/HLS with and without the playback token.
It restores public and deletes its password; either failed cleanup fails the
run and must be recovered before continuing. Exact running image IDs are
required. Token expiry and the remaining A08 boundaries are not covered here.
