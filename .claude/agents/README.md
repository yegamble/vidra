# The Vidra Product & Engineering Council

Fourteen project subagents, checked into this repo, that review Vidra across
its four repositories from genuinely different seats. Launch from the meta repo
root — this is where `vidra-core`, `vidra-user` and `vidra-search` are
deliberately tied together.

## Launch

```
/council <scope>
```

e.g. `/council search: do search, autosuggest, home recommendations, related
videos, search history and admin search settings add up to a complete
consumer/admin product, or only a complete backend?`

The chair picks **3–5** teammates — never all fourteen. Beyond five,
coordination overhead eats the benefit.

## Roster

| Agent | Seat | Primary question |
|---|---|---|
| `vidra-architect` | principal architect | Does this make sense across core/user/search? |
| `vidra-core` | backend/API engineer | Is the domain model, API and data behaviour correct? |
| `vidra-user` | frontend engineer | Can users actually use what core implements? |
| `vidra-search` | search/relevance engineer | Is discovery useful, private, resilient, measurable? |
| `vidra-infrastructure` | self-hosting SRE / platform | Can an operator safely deploy, run and recover this? |
| `vidra-security` | application security | What can an attacker — or a hostile instance — reach? |
| `vidra-qa-release` | QA / release lead | Does it work end to end, including failure paths? |
| `vidra-product-completeness` | principal PM | Is this a complete product feature, or just code that exists? |
| `vidra-viewer` | consumer advocate | Would a normal viewer understand, want and use this? |
| `vidra-creator` | creator advocate | Can a publisher actually finish the job? |
| `vidra-instance-admin` | admin/moderator advocate | Can the owner configure, moderate, diagnose, recover? |
| `vidra-design` | UI/UX design authority | Is this designed and measurably accessible, or just styled? |
| `vidra-business` | product strategy | Does this earn its complexity in adoption and value? |
| `vidra-devils-advocate` | adversarial reviewer | What are we fooling ourselves about? |

## Shared contracts (every teammate reads these first)

- `.claude/council/repo-map.md` — the four repos, the boundaries, the
  verification gates, and the traps that have burned this project.
- `.claude/council/finding-format.md` — the one finding schema everybody uses,
  so a backend engineer and a strategist argue about the same object.
- `.claude/council/protocol.md` — Round 0 (shared evidence) → A (blind) →
  B (cross-examination) → C (rebuttal) → D (chair's ruling), plus the effort
  budget for each round.

Each component's `AGENTS.md` is binding on any teammate touching that repo.

## Design decisions worth knowing

- **All fourteen are read-only during council rounds** (`Read, Grep, Glob,
  Bash`; business, security and design also have web search). The council
  reviews; it does not edit. Implementation is assigned afterwards, one repo to
  one implementer.
  - **`vidra-design` is the one seat that also carries `Edit`/`Write`**, for
    *direct* invocation outside a council run. Its prompt makes the mode split
    explicit and defaults to read-only when ambiguous. It is also the only seat
    allowed to run browser tooling — the *mocked* `npm run design:shots` and
    `e2e/a11y.spec.ts` — because its evidence is inherently visual and a design
    claim without a light/dark × mobile/desktop capture is worthless.
- **All fourteen run on Opus**, deliberately. Tiering the rubric-driven seats
  down to Sonnet was considered and declined: the teammates are not only
  *subject* to cross-examination, they are the ones *performing* it, and a
  weaker challenger weakens the mechanism the council is built on. Cost is
  controlled by **effort** and the **Round 0 evidence pass** instead — both in
  `.claude/council/protocol.md`.
- **Every agent pins `effort: high` in its own frontmatter.** This was a gap
  until 2026-08-31: `protocol.md` treated effort as the council's main cost
  lever, but no agent set it, so every teammate silently inherited whatever the
  main session happened to be running at. `effort` is a per-agent-definition
  field only — there is no per-invocation override — so **the per-round effort
  table in `protocol.md` is guidance for the chair's own passes, not something
  that can be applied to a teammate mid-run**. Escalating a seat to `xhigh`
  means editing that seat's file, deliberately, for a genuinely novel scope.
  Retrieval stays cheap the other way: Round 0 uses `Explore`/Haiku, and
  reviewers are never paid to enumerate.
- **The chair is an Opus session running `/advisor fable`** — not a Fable
  session. Round D adjudication is Fable's architect seat (~5–15% of the work);
  running the rounds is plumbing that should not cost architect rates. Never
  introduce "show/explain your reasoning" wording into the protocol or a
  teammate prompt: it silently reroutes Fable to Opus.
- **Infrastructure, security and instance-admin are three separate seats.**
  Infrastructure asks "can the machine run and recover?"; security asks "what
  can an attacker reach?"; admin asks "can I run my community?" The first two
  were one `vidra-ops-security` seat until 2026-08-31 — in practice the
  operator checklist crowded out the attacker's view, and federation (where
  every input arrives from a machine you do not control) deserves a reviewer
  whose whole job it is.
- **Design is a product seat, not a technical one.** It sits beside viewer and
  creator because its authority is over *whether a person can use this*, and it
  is bound by `vidra-user/.ralph/specs/design-system.md` — where its taste and
  the spec disagree, the spec wins and the disagreement becomes a finding.
- **Viewer and creator are deliberately separate.** They want opposite things
  (simplicity vs control) and that tension should surface, not be averaged away.
- The most valuable seat is usually `vidra-product-completeness`, whose mantra
  is: *"Implemented in Go" is not the same thing as "Vidra has this feature."*
