# Automatic category and language for public videos (TypeSafe Jev) — design

Date: 2026-09-20 · Status: design approved by the owner, not yet planned or built ·
Repos: vidra-core (C), vidra-user (U), vidra (M)

## 1. What this is

An optional, operator-enabled feature that fills the **category** and **language**
of public videos that have none, using TypeSafe's Jev model. It is the first of
four places where a semantic text judgment does real work in vidra, chosen to go
first because a wrong answer costs the least here: a creator changes a dropdown.

Jev is not a text generator. It is an HTTP API (`POST /v1/systemone`) that takes a
JSON *state* plus narrow *questions* and returns typed answers with calibrated
probabilities — here, one pick from a closed list per question. Facts that shape
this design, from the vendor's documentation on 2026-09-20:

| Fact | Consequence here |
|---|---|
| Text only | Judges title, description, channel name and tags — never the media |
| $0.042 per million input tokens, output free; ~0.1–0.5 s per request | Cost and latency never constrain the design; 50,000 videos ≈ $1.50 |
| 64k-token context, 32k for state plus longest question | Description is cut at 2,000 characters, the cut search already uses |
| English primary; other languages "handled but not equally well" | Language gets a stricter confidence bar than category |
| Injected instructions in the input can change the answer | Output is confined to a closed vocabulary; the model never takes a moderation action |
| The `jev-latest` alias moves when a new model ships | Pin `jev-1.13.0`; thresholds are tuned against a version |
| Hosted in the US; inputs not used for training; retention unspecified; zero retention is enterprise-only | Operator opt-in, off by default, public content only, stated plainly in the UI |

### Why this seam (verified in the code at core v0.7.5)

- A URL import reads four fields from yt-dlp — title, description, duration,
  thumbnail (`internal/ytdlp/ytdlp.go`). Category, language and tags are never set.
- A channel-sync draft is created with a title and `privacy = private` and nothing
  else (`internal/channelsync/service.go`).
- An upload defaults category and language to empty; nothing infers them.
- Category and language drive the browse filters, and language is a hard filter
  in search, so an empty value makes a video invisible to anyone who filters.

## 2. Decisions the owner made

1. **First slice:** video metadata, ahead of report triage, watched-word precision
   and a related-videos topic label (section 13).
2. **Auto-fill, not suggest.** When confident, vidra fills the empty field itself
   and Studio marks it as set automatically. It never overwrites a human value.
3. **Public content only, after publish.** A video is judged only once it is
   public and published. Drafts, private and unlisted videos are never sent.
4. **Fields:** category and language. Tags are a later slice: Jev cannot generate
   text, so tags need a separate mechanism (code proposes candidates, Jev approves
   or rejects each).
5. **Existing library:** swept only when the operator presses a button, as a
   tracked, stoppable run. Switching the feature on does not sweep the library;
   section 4.4 states exactly which videos it does reach.
6. **The API key is set in the admin panel**, with no restart and no `.env` edit,
   reusing the write-only secret mechanism the admin mail-settings work is
   building. The environment variable remains as a fallback.
7. **Architecture:** a worker that claims videos by their current *state*, not an
   event queue hooked into each publish path.

## 3. Non-goals

- No per-query use of Jev anywhere. Search and suggest have a 50 ms budget, and a
  viewer's query must not leave the instance.
- No writing of `is_sensitive`. The `hide` policy removes a video from browse and
  search; a false positive would silently disappear a creator's work.
- No comment holding, no federation inbox gating, no transcript-based features.
- No suggestion UI, no confidence display, no per-video creator notification.
- No re-judging when a title or description later changes. One judgment per video.
- No per-instance threshold settings in this version (section 6).

## 4. Architecture (vidra-core)

```
   tick (30 s, jittered)
        │  toggle on AND key present?  ── no ──▶ idle (today's behaviour)
        ▼ yes
   claim ≤ 25 eligible videos ─▶ build state ──▶ judgment.Ask ──▶ store raw answer
   (INSERT is the claim)                          (one request,        │
                                                   two questions)      ▼
                                   video.Service.ApplyInferredMetadata
                                   (guarded write → existing onUpdate hooks:
                                    federation Update, search upsert, …)
```

### 4.1 `internal/judgment` — the Jev client

Knows nothing about videos. Input: a JSON state and a set of questions. Output:
for each question, the pick and the per-option probabilities.

- Key resolution: sealed admin setting, else `TYPESAFE_API_KEY`. Read per call, so
  a key set in the admin panel takes effect on the next tick with no restart.
- `TYPESAFE_ENDPOINT` (default `https://api.typesafe.ai`), `TYPESAFE_MODEL`
  (default `jev-1.13.0`). The endpoint is operator configuration, so it uses a
  plain `http.Client` like the Whisper client, not the SSRF-guarded one.
- 5 s per-call timeout; response read through a size cap; circuit breaker with
  `searchclient`'s numbers (open after 5 consecutive transport or 5xx failures,
  30 s cool-down, one half-open probe).
- Errors are classified into closed codes — `auth`, `rate_limited`, `unavailable`,
  `bad_response` — and laundered through `safeerr`. The key joins the
  observability sensitive-key denylist.
- Only `choice` is implemented now. `noul` and `score` arrive with the slices that
  need them; nothing else in the package changes.

### 4.2 `internal/metadatafill` — policy and worker

Knows nothing about HTTP. Runs on `jobloop` beside the other workers. Unlike the
captions worker it **always starts**: its capability can arrive at runtime (a key
saved in the admin panel), so gating the start on boot configuration would strand
it. Each tick is a no-op unless the toggle is on and a key resolves.

**Eligibility** mirrors the search index's own rule, so nothing is sent that the
instance does not already serve in discovery: `privacy = 'public'`,
`state = 'published'`, not blocked, owner not unlisted, `category IS NULL OR
language IS NULL`, and no row in `video_metadata_judgments`. One more condition
separates new from existing videos (section 4.4).

**Claim.** Up to 25 videos per tick, from two sources. New videos: `INSERT INTO
video_metadata_judgments (video_id, state, lease_expires_at) SELECT … ON CONFLICT
DO NOTHING RETURNING video_id`, inserted as `running`. The primary key makes the
insert itself the claim, so two replicas can never judge the same video. Retries:
`pending` rows whose `next_attempt_at` is due, and `running` rows whose lease has
expired (a dead replica's claims), taken with `FOR UPDATE SKIP LOCKED`. At 25 per
30 s tick one replica judges about 50 videos a minute, far under the vendor's
1,200 requests a minute; a 50,000-video run takes roughly 17 hours.

### 4.3 Data model

Three new tables: the judgments below, and two small supporting tables described
in section 4.4 (`metadata_fill_runs`, and a single-row `metadata_fill_state`).

```sql
CREATE TABLE video_metadata_judgments (
    video_id         UUID PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    state            TEXT NOT NULL DEFAULT 'pending'
                     CHECK (state IN ('pending','running','done','failed')),
    attempts         INT NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_expires_at TIMESTAMPTZ,
    model            TEXT,
    judged_at        TIMESTAMPTZ,
    category_pick    TEXT,   -- category id; NULL = none_of_these or not asked
    category_prob    REAL,
    language_pick    TEXT,   -- language code; NULL = unclear
    language_prob    REAL,
    category_applied TEXT,   -- what the worker wrote; cleared when a human sets it
    language_applied TEXT,
    last_error_code  TEXT,   -- closed code only, never upstream text
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

A row's existence means "already judged", including when Jev was not confident,
so an uncertain video costs one request, ever. Raw picks and probabilities are
kept apart from what was applied: a threshold can change later and be re-applied
to rows already judged without asking Jev again. `videos` and its hot queries are
untouched. The migration number is assigned when the PR is opened (0150 is the
newest today, and other work is in flight).

### 4.4 New versus existing videos

`videos` has no `published_at` column; every publish transition bumps
`updated_at`. The automatic rule is therefore `updated_at >= enabled_since`, where
`enabled_since` is the moment the feature last became active. The worker keeps it
in the single-row `metadata_fill_state` table: sets it when it first finds the
feature active (`UPDATE … WHERE enabled_since IS NULL`, so replicas cannot
disagree), clears it when it finds it inactive. The rule the operator is told, because it is
the true one: **videos published or edited after you switch this on are filled
automatically; everything else waits for the button.**

The button creates a `metadata_fill_runs` row (`running | stopped | done`, counts,
started by). While a run is `running`, the `enabled_since` condition is lifted.
The run is projected into `job_runs` with the trigger pattern PeerTube import runs
use — one dashboard row per run, not one per video. Stop flips the row; the worker
reads it each tick. Starting a run also returns `failed` rows to `pending`.

### 4.5 Applying an answer — `video.Service.ApplyInferredMetadata`

One new service method, so an automatic fill has exactly the side effects of a
human edit. It writes each field only `WHERE <field> IS NULL AND privacy = 'public'
AND state = 'published'`, validates the value against the live vocabulary
(`IsCategory`, `IsLanguage`), records what it wrote in `*_applied`, then fires the
service's existing `onUpdate` hooks — the seam federation uses to send an Update
to remote followers.

The ordinary `Update` path gains one statement: when a human sets category or
language, that field's `*_applied` is cleared. The Studio marker is derived from
`*_applied IS NOT NULL`, so it can never claim a value a person chose — including
when they re-select the same value the worker had picked.

## 5. The request

State (public fields only):

```json
{ "video": { "title": "…", "description": "… first 2,000 characters …",
             "channel": "…", "tags": ["…"] } }
```

Two `choice` questions in one request; they run in parallel and cannot see each
other's answers.

- **category** — "Which category best describes the subject of the video in
  `video`?" Options are the instance's live list (`video.CategoryOptions()`), sent
  by label and mapped back to ids in code so custom taxonomies work. The 18
  built-in categories carry a one-line description written once in Go; custom
  categories are sent as label only. Plus `none_of_these`: "no category fits, or
  there is too little information to tell".
- **language** — "In which language are `video.title` and `video.description`
  written?" Options are the 30 codes in `video.Languages` plus `unclear`. The
  question is deliberately literal: Jev answers the question as written, and the
  language of the metadata is a proxy for the language spoken. The Studio marker
  is how a wrong proxy gets corrected.

A `choice` carries at most 255 options. An instance with more than 254 categories
skips the category question and asks only language.

## 6. Confidence bars and the evaluation gate

A field is filled only when the winning option's probability clears its bar.
**Starting values: category 0.70, language 0.90. These are placeholders taken
from the vendor's general guidance, not measurements of vidra content.** They are
Go constants in this version.

Before auto-fill is switched on for the beta instance, the bars are set from a
measurement. The beta has a labelled set already: videos imported from PeerTube
kept their human-chosen category and language. A new subcommand of the API
binary, alongside `migrate` and `verify-blobs`, samples public videos that
*already have* human values, asks Jev, **writes nothing**, and prints agreement
per probability band plus the most-confused pairs. The run and the bars chosen
from it are recorded in `docs/`. Caveat, stated in that record: creator-chosen
categories are noisy, so agreement is a floor on accuracy, not ground truth.

## 7. Failure handling

The fallback in every case is "the field stays empty" — today's behaviour.

| Situation | Behaviour |
|---|---|
| Toggle off, or no key | Worker idles. Status row: Off / Needs setup |
| Key rejected (`auth`) or `rate_limited` | The whole worker pauses; the status row says why. No per-video attempts are spent |
| Timeout or 5xx | That video retries with exponential backoff; `failed` after 5 attempts; the next run returns it to `pending` |
| Pick not in the live vocabulary, or the category deleted since | Stored, not applied |
| Video no longer public and published at apply time | The guarded write does nothing |
| More than 254 categories | Category question skipped |
| Injected instructions in a description | Worst case is one wrong value from a closed list, visible and correctable in Studio. Accepted risk |
| Video deleted | The row goes with it (`ON DELETE CASCADE`) |

Audit rows, closed codes only: toggle changed, key set or cleared, run started,
run stopped. `audit_log` metadata rejects prose, and no model output is written
to it. Per-video fills are recorded in `video_metadata_judgments`, not in the
audit log. No creator notification is sent: a backfill would send hundreds.

## 8. Privacy statement (the text the operator sees)

> Sends the title, description, channel name and tags of **public** videos to
> TypeSafe, a third-party service hosted in the United States, to choose a
> category and language for videos that have none. Private and unlisted videos,
> drafts, comments and messages are never sent. TypeSafe states it does not train
> on this data. Off by default.

The operator is the party deciding to send this data and is responsible for
reflecting it in the instance's own privacy notice; the runbook says so.

## 9. Surfaces

**Admin (U).** No new page.
- One `META` entry in `lib/admin-config-ia.ts`: `metadata_autofill_enabled`, a
  toggle on the VOD config page beside transcription, with the section 8 text as
  help and the existing `warn` mechanism when the infrastructure snapshot reports
  the feature enabled but not configured.
- One `metadata_autofill` row on the infrastructure page (Off / Active / Needs
  setup) with its `FEATURE_CONFIG_PAGE` deep link.
- One status card modelled on `MailTestCard`: counts (waiting, filled, not
  confident, failed), **Test connection**, and **Fill existing videos (N)** with
  Stop.
- The key field uses the `SecretInput` primitive from the admin mail-settings
  work. It is the last PR of this slice and depends on that work's core secret
  store being on `main`. Until then the key comes from the environment.

**Studio (U).** The shared `TaxonomySelect` takes an optional `autoFilled` flag
and renders a quiet note: "Set automatically · change it if it's wrong". No engine
name and no confidence number, following the safety-scan copy precedent. The flag
lives in the shared component so the upload and edit forms are never patched
separately.

## 10. Contract and configuration

- Video view, owner and staff only: `auto_filled: ["category", "language"]`.
- `GET /admin/metadata-fill/status` — enabled, configured, counts, last error
  code, active run.
- `POST /admin/metadata-fill/test` — one fixed, harmless judgment; reports ok,
  key rejected, or unreachable.
- `POST /admin/metadata-fill/runs` (409 when one is running) and
  `DELETE /admin/metadata-fill/runs/current`.
- One instance setting, `metadata_autofill_enabled`, default false (the
  settings-count assertion moves from 118 to 119). The sealed key setting is added
  with the key-field PR.
- Environment: `TYPESAFE_API_KEY`, `TYPESAFE_ENDPOINT`, `TYPESAFE_MODEL`,
  `METADATA_AUTOFILL_ENABLED`. Each gets a compose consumer in this repo as a plain
  `${VAR:-}` pass-through — a compose fallback value would shadow the Go default —
  and an entry in `env/production.env.example`.

## 11. Testing

- **Client:** an `httptest` stand-in for `/v1/systemone` — success, 401, 429, 5xx,
  timeout, oversized body, malformed body, a pick outside the option set, breaker
  open and half-open.
- **Worker:** both sides of each bar; never overwrites; vocabulary changed between
  judge and apply; video no longer public at apply; attempts and backoff;
  `enabled_since` set and cleared; run lifts the cutoff; stop is honoured; more
  than 254 categories. An integration-tagged Postgres test proves two concurrent
  claimers take disjoint sets.
- **Video service:** `ApplyInferredMetadata` fires the `onUpdate` hooks; a human
  edit clears `*_applied`, including a re-selection of the same value.
- **HTTP:** admin-only authorisation, 409 on a second run, audit rows, the
  settings count, and the OpenAPI contract test in both directions.
- **Frontend:** unit tests for the marker and each card state; a mocked e2e spec;
  and a backed spec in the optional workflow that runs against a **stub Jev
  server** and proves publish → filled → Studio marker → category filter finds the
  video. No real key in CI. A mocked-green suite alone is not accepted as evidence
  that the feature works.
- **Real service:** one manual run on the beta instance with the real key,
  recorded in `docs/` with the evaluation.

## 12. PR sequence

Each PR is small and merged before the next; core goes first because the contract
flows from core to user. All work happens in dedicated worktrees.

1. C — `internal/judgment` client, environment config, denylist entry.
2. C — migration, `internal/metadatafill`, `ApplyInferredMetadata`, the human-edit
   clear, the toggle, the infrastructure row, wiring.
3. C — admin endpoints, `metadata_fill_runs` with its `job_runs` projection,
   OpenAPI, `auto_filled`, audit actions.
4. C — the evaluate subcommand.
5. M — compose consumers, env example, runbook.
6. U — codegen, the toggle and its warning, the infrastructure row, the status
   card.
7. U — the Studio marker; mocked and backed e2e.
8. C + U — the sealed key setting and the `SecretInput` field (after the admin
   mail-settings secret store lands).
9. M — the beta evaluation record, a bars change in core if the numbers call for
   one, and a note in the release-readiness scope ledger.

The feature is off by default, so a release containing it is safe to deploy.

## 13. Later slices (each gets its own design)

- **Abuse-report triage** — a suggested category and severity on `reports`, plus a
  sort. The queue is newest-first with no structure today. This is the scope
  ledger's SCP-10 "AI moderation". It must run off the request path and must
  never read the plaintext snapshot stored on message-type reports.
- **Watched-word precision** — the matcher is a bare `strpos`, so a watched word
  also matches inside unrelated words. A yes/no judgment on each match feeds the
  existing resolve/dismiss queue. Part of SCP-09.
- **Related-videos topic label** — the co-visitation rail is empty on small
  instances by privacy design and the fallback is exact tag overlap. Needs an
  offline measurement first, and two vidra-search fixes before any ranker work:
  a feature-version guard on trained models, and the creator-repetition penalty
  missing from shadow evaluation.

## 14. Risks and open items

- **Accuracy on vidra content is unmeasured.** Section 6 is the gate; until it has
  run, the bars are guesses.
- **Non-English instances** may need different bars than constants allow. Stored
  raw judgments make a later move to settings cheap.
- **Dependency on in-flight work.** PR 8 waits on the admin mail-settings secret
  store. PRs 1–7 do not.
- **An edited old video becomes eligible** under the `updated_at` rule. This is
  stated to the operator rather than hidden; a `published_at` column would make
  the rule exact and is out of scope here.
