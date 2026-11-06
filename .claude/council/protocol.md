# Council protocol — how the rounds run

The chair (the main session) runs the rounds. Teammates obey their round.

## Round 0 — shared evidence pass (chair, before any teammate is dispatched)

Teammates each running their own repo-wide `grep` sweeps is the largest single
cost in a council run, and it is also a *quality* problem: five specialists
each grep up a slightly different picture and then argue about different
objects.

Before Round A the chair builds one **evidence pack** for the scope — a cheap
retrieval pass (the `Explore` agent, or a Haiku/Sonnet subagent) enumerating
the relevant files, endpoints, contract entries, migrations, UI routes and
admin surfaces. Every teammate reads the pack, and greps only to chase
something the pack missed — saying so when they do.

Retrieval is not judgement. Never pay a reviewer's rate for enumeration.

## Effort per round (the chair sets this)

Reasoning effort is a finer-grained cost lever than swapping models, and it is
the lever this council uses: all fourteen teammates stay on Opus, and the saving
comes from not running every round at maximum.

| Round | Effort | Why |
|---|---|---|
| 0 — evidence | `low` / `medium` | Enumeration, not judgement. |
| A — blind review | `high` | Open-ended investigation — the round that earns the money. `xhigh` only for a genuinely novel scope. |
| B+C — cross-examination and rebuttal | `medium` | One bounded response to a dispute brief, in a fixed shape; disputing teammates only. |
| D — ruling | `high` | Where ambiguous judgement concentrates. |
| E — verification | `high` | Falsify completion against code and execution evidence. |

Leaving every round at `xhigh` is the default failure. Match effort to the
difficulty of the round, not to the importance of the scope.

**Mechanical limit (audited 2026-08-31).** `effort` is a field on an agent's own
definition file — there is *no* per-invocation override, so the chair cannot
dial a teammate's effort up or down between rounds. Every seat therefore pins
`effort: high` in its frontmatter, sized for Round A, which is where a reviewer
spends nearly all of its budget; Rounds B and C simply run at that same level.
The table above is real guidance for **the chair's own passes** (Round 0
retrieval, Round D adjudication) and for choosing whether a scope justifies
editing a seat up to `xhigh` — it is not something that can be applied to a
running teammate. Before this audit no agent set `effort` at all, and every
teammate silently inherited the main session's level.

## Round A — blind review

Each teammate investigates **independently**, without seeing any other
teammate's conclusions. Evidence from the repositories, not assumptions.

Output, in the shared finding format, grouped as:

```
BLOCKERS
REQUIRED
SHOULD
EXPERIMENT
NOT WORTH DOING   ← things in scope you deliberately decline to recommend, with why
```

The `NOT WORTH DOING` section is mandatory and is not a throwaway. A review
that recommends everything it noticed has done no prioritisation.

Close Round A with a **Position summary**: at most five lines stating what you
believe and what would change your mind.

## Round B+C — cross-examination and rebuttal (one turn)

Runs only when Round A produced a disputed BLOCKER or REQUIRED item, and only
for the teammates party to a dispute. The chair sends them a dispute brief: the
disputed findings in full and a one-line index of the other teammates'
BLOCKER/REQUIRED titles, never SHOULD, EXPERIMENT or NOT WORTH DOING items. You
MUST produce all four:

1. **CHALLENGE** — attack at least one substantive recommendation from another
   teammate. Name the teammate, the finding, and the evidence that undermines it.
2. **OVER-ENGINEERED** — name exactly one proposal (yours included, if honest)
   that costs more than the failure it prevents.
3. **MISSED** — one risk or requirement, inside your expertise, that everyone
   else overlooked.
4. **DEFENCE** — answer every challenge aimed at you, with evidence.

Do not soften a challenge to keep the peace. Consensus is not the goal;
arguments that survive scrutiny are the goal.

Then, in the same answer, state explicitly:

```
RETRACTED: <finding> — <who disproved it and how>
REVISED:   <finding> — <old position> → <new position> — <what changed it>
HELD:      <finding> — <the challenge> — <why it does not land>
```

Changing your mind under good evidence is a **successful outcome** and is
scored as such. Holding a position you cannot defend is the failure. A second
exchange runs only when an answer raises a new disputed BLOCKER.

## Round D — ruling (chair only)

The chair does NOT majority-vote. For every disputed item:

```
DECISION:            ACCEPT | MODIFY | EXPERIMENT | DEFER | REJECT | BLOCK RELEASE
WHY:
DISSENTING VIEW:     (name the teammate; never delete a losing argument)
AFFECTED REPOS:
USER IMPACT:
OPERATOR IMPACT:
BUSINESS VALUE:
TECHNICAL COST/RISK:
ACCEPTANCE CRITERIA:
TEST PLAN:
```

Then one prioritised backlog:

```
P0 — release blockers
P1 — required for coherent product behaviour
P2 — high-value improvements
P3 — experiments and future opportunities
DECLINED — considered and rejected, with the reason
```

## Round E — post-implementation verification (`/council --verify <scope>`)

Run after implementation PRs are opened or merged, and again after material
follow-up changes. The chair records scope, acceptance criteria, checkout paths,
commit SHAs, dependency PRs and actual test/CI evidence in a shared evidence pack.
Refresh `origin/main` before checking merge state. Open PRs cannot receive a complete verdict while a required dependency is unmerged.

Dispatch exactly three independent, read-only seats with that evidence pack:

- **`vidra-product-completeness`**: walk every applicable row of the slice table
  in `.claude/agents/product/vidra-product-completeness.md` against all affected
  repos. The current table has 20 rows (the older proposal called it 17); do
  not omit accessibility, mobile, tests or degraded-dependency behaviour.
  Prove typed `endpoints.ts` callers, mounted components and reachable navigation
  for user/admin endpoints; loading (`Spinner`), empty (`EmptyState`), error
  (`ErrorState`) and disabled reasons; `useT()` keys in both `en` and `fr`.
  Configurable admin controls belong in `internal/instancesettings` or sealed
  settings tables such as `mail_config`/`oidc_providers`; justify any exception.
- **`vidra-qa-release`**: audit core unit/tagged-integration results and audit
  assertions (`findAudit`), frontend component and applicable `e2e/` plus
  `e2e-backed/` proof of real DB mutation and fresh refetch, and meta recovery
  classification plus rollback compatibility guards. Check search tests when
  affected. Name unrun, missing, skipped or stale proof explicitly.
- **`vidra-devils-advocate`**: try to falsify completion using silent skips,
  components imported only by tests, ignored response fields, unhandled error
  codes, stale docs and unavailable-dependency paths. Confirm reachability
  from a route, rather than assuming an exported component is mounted.

Each seat returns row-by-row `PASS | FAIL | NOT_APPLICABLE`, a `file:line`
citation and execution artifact where relevant, plus an exact punch-list.
`NOT_APPLICABLE` requires a scope-specific reason; a missing test or service is
`FAIL`, not an exemption. Static citations cannot replace runtime proof; share disputed findings for rebuttal.

Before the ruling, run from the meta checkout and retain actual output:

```sh
.claude/council/quiet.sh slice-gate python3 scripts/ci/check-vertical-slice-completeness.py
```

For release qualification add `--strict-migrations`, verify pinned-release CI,
release preflight, real upgrade/rollback/replacement-host restore, migration,
install-stopwatch and digest vulnerability evidence in `docs/release-readiness.md`
(~1.5 MB: `grep -n` the release or check, never read it whole).
A green source-branch check alone does not qualify a released image.

Return one verdict with the evidence matrix and punch-list:

```text
VERDICT: 100% COMPLETE
# or
VERDICT: INCOMPLETE — SEND BACK TO WAR ROOM LOOP
```

Complete requires every applicable row, all affected PRs merged to their own
`main`, their required CI green, and the mechanical gate passing. Label lifecycle
state separately: implemented / merged / released / deployed. An incomplete
verdict keeps the slice `IN_PROGRESS` and `EXIT_SIGNAL: false`; route each item
back to its owning repository. Never manufacture test output or mark a planned
drill executed. Verification review itself does not change application code.

## The chair seat

The chair runs the rounds *and* rules. Those are different jobs: dispatching
teammates and shuttling Round A output between them is plumbing, while Round D
adjudication — deciding between specialists who genuinely disagree — is the
ambiguous judgement the whole council exists to produce.

Run the chair as an **Opus session with `/advisor fable`**, not as a Fable
session. Fable then steers panel selection and the Round D ruling — its
architect seat, roughly 5–15% of the work — while Opus runs the rounds. Making
Fable the whole chair session pays architect rates to shuffle teammate output.

**Never add "show your reasoning" / "explain your thinking" wording to this
protocol or to a teammate prompt.** It trips the reasoning-extraction
classifier and silently reroutes Fable to Opus: you pay for the advisor seat
and do not get it. (Audited 2026-08-31 — this protocol is clean. Round A's
"what would change your mind" asks for a falsification condition, which is a
substantive claim, not a reasoning echo.)

## Implementation rules (only after the owner asks for implementation)

- No code is modified during council review. Review teammates are read-only.
- When implementation is requested, assign **one repo to one implementer**.
  Parallel agents editing the same files overwrite each other.
- Fanning two agents into the same repo requires separate git worktrees.
- Each implementer obeys that repo's AGENTS.md: TDD, one small PR (<300 lines),
  the repo's verification gate pasted into the PR body, and
  finished-means-merged.
