# Platform release records

One JSON file per platform release, `releases/<tag>.json`. Each file states which
vidra-core, vidra-user and vidra-search images make up that release: tag, source
commit, registry repository, image index digest and per-platform manifest
digests, plus the core and search schema versions the release's migrators end
at.

`deploy/deploy.sh` and `deploy/rollback.sh` read this directory through
`deploy/release-mapping.py` **before they change anything**: before the checkout
sync, the pre-deploy dump, the pull, the migrations and `up -d` (deploy), and
before the env file is rewritten (rollback). A **deploy** requires the pinned
`VIDRA_*_TAG` triple to be one a record pairs. Components may carry different
tags. What is refused is a triple no record pairs, like a user image from one
release beside a core image from another. On a bundle tree, a deploy also
refuses a bundle whose tag is not `VIDRA_CORE_TAG`.

A **rollback** is stopped only by what predicts the wrong bytes or a broken env
rewrite: a digest that contradicts a record that loaded, and a target tag that is
unset or not release-shaped. A triple no record pairs, including `rollback.sh
--user <tag>` under the core and search being served, continues with a WARNING
that names what was not verified. So does a `releases/` directory that cannot be
used (missing, or holding a corrupt record for some *other* release): it says
nothing about the target's images, so the rollback continues with a WARNING that
NOTHING about the target was verified, to be fixed after service is back. The
same problems refuse a deploy.

## Who adds one, and when

The release owner adds `releases/<tag>.json` on `main` **after** that release's
images are published and verified, in the same PR as the release's evidence.
Copy the values from the frozen verification manifest (`deploy/release-preflight.py`
writes it), and extend `tests/release_mapping_test.py`'s evidence cross-check to
the new file.

The preflight also **reads** this directory: `releases/<tag>.json` is how it
learns which tag each component carries, so a core-only release (v0.7.4,
v0.7.5, which pair vidra-user and vidra-search at v0.7.3) can be frozen at all.
That is circular for exactly one run — the record does not exist yet while its
own evidence is being produced — so that first run passes
`--component-tag vidra-user=<tag> --component-tag vidra-search=<tag>` instead.
Afterwards the record makes the flags unnecessary and `--tag <release>` alone
reproduces the same tree. See "Core-only releases" in `deploy/README.md`.

The record cannot live inside the release's own meta tag. `deploy/release.sh`
pushes this repository's tag **before** it creates the component releases, because
vidra-core's release-assets workflow builds the bundle from that tag. No image
exists at that moment, so there is no digest to record. A **uniform** triple
(all three tags `vN`) that is newer than every record therefore runs
**unverified with a WARNING** instead of being refused, whatever tree it runs
from: a tree pinned to tag `vN` (by `deploy/pin-release.sh`, or an unpacked `vN`
bundle), and equally a tree on `main` — a fresh `install.sh --git`, which clones
`main` and one commit after the tag no longer sits on it, or a rehearsal lab
deploying `vN-rc1`. A typo'd uniform tag is still caught by the checkout sync
and `compose pull`. The record for `vN` reaches hosts through the next meta tag
or bundle. That is also what rollbacks to `vN` read.

**This is an open gap.** An upgrade to the newest release compares only the tag
strings, and a wrong digest pin only warns. It closes when the record ships
**inside the release artifact**. vidra-core's release-assets workflow (or
`deploy/release.sh`) would emit `releases/vN.json` after the images publish, and
the vN bundle would carry it. `deploy.sh` on a vN bundle would then verify the
digests against a record that shipped with vN.

## Overriding a refusal: `VIDRA_RELEASE_MAPPING=warn`

A **mixed** triple no record pairs, or a uniform one that falls between two
records, refuses a deploy. When that pairing is deliberate and its record has not
landed on this tree yet (a platform release that re-releases only vidra-user, a
lab), set `VIDRA_RELEASE_MAPPING=warn` in `env/production.env` or in the
environment (`VIDRA_RELEASE_MAPPING=warn ./deploy/deploy.sh`, read through
`env_get` like `VIDRA_SKIP_DNS_PREFLIGHT`). `deploy/lib.sh` logs the override
and the checker turns that one refusal into a WARNING naming exactly what was
skipped: that the images were released together, that the tags exist, and their
digests. Unset it once the record is on the tree.

It never reaches past the pairing. A digest that contradicts a record, a tag that
is unset or not release-shaped, a `releases/` directory that cannot be used and a
stale bundle all predict a real failure and still stop the deploy. An
unrecognised value is reported and ignored, so a typo neither bypasses the check
silently nor stops a rollback. In a rollback the override changes nothing: an
unpaired triple already warns there.

## Releases without a record

Nothing before **v0.6.4** has a record. A triple whose tags all predate the oldest
record is deployed and rolled back with a WARNING, so historical releases keep
working. A pre-v0.6.4 tag next to a recorded one is refused in a deploy, because
no record pairs them, and warned about in a rollback.

### Deliberately unrecorded releases

**v0.6.7 — superseded by v0.6.8 before any deployment.** Its vidra-user image
was cut one merge short of the change the release existed to ship, so the
triple it names documents an incomplete release; it was re-cut as v0.6.8 from
the same meta commit and never deployed. The record PR `deploy/release.sh`
opened for it (#218) was closed unmerged by the owner on 2026-09-15 as
"Superseded — do not merge". **`deploy.sh` refusing a v0.6.7 triple is the
intended behaviour, not a missing record**; a rollback to it still proceeds
with the WARNING above. Do not add `releases/v0.6.7.json`.

### Records frozen retroactively

**v0.6.8 and v0.6.9** were recorded on **2026-09-20**, days after they were
cut; their manifests' `created_at` says so. Their evidence is what the
preflight and the registry could still be asked on that date — the
source/image/asset/contract freeze, the `imagetools inspect` transcript and
the images' own `migrate embedded-max` answers. **Neither release was scanned,
drilled, or — as far as any committed artifact shows — deployed, and both are
superseded by v0.7.x.** A record makes a triple *verifiable*; it does not make
it accepted. What the records buy is narrow and real: a rollback to either now
verifies its digests instead of warning that nothing was checked, and a deploy
of either is no longer refused for want of a pairing.

## Format (`schema_version` 1)

Validated strictly by `deploy/release-mapping.py`. An unknown key, a short commit,
a non-`sha256:` digest or a string schema version makes the whole directory
fatal, in deploys and rollbacks alike.

```json
{
  "schema_version": 1,
  "release": "vX.Y.Z",
  "meta_commit": "<40 hex>",
  "core_schema_version": 146,
  "search_schema_version": 18,
  "components": {
    "core":   {"tag": "vX.Y.Z", "commit": "<40 hex>",
               "image": {"repository": "ghcr.io/yegamble/vidra-core",
                         "index_digest": "sha256:<64 hex>",
                         "platforms": {"linux/amd64": "sha256:<64 hex>"}}},
    "user":   {"...": "same shape"},
    "search": {"...": "same shape"}
  },
  "evidence": "docs/evidence/<optional path to the verification record>"
}
```

Images are still **pulled by tag**. The checker compares a digest only when a
tag is pinned as `VIDRA_*_TAG=<tag>@sha256:<digest>`, the one digest form compose
would honour. Today that comparison is mostly latent. The embedded-migrator floor
in `deploy.sh`/`rollback.sh` refuses that spelling for core and search before the
checker runs, so on the current scripts it only reaches a pinned user tag, or a
checker run by hand. Pulling by the recorded digests is a separate follow-up.

The record describes the images at **its** `repository`. The effective image
source, `${VIDRA_IMAGE_REGISTRY:-ghcr.io}/${VIDRA_IMAGE_OWNER:-yegamble}` as the
compose file renders it, is compared with that prefix. A fork or a mirror is
legitimate, so a difference is **UNVERIFIED with a WARNING** naming both
repositories, never a refusal, and digest pins are then not compared (a fork's
image cannot carry the upstream digest). The `evidence` key names the
verification record in this repository's `docs/`; bundles do not ship `docs/`, so
on a bundle host it is provenance to look up on GitHub, not a path to open.
