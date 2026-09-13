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

A **rollback** is stopped only by what predicts the wrong bytes or untrustworthy
metadata: a digest that contradicts a record, an unreadable record, an
unparseable tag. A triple no record pairs, including `rollback.sh --user <tag>`
under the core and search being served, continues with a WARNING that names what
was not verified.

## Who adds one, and when

The release owner adds `releases/<tag>.json` on `main` **after** that release's
images are published and verified, in the same PR as the release's evidence.
Copy the values from the frozen verification manifest (`deploy/release-preflight.py`
writes it), and extend `tests/release_mapping_test.py`'s evidence cross-check to
the new file.

The record cannot live inside the release's own meta tag. `deploy/release.sh`
pushes this repository's tag **before** it creates the component releases, because
vidra-core's release-assets workflow builds the bundle from that tag. No image
exists at that moment, so there is no digest to record. A tree pinned to tag
`vN` (by `deploy/pin-release.sh`, or an unpacked `vN` bundle) therefore runs `vN`
**unverified with a WARNING** instead of being refused, provided all three tags
are `vN`. The record for `vN` reaches hosts through the next meta tag or bundle.
That is also what rollbacks to `vN` read.

**This is an open gap.** An upgrade to the newest release compares only the tag
strings, and a wrong digest pin only warns. It closes when the record ships
**inside the release artifact**. vidra-core's release-assets workflow (or
`deploy/release.sh`) would emit `releases/vN.json` after the images publish, and
the vN bundle would carry it. `deploy.sh` on a vN bundle would then verify the
digests against a record that shipped with vN.

## Releases without a record

Nothing before **v0.6.4** has a record. A triple whose tags all predate the oldest
record is deployed and rolled back with a WARNING, so historical releases keep
working. A pre-v0.6.4 tag next to a recorded one is refused in a deploy, because
no record pairs them, and warned about in a rollback.

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
