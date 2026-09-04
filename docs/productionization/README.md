# Vidra Productionization Program

**Goal: WordPress-level installation simplicity with an architecture capable of growing toward
serious enterprise video infrastructure.**

A hobbyist installs Vidra on one VPS in minutes. A company later swaps local Postgres for managed
Postgres, local storage for S3, local delivery for a CDN, one worker for a fleet, HLS-only for
HLS+DASH, clear media for DRM — **without replacing Vidra itself**. Complexity appears only when
the operator needs the corresponding capability.

This directory is the program's tracking surface. Update the checklists here as work lands.

## Documents

| Doc | Contents |
|---|---|
| [architecture-today.md](architecture-today.md) | How Vidra actually works right now (audit snapshot, 2026-08-19) + the do-not-touch inventory |
| [interfaces.md](interfaces.md) | The interface seams established early so later phases are additions, not rewrites |
| [phase-1-install-and-operate.md](phase-1-install-and-operate.md) | Installer, setup engine, wizard, `vidra` CLI, doctor/update, managed Caddy |
| [phase-2-storage.md](phase-2-storage.md) | Canonical-vs-delivery separation, presigned URLs, storage migration, GC safety |
| [phase-3-media-pipeline.md](phase-3-media-pipeline.md) | CMAF, DASH, packager abstraction, codec profiles, hardware transcode, worker scale-out |
| [phase-4-delivery.md](phase-4-delivery.md) | Playback sessions, CDN abstraction, P2P, player engine adapter, QoE |
| [phase-5-enterprise.md](phase-5-enterprise.md) | Multi-CDN/steering, DRM/CENC/KMS, multi-region |
| [risks.md](risks.md) | Program-level risk register |

## Audit 2026-09-03 (second pass, full program)

Every work item in phases 1-5 was re-verified against the code at `main`
(core `9507f66`, user `4892bdd`, search `e8a1f76`). **Nothing was refuted** — no item claims
something the code does not do. All gates green: core `make ci` (incl. `test-race`), user
`npm run ci` (622/622), meta `shellcheck -x` + `tests/install_test.sh` + prod compose render
with the port/volume invariants asserted; CI green on all four repos, including core's
`ipfs-integration` and `ipfs-private-integration` and user's `frontend-e2e-backed`.

Corrections this pass made (all in place, dated):

- **phase-1 item 11 was wrong**, and contradicted the code's own written rationale: the three
  deploy gates do *not* all run in all three scripts. `require_real_domain` and
  `require_dns_points_here` are deliberately `deploy.sh`-only — refusing an emergency rollback
  over a cosmetic file check would be the wrong trade (`deploy/deploy.sh:236-239`).
- **phase-4's "Nothing calls `Purge` automatically yet"** was stale; purge is wired at
  eight-plus call sites. Header promotion is still gated, but on *exercise against a live edge*,
  not on the wiring.
- **phase-4 item 5(c)'s "nothing measures gateway fetch outcomes"** was partly stale — the
  viewer-toggled IPFS path is measured today.
- **phase-5's download-gate purge gap** was closed by core#149 the same week it was recorded.
- Counts that grew: `varErrorf` sites 88 → 126, doctor checks 18 → 26, infra capabilities
  13 → 14 (and `cdn`/`drm` now exist, retiring an "aspirational" aside).
- **phase-1 item 17 deviation (a)** is closed: `release-assets.yml` has executed; v0.6.1 ships
  `SHA256SUMS`, the bundle and four CLI binaries.

Genuine code defects found this pass (tracked, not doc drift):

1. **The settings-version poller never runs in a worker** (`vidra-core/cmd/api/main.go:1427`),
   and the comment justifying that gate is false — a `VIDRA_ROLE=worker` process reads the
   instance-settings cache constantly, so on the split topology `operations.md` recommends,
   every runtime toggle is boot-frozen while the admin UI reports success.
2. **The S3 storage layer is unexercised by automation** — six `//go:build integration` files
   self-skip on every run because `S3_TEST_ENDPOINT` is never set and no S3 service exists in
   `backend-integration.yml`, while production runs S3.
3. **QoE delivery-source attribution is wrong for Safari/native-HLS and progressive playback** —
   both report as `api-proxy`, so a CDN-specific regression on Apple clients is invisible on the
   admin page built to show it.
4. **IPFS delivery has no runtime kill switch** (boot config only, unlike its `presign`/`cdn`
   neighbours), and `env/production.env.example` documents no IPFS keys at all.

## Product philosophy (binding)

1. **Progressive complexity.** The default install asks the fewest possible questions
   (domain → storage → admin account → install). Advanced infrastructure lives behind an
   explicit Advanced path. UI speaks product language ("Where should Vidra store your videos?"),
   never infrastructure language ("Select canonical MediaStorageProvider implementation").
2. **No fork.** Same core, same interfaces, different providers, different scale. A standalone
   server and a large deployment speak the same configuration and application concepts. Nothing
   may be baked into an image that ties it to one operator (see the runtime-origin work item).
3. **One configuration engine.** The web wizard, CLI wizard, non-interactive installer, config
   files and env vars are all fronts for a single Go setup engine. No parallel setup logic.
4. **Docker is an implementation detail.** Users think "Vidra", not "seven containers". The
   `vidra` CLI wraps compose; advanced admins can still use Docker directly. Compose is one
   deployment implementation, not the fundamental architecture.
5. **The Go API must be removable from the media byte path.** At scale: auth → signed playback
   authorization → viewer fetches media from CDN/origin directly. (Today every byte proxies
   through the API; that stays the authoritative fallback forever.)
6. **Own operational complexity.** `vidra doctor` diagnoses and suggests fixes instead of dumping
   Go errors. Upgrades are one command with backup, migration, health-validation and rollback.
7. **Never sacrifice usability for architecture — and never hide dangerous actions.** Sensible
   automatic behavior plus advanced overrides; a basic admin sees "Vidra configured your video
   server", an advanced admin can inspect exactly what was configured.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Production-ready basic install: installer, setup engine, web wizard, `vidra` CLI, doctor/update, managed Caddy, owner bootstrap | **All 20 work items shipped** (2026-08-19 → 2026-08-21); first real-host install pending an operator |
| 2 | Storage: presign, canonical-vs-delivery, migration jobs, GC safety | **DONE 2026-08-21** — all 8 items (core#58-#63, user#57); exit criteria validated end-to-end on a real local→MinIO migration |
| 3 | Media pipeline: CMAF, DASH, packager abstraction, codec profiles, hw transcode, worker scale-out | **DONE 2026-08-23** — all 11 items merged (core#64-#71, meta#18/#19, user#58); exit criteria E2E-validated on a live stack 2026-08-22 |
| 4 | Delivery: playback sessions, CDN, P2P, engine adapter, QoE | **6 of 7 items merged 2026-08-23** (core#74-#77, user#59); item 5 (multi-CDN) is phase 5, P2P closed DEFER. Carry-forward: every media response is still `private` — header promotion stays gated on purge being exercised against a live edge |
| 5 | Enterprise: multi-CDN, steering, DRM/KMS, multi-region | **Floor merged, modules open.** Waves A/B/C (core#80-#82) + admin/settings/purge waves (core#115-#121, user#92-#101) all merged; items 1-3 (multi-CDN, steering, shielding), 5 (Shaka CENC), 8c (live externalization), 9-remaining and 10 (multi-region) are open |

Phases overlap deliberately at the interface level: earlier phases cut the seams
(see [interfaces.md](interfaces.md)) that make later phases possible without rewrites.

## Working rules for this program

- **Repository-first.** Derive facts from files, never from prose/docs — several runbook claims
  are already stale (see risks.md "doc drift").
- **Retain good code.** The audit produced an explicit do-not-touch inventory
  (architecture-today.md). Wrap battle-tested scripts; don't rewrite them.
- **Test after each meaningful change.** Full Playwright e2e is flaky under CPU contention —
  prefer targeted suites locally; full suites in CI.
- **Fail loud.** The env-template design (blank `:?` secrets, deliberately malformed
  placeholders) and compose render asserts are load-bearing safety features. Generators emit
  *into* this format.
