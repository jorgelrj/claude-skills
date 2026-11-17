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
2.9 Sources. IF the request or ticket says the work follows another source (a linked ticket, its attachments, a design file or a named version of it, a doc, an asset) and that source is MISSING, THEN the Outcome is not PRESENT for the items that depend on it: ask Jorge (NEEDS-JORGE MISSING-SOURCE), even on autopilot. 2.8 does not apply: no reading of a source you cannot open is high confidence.

### Examples

- "Make the button red". Target missing. Scan finds 14 buttons. Ask: "Did you mean (a) the Save button on Settings, (b) the primary button style everywhere, or (c) something else? Recommended: (b)."
- "The users can't view their messages". Target (messages view) and Outcome (users see their messages) are present. Anchor is the messages screen. Type BUG-FEEDBACK. Do not ask.

## 3 Size and lane

Count production files only. Test files, fixtures, docs, locale resources (`*.arb`, `i18n/*.json`, slang JSON) and generated files (`*.g.dart`, `*.freezed.dart`, `generated/` folders) do not count toward the size.

| Size | Rule (all conditions) | Lane |
|---|---|---|
| S | 1 to 3 production files; no new design; no schema change on real data; no new dependency. | Work Order from the Task Card, Build, quick review (correctness lens only), PR. |
| M | 4 to 8 production files in one area; goal is clear; no schema change on real data. | Explore (2 scouts), light spec, 1 or 2 Work Orders (more only when file scopes would overlap, with the reason in the spec), Build, standard review (correctness and spec lenses), QA, PR. Spec gate only if the spec lists open decisions. |
| L | More than 8 production files, OR a new screen or flow design, OR a schema change on real data, OR a new dependency. | Full spec, Jorge approves spec, parallel builders, deep review, QA, PR. |

3.1 Size on what the request changes, not on how far the code around it reaches. Adding a field that passes through existing layers is S when each layer has 3 production files or fewer to touch.
3.2 IF unsure between two sizes, THEN pick the smaller one and record the reason in §5 ASSUMPTIONS. Explore re-sizes the task (3.5), so a wrong guess costs one stage, not the whole route.
3.3 The bug flow uses the same sizes. A bug is S when the root cause is likely in one file. The Reproduce step is never skipped, in any size.
3.4 Review depth follows the lane: S = QUICK, M = STANDARD, L = DEEP.
3.5 Re-size after Explore. IF the Context Map marks 3 production files or fewer as CHANGE, with no schema, design or dependency change, THEN the lane drops to S. IF it marks more than 8, or a schema or design change, THEN it rises to L. The orchestrator records the change with `set --lane`.
3.6 Lane override. IF Jorge's request carries `--lane S|M|L` or `--quick`, THEN that lane wins over 3.1 to 3.5. `--quick` is lane S. Record the override in §3.3.
3.7 A workspace task is not sized by its repo count. Each slice is sized on its own repo's change. "Work across several repos" is never by itself a reason for L.
3.7.1 A large single-repo task is split at Handoff into stacked slices of 1 to 3 Work Orders when it passes `limits.split_orders` orders or `limits.split_criteria` criteria (orchestrator §9). Size it L as usual; do not shrink a task to avoid the split.
3.8 Time estimate. Record in §3.3 the expected wall-clock time of the chosen lane: S about 10 minutes, M about 25 minutes, L 60 minutes or more. Add 10 minutes per review fix round.
3.9 Pattern task. An M feature that copies a sibling feature already in the code, with no schema, design or dependency change, is a pattern task. The orchestrator sets it after Explore, from the scouts' `SIBLING:` line. It skips the order check, reviews at QUICK depth, and QA checks only the criteria no test covers. It keeps M's spec, because the spec is what says which sibling to copy.
3.10 Critical. Triage decides it, from the project's critical rules: a change is critical when the request or ticket says so, or it touches authentication, money, data migration or a toolchain pin, or the standing decisions or the repo's ADRs and docs define it as critical. Record YES or NO with the reason in the Task Card §3. A critical change runs FULL bars and critical targets; under `gates.full_bars: verify` the full suites stay deferred to `/tempo:verify`. A later stage that thinks a NO task is critical asks Jorge, naming the whole suites it would run, and never turns it on itself.

## 4 Routes

| Type | Route |
|---|---|
| FEATURE, S | Handoff (one Work Order from the Task Card), Build, Integrate, Review (QUICK), Ship |
| FEATURE, M or L | Explore, Spec, [Spec gate], Handoff, Build, Integrate, Review, QA, Ship |
| BUG-KNOWN | Reproduce, Root cause, [Behaviour gate], Handoff (one Work Order), Build, Integrate, Review + sibling sweep, QA, Ship |
| BUG-FEEDBACK | Investigate, Reproduce, Root cause, [Behaviour gate], Handoff, Build, Integrate, Review + sibling sweep, QA, Ship |
| WORKSPACE (request spans repos) | Explore (one CROSS-REPO scout per repo), Plan, Plan gate, one child task per repo (children whose dependencies allow it run in parallel), Joint QA, Ship |
| CHILD of a workspace task, slice S or M | Handoff (Work Orders from the plan slice and the parent Context Map), Build, Integrate, Review, [QA for M], Ship |
| CHILD of a workspace task, slice L or with an open decision | the FEATURE or BUG route for its size |
| SLICE of a split task (orchestrator §9) | Build, Integrate, Review; the parent runs one Integrate, QA and Ship after the last slice |

4.1 Plan-only mode (`/tempo:plan`) runs a route up to and including Handoff (single repo) or the Plan gate (workspace), then stops. The bug route keeps Reproduce and Root cause in plan-only mode: they commit only a test, on the repro branch.

## 5 Dependency types

| Type | Meaning | Example |
|---|---|---|
| blocks-start | the target cannot compile or run its tests without the source's change | a DTO field in a shared library the service reads |
| blocks-merge | the target can be built now against the agreed contract; its PR merges after the source's | an endpoint the client calls, with the request shape agreed in the plan |
| blocks-validation | both can be built and merged; only the joint check waits for both | an external system's deploy |

5.1 Only blocks-start orders the work. A wrong blocks-start costs days of waiting, so when unsure, pick blocks-merge and record the contract.
5.2 Work owned by another team is an EXTERNAL BLOCKER, never a reason to wait for a start when a stub or a contract lets the slice be built.
