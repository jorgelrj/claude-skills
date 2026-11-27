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
| 2.4 | **Check.** How we know it worked, and where a person sees it: the endpoint, the screen or the app. | Mark `ARCHITECT WILL DRAFT`. The criteria and their Live lines are confirmed in the Spec. |

2.5 A bug report's Outcome is "the symptom no longer happens". IF the symptom is stated, THEN Outcome is PRESENT.
2.6 Before asking, run a quick scan (Grep and Glob, 5 searches or fewer) so each question offers choices found in the code.
2.7 Ask 1 to 3 questions. Each question SHALL list options and one recommended option.
2.8 IF triage can pick a reading with high confidence, THEN record it in §5 ASSUMPTIONS and do not ask.
2.9 Sources. IF the request or ticket says the work follows another source (a linked ticket, its attachments, a design file or a named version of it, a doc, an asset) and that source is MISSING, THEN the Outcome is not PRESENT for the items that depend on it: ask Jorge (NEEDS-JORGE MISSING-SOURCE), even on autopilot. 2.8 does not apply: no reading of a source you cannot open is high confidence.
2.10 Done-when steps. List each step of the request's Done-when (or of the Outcome when it has none) in Task Card §4 as `DW-n`, in the request's words: every result and every action, outside ones too (a comment posted on an issue, an issue closed, a message sent). An assumption SHALL NOT drop, shrink or reassign a step: "the output is a file for Jorge to post" turns "posted on #92" into a different task.
2.10.1 Before you decide a step cannot be done, check the tool read-only (`gh auth status`, `gh issue view <n>`). `gh` works in the sandbox. IF the check passes, THEN the step stays and the task does it.
2.10.2 IF a step still cannot be done in the run, THEN the Outcome is not PRESENT: ask Jorge, ending `NEEDS-JORGE`, with the options (a) Jorge gives the access (b) Jorge changes the Done-when (c) drop the step. 2.8 does not apply. Only Jorge's answer changes a step.

### Examples

- "Make the button red". Target missing. Scan finds 14 buttons. Ask: "Did you mean (a) the Save button on Settings, (b) the primary button style everywhere, or (c) something else? Recommended: (b)."
- "Done when a table per card is posted on #92". DW-1 is the posted comment, not a Markdown file in the task folder. `gh issue view 92` works, so do not ask.
- "The users can't view their messages". Target (messages view) and Outcome (users see their messages) are present. Anchor is the messages screen. Type BUG-FEEDBACK. Do not ask.

## 3 Size and lane

Count production files only. Test files, fixtures, docs, locale resources (`*.arb`, `i18n/*.json`, slang JSON) and generated files (`*.g.dart`, `*.freezed.dart`, `generated/` folders) do not count toward the size.

| Size | Rule (all conditions) | Lane |
|---|---|---|
| S | 1 to 3 production files; no new design; no schema change on real data; no new dependency. | Work Order from the Task Card, Build, quick review (correctness lens only), QA, PR. |
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
3.8 Time estimate. Record in §3.3 the expected wall-clock time of the chosen lane: S about 15 minutes, M about 25 minutes, L 60 minutes or more. Add 10 minutes per review fix round.
3.9 Pattern task. An M feature that copies a sibling feature already in the code, with no schema, design or dependency change, is a pattern task. The orchestrator sets it after Explore, from the scouts' `SIBLING:` line. It skips the order check, reviews at QUICK depth, and QA checks each criterion at its 3.11 depth, as for any task. It keeps M's spec, because the spec is what says which sibling to copy.
3.10 Critical. Triage decides it, from the project's critical rules: a change is critical when the request or ticket says so, or it touches authentication, money, data migration or a toolchain pin, or the standing decisions or the repo's ADRs and docs define it as critical. Record YES or NO with the reason in the Task Card §3. A critical change runs FULL bars and critical targets; under `gates.full_bars: verify` the full suites stay deferred to `/tempo:verify`. A later stage that thinks a NO task is critical asks Jorge, naming the whole suites it would run, and never turns it on itself.
3.11 QA depth, per criterion. The architect infers it from what the criterion changes; Jorge does not set it.
3.11.1 LIVE (shown in the running product) when the criterion has any of:
- a new feature, screen, flow, endpoint, job or command;
- changed logic: a rule, condition, calculation, state change, permission or sign-in, money, a data write or delete, a migration;
- a layout change or a new screen state (empty, error, loading, a menu), or a prototype flow to follow;
- a contract another repo's client now calls in a new way;
- a bug fix's AC-1 (the reported steps).
3.11.2 TEST (a named test is enough, no app run) when the change is only one of these, and touches no logic:
- `cosmetic`: a colour, token, spacing, icon or copy change on an existing screen, with no layout or behaviour change. It never shows, hides, enables, disables, reorders or moves an element, and the copy does not depend on a condition. Its test asserts the value (a golden, a token or widget test); with a design frame, the value equals the design's token.
- `additive`: a field added to an existing response, model or event whose value is copied as it is from data the code already loads (no new calculation, query, condition or default rule), with existing fields and logic unchanged. A field whose value new code works out is changed logic (3.11.1). A contract, controller or e2e test asserts the field and its value.
- `refactor`: no behaviour change, and existing tests cover every path the change touches and pass unchanged. IF a touched path has no test, or a test had to change, THEN it is LIVE.
- `config`: an env variable, flag, manifest entry or build define, with its parsing and boot or readiness check, asserted by a boot or config test, where no screen, route or command in this task acts on the value yet. A flag that turns a behaviour on or off, or a value a rule, limit or calculation uses, is changed logic (3.11.1).
- `guard`: a test, contract file, guard, inventory or CI file whose only reader is the test suite or CI (a contract spec, an architecture rule, a forbidden-value detector, a lane filter); its own run is the proof. An endpoint a contract describes is still LIVE.
- `docs`, `bar` (lint, build, green bar).
3.11.2.1 Whatever 3.11.1 says, a criterion is TEST when the running product cannot be made to show it: `race` (two orders or two concurrent requests forced), `external` (an outside service's failure, or a value it sends, that cannot be caused locally), `fault` (a write made to fail, such as a rolled-back transaction). Only that part is TEST: the operation's normal path has its own LIVE criterion.
3.11.3 IF a criterion fits 3.11.1 and 3.11.2 (3.11.2.1 excepted), or the class is unsure, THEN it is LIVE. A criterion that mixes classes is split, one criterion per class: the part a person can see in the product is LIVE; a cosmetic, additive, race, external or fault part is TEST.
3.11.4 IF the Task Card Outcome adds a feature or changes logic, THEN at least one criterion is LIVE and shows that Outcome end to end; a set made only of TEST criteria is a misclassification. Otherwise, a task whose criteria are all TEST runs QA without starting the product: QA confirms each named test asserts its criterion and cites or runs it (qa 2.1).

## 4 Routes

| Type | Route |
|---|---|
| FEATURE, S | Handoff (one Work Order from the Task Card), Build, Integrate, Review (QUICK), QA, Ship |
| FEATURE, M or L | Explore, Spec, [Spec gate], Handoff, Build, Integrate, Review, QA, Ship |
| BUG-KNOWN | Reproduce, Root cause, [Behaviour gate], Handoff (one Work Order), Build, Integrate, Review + sibling sweep, QA, Ship |
| BUG-FEEDBACK | Investigate, Reproduce, Root cause, [Behaviour gate], Handoff, Build, Integrate, Review + sibling sweep, QA, Ship |
| WORKSPACE (request spans repos) | Explore (one CROSS-REPO scout per repo), Plan, Plan gate, one child task per repo (children whose dependencies allow it run in parallel), Joint QA, Ship |
| CHILD of a workspace task, slice S or M | Handoff (Work Orders from the plan slice and the parent Context Map), Build, Integrate, Review, QA, Ship |
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
