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

**What the tree cannot prove, the deploy fetches.** When a verdict turns on a
record this tree has no copy of, `deploy/lib.sh`'s `fetch_release_record`
downloads `releases/<tag>.json` from this repository over https during
preflight — before the checkout sync, the dump, the pull and the migrations —
and re-runs the checker with `--extra-record`. The pairing and any digest pin
are then held against the real record after all, and a **contradiction stops
the run** exactly as it would for a record on disk. The fetched copy is used
for that one run and written nowhere.

The same record, and the same fetch, is what `deploy/pin-release.sh` reads to
decide what to WRITE into the three `VIDRA_*_TAG` keys — it pins each component
at the tag the record pairs it at, rather than putting one tag in all three (it
used to, and a core-only release then pinned an image that does not exist). With
no record it falls back to the uniform pin and warns; `--component-tag
<role>=<tag>` states the pairing by hand. See "Everyday operations" in
`deploy/README.md`.

That covers **both** shapes the newest release takes. A uniform triple
(`vN vN vN`) is the obvious one. A **core-only** release is the one that
actually shipped twice: v0.7.4 and v0.7.5 re-released vidra-core alone, so
their triples are `core vN / user v(N-k) / search v(N-k)` — not uniform, and
refused rather than merely unverified when the record is missing. The record
to fetch is the **newest of the three pinned tags**, which
`deploy/release-mapping.py --print-missing-release` decides (there is
deliberately no second semver implementation in shell). It names nothing —
and nothing is fetched — when a record here already names that release, when
every pin predates the first record, or when a tag is not release-shaped.

A fetch that fails, or a record that is fetched and then not admitted, leaves
the first verdict exactly as it was: **a refusal stays a refusal.** Nothing
here is ever looser than it would be without the fetch, and nothing is ever
stricter on absence.

`VIDRA_RECORD_FETCH=off` skips it entirely (airgapped hosts attempt no
request), and `VIDRA_RECORD_BASE_URL` points it at a fork's or a mirror's
records; both are read through `env_get`, from the env file or the
environment. curl, not git: a bundle host has no git anywhere.

### Trust model

A record fetched from the default URL has **the same trust anchor as a record
in the tree**: the same GitHub repository, over the same TLS, that delivered
the bundle this host is running. So the pairing check is what it always was —
a catcher for operator error (a user image from one release beside a core
image from another), not a defence against an adversary who controls that
anchor. Whoever controls the record source can block a deploy or bless one,
exactly as whoever controls the bundle source can; there is no additional
exposure here, and this feature does not pretend to remove the original.

What the admission rules do enforce is that a record is used only for what it
actually is. A fetched record is admitted only when it passes the same
`validate()` as a tree record, names the release that was asked for, pairs the
pinned triple **exactly**, describes a release this tree has no record for,
and is structurally a release: **no component tag newer than the release it
names, and at least one equal to it**. Anything else is ignored with a
warning and changes no verdict. It is not an override — a mixed triple no
record pairs is still refused, and a stale bundle still stops a deploy.

Two consequences are deliberate:

- Every log line reporting a verdict that rests on a fetched record **says so
  and names the source URL** (credentials masked), so "verified" is never
  silently a statement about bytes from somewhere else.
- Pointing `VIDRA_RECORD_BASE_URL` anywhere but the default logs a distinct
  **NON-CANONICAL** warning, because the verdict then rests on a source the
  operator chose rather than on the one that published the release.
- A stop caused by a fetched record names **both** escape knobs in the
  message, because one is not enough. A wrong — or forged — remote record must
  never trap an operator mid-incident with no way out. Turning the fetch off
  (`VIDRA_RECORD_FETCH=off`) falls back to this tree alone, which can **never**
  report verified for a release it has no record for — but what that means
  depends on the shape:
  - a **uniform** `vN vN vN` triple continues **UNVERIFIED** with the warning;
  - a triple the tree cannot pair — a **core-only** release such as v0.7.4 or
    v0.7.5 — is **still refused** by the pairing check, because pass 1's
    refusal stands once the fetch is off. `VIDRA_RELEASE_MAPPING=warn` is the
    override for that one, and it **waives the pairing check** for that run:
    the deploy then proceeds having verified nothing about whether these
    images were released together.

**What is still not verified**, and nothing here can change either:

- **Offline.** No egress, no curl, or `VIDRA_RECORD_FETCH=off` — the run keeps
  today's WARNING naming what was not checked, plus the exact `curl` to try by
  hand. A record that cannot be fetched predicts nothing about the images, so
  it may not stop a deploy.
- **The window before the record merges.** Between a release publishing and
  its record PR landing on `main`, the record does not exist *anywhere* yet.
  That closes only when the record ships **inside the release artifact** —
  vidra-core's release-assets workflow (or `deploy/release.sh`) emitting
  `releases/vN.json` after the images publish, so the vN bundle carries it.

One more honest limit on the digest half: images are pulled **by tag**, and
`deploy.sh`'s `require_embedded_migrate_tag` refuses a `<tag>@sha256:<digest>`
spelling for `VIDRA_CORE_TAG` and `VIDRA_SEARCH_TAG` before the checker runs
(see "Format" below). So the digest comparison this fetch makes reachable is
today reachable only for `VIDRA_USER_TAG`. The **pairing** assertion covers all
three. Pulling by the recorded digests remains the separate follow-up.

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
