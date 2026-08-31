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
| B — cross-examination | `medium` | A bounded response to text you have been handed, in a fixed four-part shape. |
| C — rebuttal | `medium` | Same — a bounded response to a named challenge. |
| D — ruling | `high` | Where ambiguous judgement concentrates. |

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

## Round B — cross-examination

You now receive the other teammates' Round A output. You MUST produce all four:

1. **CHALLENGE** — attack at least one substantive recommendation from another
   teammate. Name the teammate, the finding, and the evidence that undermines it.
2. **OVER-ENGINEERED** — name exactly one proposal (yours included, if honest)
   that costs more than the failure it prevents.
3. **MISSED** — one risk or requirement, inside your expertise, that everyone
   else overlooked.
4. **DEFENCE** — answer every challenge aimed at you, with evidence.

Do not soften a challenge to keep the peace. Consensus is not the goal;
arguments that survive scrutiny are the goal.

## Round C — rebuttal and revision

Teammates may move. State explicitly:

```
RETRACTED: <finding> — <who disproved it and how>
REVISED:   <finding> — <old position> → <new position> — <what changed it>
HELD:      <finding> — <the challenge> — <why it does not land>
```

Changing your mind under good evidence is a **successful outcome** and is
scored as such. Holding a position you cannot defend is the failure.

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
