# The Vidra Product & Engineering Council

Twelve project subagents, checked into this repo, that review Vidra across its
four repositories from genuinely different seats. Launch from the meta repo
root — this is where `vidra-core`, `vidra-user` and `vidra-search` are
deliberately tied together.

## Launch

```
/council <scope>
```

e.g. `/council search: do search, autosuggest, home recommendations, related
videos, search history and admin search settings add up to a complete
consumer/admin product, or only a complete backend?`

The chair picks **3–5** teammates — never all twelve. Beyond five, coordination
overhead eats the benefit.

## Roster

| Agent | Seat | Primary question |
|---|---|---|
| `vidra-architect` | principal architect | Does this make sense across core/user/search? |
| `vidra-core` | backend/API engineer | Is the domain model, API and data behaviour correct? |
| `vidra-user` | frontend engineer | Can users actually use what core implements? |
| `vidra-search` | search/relevance engineer | Is discovery useful, private, resilient, measurable? |
| `vidra-ops-security` | self-hosting SRE / security | Can an operator safely deploy and run this? |
| `vidra-qa-release` | QA / release lead | Does it work end to end, including failure paths? |
| `vidra-product-completeness` | principal PM | Is this a complete product feature, or just code that exists? |
| `vidra-viewer` | consumer advocate | Would a normal viewer understand, want and use this? |
| `vidra-creator` | creator advocate | Can a publisher actually finish the job? |
| `vidra-instance-admin` | admin/moderator advocate | Can the owner configure, moderate, diagnose, recover? |
| `vidra-business` | product strategy | Does this earn its complexity in adoption and value? |
| `vidra-devils-advocate` | adversarial reviewer | What are we fooling ourselves about? |

## Shared contracts (every teammate reads these first)

- `.claude/council/repo-map.md` — the four repos, the boundaries, the
  verification gates, and the traps that have burned this project.
- `.claude/council/finding-format.md` — the one finding schema everybody uses,
  so a backend engineer and a strategist argue about the same object.
- `.claude/council/protocol.md` — Rounds A (blind) → B (cross-examination) →
  C (rebuttal) → D (chair's ruling).

Each component's `AGENTS.md` is binding on any teammate touching that repo.

## Design decisions worth knowing

- **All twelve are read-only** (`Read, Grep, Glob, Bash`; business also has
  web search). The council reviews; it does not edit. Implementation is
  assigned afterwards, one repo to one implementer.
- **All twelve run on Opus.** The chair is the architect seat of the
  orchestration — run the chair session under Fable if you want architect-grade
  refereeing, with `/effort` matched to how hard the scope actually is; the
  teammates do research and review, which is Opus work.
- **Ops-security and instance-admin are deliberately separate.** Ops asks "can
  the machine run?"; admin asks "can I run my community?"
- **Viewer and creator are deliberately separate.** They want opposite things
  (simplicity vs control) and that tension should surface, not be averaged away.
- The most valuable seat is usually `vidra-product-completeness`, whose mantra
  is: *"Implemented in Go" is not the same thing as "Vidra has this feature."*
