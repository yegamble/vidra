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
| 2 | Storage: presign, canonical-vs-delivery, migration jobs, GC safety | Not started (seams defined) |
| 3 | Media pipeline: CMAF, DASH, packager abstraction, codec profiles, hw transcode, worker scale-out | Not started (seams defined) |
| 4 | Delivery: playback sessions, CDN, P2P, engine adapter, QoE | Not started (seams defined) |
| 5 | Enterprise: multi-CDN, steering, DRM/KMS, multi-region | Not started |

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
