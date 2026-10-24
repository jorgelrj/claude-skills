---
name: triage-rubric
description: TEMPO clarity rubric (Target, Outcome, Anchor, Check), task type rules (feature, known bug, user-feedback bug) and size lanes (S, M, L). Use when triaging a request or deciding which lane a task runs in.
---

# Triage rubric

## 1 Task type

1.1 FEATURE: the request asks for behaviour that does not exist yet, or a change to working behaviour.
1.2 BUG-KNOWN: the request names a symptom AND at least one of: an error message, a stack trace, reproduction steps, a file or a failing test.
1.3 BUG-FEEDBACK: the request reports a symptom from a user's point of view and names none of the items in 1.2.
1.4 IF a request is both a bug and a feature, THEN classify it as FEATURE and record the bug in Task Card §5.

## 2 Clarity check

Ask the four questions in order. Only questions 1 and 2 can send the task back to Jorge.

| # | Question | IF missing, THEN |
|---|---|---|
| 2.1 | **Target.** Which thing changes? A screen, component, endpoint or behaviour. | Ask Jorge. |
| 2.2 | **Outcome.** What is true afterwards? | Ask Jorge. |
| 2.3 | **Anchor.** Where to start looking: a screen name, an error, a file. | Mark `EXPLORE WILL FIND`. Do not ask. |
| 2.4 | **Check.** How we know it worked. | Mark `ARCHITECT WILL DRAFT`. The criteria are confirmed in the Spec. |

2.5 A bug report's Outcome is "the symptom no longer happens". IF the symptom is stated, THEN Outcome is PRESENT.
2.6 Before asking, run a quick scan (Grep and Glob, 5 searches or fewer) so each question offers choices found in the code.
2.7 Ask 1 to 3 questions. Each question SHALL list options and one recommended option.
2.8 IF triage can pick a reading with high confidence, THEN record it in §5 ASSUMPTIONS and do not ask.

### Examples

- "Make the button red". Target missing. Scan finds 14 buttons. Ask: "Did you mean (a) the Save button on Settings, (b) the primary button style everywhere, or (c) something else? Recommended: (b)."
- "The users can't view their messages". Target (messages view) and Outcome (users see their messages) are present. Anchor is the messages screen. Type BUG-FEEDBACK. Do not ask.

## 3 Size and lane

| Size | Rule (all conditions) | Lane |
|---|---|---|
| S | 1 to 2 files; no new design; no data or schema change; no new dependency. | Work Order, Build, quick review (correctness lens only), PR. |
| M | 3 to 8 files in one area; goal is clear; no schema change on real data. | Explore, light spec, Build, standard review (all lenses), QA, PR. Spec gate only if the spec lists open decisions. |
| L | More than 8 files, OR a new design, OR a data or schema change, OR a new dependency, OR work across more than one area. | Full spec, Jorge approves spec, parallel builders, deep review, QA, PR. |

3.1 IF unsure between two sizes, THEN pick the larger one.
3.2 The bug flow uses the same sizes. A bug is S when the root cause is likely in one file. The Reproduce step is never skipped, in any size.
3.3 Review depth follows the lane: S = QUICK, M = STANDARD, L = DEEP.

## 4 Routes

| Type | Route |
|---|---|
| FEATURE, S | Handoff (one Work Order from the Task Card), Build, Integrate, Review (QUICK), QA, Ship |
| FEATURE, M or L | Explore, Spec, [Spec gate], Handoff, Build, Integrate, Review, QA, Ship |
| BUG-KNOWN | Reproduce, Root cause, [Behaviour gate], Handoff (one Work Order), Build, Integrate, Review + sibling sweep, QA, Ship |
| BUG-FEEDBACK | Investigate, Reproduce, Root cause, [Behaviour gate], Handoff, Build, Integrate, Review + sibling sweep, QA, Ship |
| WORKSPACE (request spans repos) | Explore (one CROSS-REPO scout per repo), Plan, Plan gate, one child task per repo in plan order, Joint QA, Ship |

4.1 Plan-only mode (`/tempo:plan`) runs a route up to and including Handoff (single repo) or the Plan gate (workspace), then stops. The bug route keeps Reproduce and Root cause in plan-only mode: they commit only a test, on the repro branch.

## 5 Dependency types

| Type | Meaning | Example |
|---|---|---|
| blocks-start | the target cannot compile or run its tests without the source's change | a DTO field in a shared library the service reads |
| blocks-merge | the target can be built now against the agreed contract; its PR merges after the source's | an endpoint the client calls, with the request shape agreed in the plan |
| blocks-validation | both can be built and merged; only the joint check waits for both | an external system's deploy |

5.1 Only blocks-start orders the work. A wrong blocks-start costs days of waiting, so when unsure, pick blocks-merge and record the contract.
5.2 Work owned by another team is an EXTERNAL BLOCKER, never a reason to wait for a start when a stub or a contract lets the slice be built.
