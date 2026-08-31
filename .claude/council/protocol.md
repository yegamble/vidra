# Council protocol — how the rounds run

The chair (the main session) runs the rounds. Teammates obey their round.

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

## Implementation rules (only after the owner asks for implementation)

- No code is modified during council review. Review teammates are read-only.
- When implementation is requested, assign **one repo to one implementer**.
  Parallel agents editing the same files overwrite each other.
- Fanning two agents into the same repo requires separate git worktrees.
- Each implementer obeys that repo's AGENTS.md: TDD, one small PR (<300 lines),
  the repo's verification gate pasted into the PR body, and
  finished-means-merged.
