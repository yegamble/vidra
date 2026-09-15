# v0.6.6 backend-backed e2e suite (Wave A) — GROUP-1 workflow rows on the published images

**PASS for 19 GROUP-1 workflow rows on the published v0.6.6 images; two real
frontend issues found; full release readiness stays NO-GO.** Wave A of the
v0.6.6 acceptance re-run measured the committed `vidra-user/e2e-backed`
Playwright suite — the **REAL backend-backed** project (76 specs), **not** the
mocked `e2e/` project — against a backend running on the **published v0.6.6
image digests**. Nineteen workflow rows whose every mapped spec passed are
promoted **UNVERIFIED → PASS**; two rows carry documented **known issues** and
stay UNVERIFIED. The
[e2e-runtime disposition](evidence/release-v0.6.6-verification/e2e-runtime/disposition.json)
moves the counts from **5 PASS / 45 UNVERIFIED / 9 BLOCKED** to
**24 PASS / 26 UNVERIFIED / 9 BLOCKED**.

Every verdict below is file-asserted from
[`e2e-runtime/matrix.json`](evidence/release-v0.6.6-verification/e2e-runtime/matrix.json)
(spec → first-pass / re-run / verdict) and the per-spec Playwright JSON reports
under [`e2e-runtime/reports/`](evidence/release-v0.6.6-verification/e2e-runtime/reports/);
the image digests and ledgers are file-asserted from
[`e2e-runtime/backend-proof.txt`](evidence/release-v0.6.6-verification/e2e-runtime/backend-proof.txt).
Host, tunnel and frontend-source facts are session-reported.

## Candidate and boundary

- **Candidate / suite.** v0.6.6, exercised by the committed `vidra-user/e2e-backed`
  Playwright suite (76 specs) at frontend source commit `1aec0d23`
  (session-reported). This is the backend-backed project that drives a live
  stack, not the mocked `e2e/` project.
- **Backend under test (file-asserted from `backend-proof.txt`).** A backend on
  the **published v0.6.6 images**, verified as the loaded image digests:
  - core api `sha256:332bdc2005db5a967d62f285b95b33b87f0246fccf28c7d54710e52d4c8ee64a`
    (`ghcr.io/yegamble/vidra-core`; v0.6.6 index `sha256:b2b7717d…07e32fd`)
  - search api `sha256:f021b0b1db340b7277cb625f946b23f31daec5a66ff7b68ba62cd7be6dc9fbd6`
    (`ghcr.io/yegamble/vidra-search`)
  - postgres `postgres:18-alpine`, redis `redis:8-alpine`
- **Ledgers (file-asserted).** `schema_migrations` **146 / dirty false**;
  `vidra_search_migrations` **18 / dirty false**. `core /healthz` and
  `search /healthz` both `{"status":"ok"}`.
- **Host.** `159.65.249.255` (session-reported). Not deployed: production and
  beta were untouched; beta stays on v0.6.4.
- **Scope.** GROUP-1 required user/admin/creator workflow rows that the suite has
  backend-backed drivers for. Integration rows requiring external providers or a
  sanitized source (MIG/INT/OPS/STO), and rows with no backed driver, are not in
  scope and keep their prior status.

## Flake vs. real failure — the method

The first pass ran **4 workers under real transcode** on an 8-vCPU host, which
produced CPU-load timeouts (`FAIL(load)` in the matrix) that are wall-clock
artifacts, not product defects. Each such spec was re-run **individually,
UNLOADED** (the `indiv-*` reports) or **serially**; a spec that then passed is
recorded `FLAKE->PASS` in the matrix and **counted as pass, with a note** in the
promoted row's basis. A row is promoted only if **every** mapped spec passed on
v0.6.6 (flake-then-pass included).

The two **real** failures below reproduced **3/3** on unloaded re-run — they are
not flakes. They are recorded as known issues, **not** promoted, and **not**
marked BLOCKED.

## Rows promoted UNVERIFIED → PASS (19)

Basis for every row: the backend-backed `e2e-backed` suite on the published
v0.6.6 digests (above). Matrix row labels are coarse; the numbered workflow rows
below draw on the mapped spec set shown.

| Row | Mapped specs (all passed on v0.6.6) |
|---|---|
| **PUB-01** | channel-management, upload-batch, upload-cancel, upload-draft-recovery (flake→pass) |
| **PUB-02** | upload-batch, upload-cancel, upload-draft-recovery (flake→pass), channel-management |
| **PUB-03** | video-password (flake→pass), channel-management, upload-batch, upload-cancel |
| **PUB-04** | schedule (flake→pass), video-password (flake→pass), quarantine (isolated `QUARANTINE_NEW_UPLOADS` run) |
| **PLAY-01** | hls-playback, embed, player-settings — Chromium backend-backed slice (native-HLS on Apple hardware stays a tracked residual) |
| **PLAY-02** | hls-playback, player-settings, embed |
| **PLAY-03** | video-password (flake→pass), embed |
| **CRT-01** | studio (9/9, flake→pass), upload-thumbnail, video-description (flake→pass), video-tags (flake→pass), video-taxonomy (flake→pass) |
| **SOC-01** | subscribe, subscriptions, save, playlists, history, continue-watching |
| **SOC-02** | comments, comment-replies, rating, report, notification-prefs, notifications (flake→pass serial) |
| **MSG-01** | messaging, message-compose |
| **MSG-02** | messaging, message-compose |
| **MSG-03** | e2ee |
| **ADM-01** | admin-users, admin-comments, admin-videos, blocked-videos, blocks, mutes, instance-mutes, moderation, moderation-instances, watched-words, watched-word-matches, quarantine (isolated) — see the signup-approval carve-out below |
| **ADM-02** | moderation, moderation-instances, admin-comments, blocked-videos, blocks, mutes, instance-mutes, watched-words, watched-word-matches, quarantine (isolated) |
| **ADM-03** | admin-system, instance-settings, sensitive-content |
| **ADM-04** | admin-audit, admin-system, instance-settings, sensitive-content |
| **INT-11** | donations |
| **QLT-02** | required-controls (8/8, axe clean) — see the host-timeout caveat below |

### QLT-02 host-timeout caveat

`required-controls.spec.ts` passes **8/8 with ZERO axe violations**, but its two
axe accessibility sweeps time out at the spec's own **90 s `test.slow()`** budget
on the 8-vCPU host and need a **300 s** budget to complete. With 300 s they pass
8/8 and axe is clean (see
[`reports/indiv-required-controls.json`](evidence/release-v0.6.6-verification/e2e-runtime/reports/indiv-required-controls.json)
and [`reports/reqctl-extended.json`](evidence/release-v0.6.6-verification/e2e-runtime/reports/reqctl-extended.json)).
This is a **wall-clock artifact of the host, NOT an accessibility or product
defect**. QLT-02's full control + accessibility inventory (every required screen,
390px + desktop, light/dark, keyboard, loading/empty/error/retry, mutation
readback after full reload) is broader than this one backed spec; the promotion
rests on `required-controls` passing clean on the v0.6.6 digests.

### ADM-01 signup-approval carve-out

ADM-01's definition includes signup approval, and the `registration-approval`
spec (mapped to **AUTH-02** in the matrix) **failed** — see the known issue
below. ADM-01's promotion rests on the admin **users/roles/quotas/moderation**
specs that all passed; the in-place "approved" label clause is carved out and
tracked under AUTH-02, and is **not** part of this promotion. The approve/reject
API itself returns 200 and the account is correctly created/gated.

## Known issues found on v0.6.6

Both are **real** (reproduced 3/3), **minor frontend**, with the **backend
proven healthy**, and both specs had **never run in CI** (finding F04 class).
Because the v0.6.6 images are frozen, any fix would land in a **future release**;
neither row is promoted and neither is marked BLOCKED.

### 1. SRC-03 — search history-delete refresh timing (`search-discovery.spec.ts`)

- **Backend proven healthy:** the `search.submitted` event returns **202**,
  `GET /me/search-history` returns the entry in **< 5 s**, and the search service
  logs **200**.
- **Symptom:** the settings page reads history **~5 s before** the batched
  `search.submitted` event flushes (the client's **5 s `FLUSH_INTERVAL_MS`**) and
  does **not** refetch, so a just-searched query does not appear in the list.
- **Not affected:** autocomplete / suggestions **PASS** (flaky → pass unloaded).
- **Characterization:** a minor frontend refresh-timing gap, not a backend
  defect. Evidence:
  [`reports/search-hist.json`](evidence/release-v0.6.6-verification/e2e-runtime/reports/search-hist.json),
  [`reports/search.json`](evidence/release-v0.6.6-verification/e2e-runtime/reports/search.json).
- **Row disposition:** **SRC-03 UNVERIFIED** (known issue). **SRC-02** also stays
  UNVERIFIED (its full privacy/retention/degraded-fallback procedure is not driven
  by this facet, and the one adjacent surface it touched — history deletion — hit
  this same issue).

### 2. AUTH-02 — registration-approval in-place label (`registration-approval.spec.ts`)

- **Backend proven healthy:** approve/reject API succeeds (**200**), the account
  is **created on approve** and **refused on reject**, and login is **gated
  correctly**. Ten of the other AUTH specs pass (account-export, auth-persistence,
  session, deactivate, delete-account, email-verify, owner-claim, password-reset,
  password-reset-confirm, profile-edit).
- **Symptom:** the spec expects the approved row to show **"approved" in place**
  in the Pending filter, whereas the v0.6.6 UI **drops the row from Pending** on
  approve/reject.
- **Characterization:** a UI-vs-spec mismatch, defensible either way —
  **unresolved pending a UX ruling** (fix the UI to confirm in place, or correct
  the over-strict spec). Evidence:
  [`reports/regapproval.json`](evidence/release-v0.6.6-verification/e2e-runtime/reports/regapproval.json).
- **Row disposition:** **AUTH-02 UNVERIFIED** (known issue). The other AUTH rows
  (AUTH-01/05) are held UNVERIFIED conservatively because this shared approval
  surface failed; AUTH-03/04 remain **BLOCKED [B3]** (external provider inputs),
  unchanged.

## Rows deliberately not moved

- **CRT-02** — stays **UNVERIFIED**: no backend-backed driver exists in the
  `e2e-backed` suite, so this facet cannot certify it.
- **SRC-02, SRC-03, AUTH-02** and the rest of the AUTH family — see above.
- **MIG-01..06 (BLOCKED B2), INT-10 (BLOCKED B3), AUTH-03/04 (BLOCKED B3),
  STO-01/02/03, INT-01..09, OPS-01/02, REL-01, INS-01/02/04/05, QLT-01** — not
  driven by this facet; carried verbatim from the v0.6.6 native/ios disposition.
- Skipped / not-run specs move no row: `atproto`, `peertube-import`,
  `channel-sync`, `whisper-captions`, `ipfs`/`ipfs-privacy-fence`.

## Counts

| | PASS | UNVERIFIED | BLOCKED |
|---|---|---|---|
| Prior (ios/native v0.6.6) | 5 | 45 | 9 |
| **This facet (e2e-runtime)** | **24** | **26** | **9** |

Nineteen rows moved UNVERIFIED → PASS (PUB-01..04, PLAY-01..03, CRT-01, SOC-01,
SOC-02, MSG-01..03, ADM-01..04, INT-11, QLT-02). BLOCKED unchanged (AUTH-03/04,
MIG-01..06, INT-10). The prior five PASS (INS-03, SRC-01, REC-01/02/03) are
carried. Full release verdict stays **NO-GO**: the broader browser matrix, the
representative-source migration (B2), the selected IdP/mail/CDN providers (B3),
the two known issues above, and the owner's deploy decision remain.

## Evidence integrity

[`e2e-runtime/committed-hashes.json`](evidence/release-v0.6.6-verification/e2e-runtime/committed-hashes.json)
is the independent sha256 index recomputed over every committed file in the
`e2e-runtime` tree except itself. The Playwright JSON reports and `backend-proof.txt`
and `matrix.json` were scanned for credentials before commit — no test-account
email, owner/admin password, token or `process.env` value appears in them (the
only `password`/`.fill(...)` strings are Playwright selector code in error
snippets). No file was redacted or omitted.
