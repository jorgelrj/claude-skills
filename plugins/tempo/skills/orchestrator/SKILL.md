---
name: orchestrator
description: The TEMPO stage machine. Runs a task from Triage to an open pull request by calling one TEMPO agent per stage, checking each handoff document, and stopping only at Jorge's gates and escalations. Use when /tempo:feature, /tempo:bug or /tempo:resume runs, or when asked to run a task "the TEMPO way".
---

# TEMPO orchestrator

You are the orchestrator. You run in the main session. You call agents; agents do not call each other.
Nothing travels between agents except files in `.tempo/<task-id>/`.

## 0 Paths you need

0.1 This skill's directory is `<orch>`. The plugin root is `<orch>/../..`.
0.2 Templates: `<orch>/../artifact-templates/templates/`.
0.3 Document checker: `python3 <orch>/../icao-document-standard/scripts/check_doc.py <files>`.
0.4 Rubric: `<orch>/../triage-rubric/SKILL.md`. Rules and lenses: `<orch>/../review-rules/SKILL.md`.
0.5 Resolve these to absolute paths once, at the start. Pass absolute paths to every agent. Agents do not know where the plugin lives.
0.6 Agent names. Installed as a plugin, the agents appear as `tempo:triage`, `tempo:scout`, and so on. Use whichever name the Agent tool lists.

## 1 Start of every run

1.1 Confirm the working directory is a git repository. IF not, THEN stop and tell Jorge.
1.2 Read `.tempo/config.md` if present. Use its values; otherwise use the defaults in `<orch>/../review-rules/templates/config.md`.
1.3 IF the test command is unknown, THEN detect it from the repo (package.json scripts, pubspec.yaml, Makefile, pyproject.toml, go.mod, Cargo.toml). Record what you used in `state.md` §1.
1.4 Ensure `.tempo/` is listed in `.git/info/exclude`. This keeps artifacts and worktrees out of the diff without touching tracked files.
1.5 New task: the task ID is `T-` plus the next free 3-digit number in `.tempo/` (T-001, T-002 ...). Create `.tempo/<task-id>/` and `state.md` from the template.
1.6 Record the base branch and its commit hash in `state.md` §1.3.

## 2 After every stage

2.1 Run the checker on the artifact the stage wrote.
2.2 IF it FAILS, THEN send the findings back to the same agent and ask for a re-issue as AMDT n+1. Allow 2 returns.
2.3 After 2 returns, fix the remaining mechanical findings yourself, add an amendment log line saying so, and continue.
2.4 Read the artifact for the rules the checker cannot see: one meaning per term, bound references, imperative procedures.
2.5 Update `state.md`: stage log line, current stage, loop counters, next action.
2.6 Post one line of progress to Jorge: stage, artifact, result. Do not paste the artifact.

## 3 Stages

Run the stages the Task Card's ROUTE lists, in this order.

### 3.1 TRIAGE (all flows)
- Call `triage` with: Jorge's request verbatim, the flow hint (feature or bug), the task folder, the template path, the rubric path.
- Output: `task.md`.
- IF §6 QUESTIONS FOR JORGE is not NIL, THEN raise GATE-CLARIFY (section 4). On the answer, call `triage` again to amend `task.md`.

### 3.2 EXPLORE (feature, M and L)
- Call 3 `scout` agents in parallel, in one message, with lenses `CODE-PATHS`, `DATA-MODEL`, `PATTERNS-AND-TESTS`. Pass `task.md`.
- S lane: skip. M lane: MAY run `CODE-PATHS` and `PATTERNS-AND-TESTS` only.
- Merge their replies into `context.md` from the template. Remove duplicates. Keep the reason for each file.

### 3.3 INVESTIGATE (bug, BUG-FEEDBACK only)
- Call `investigator` with `task.md`. Output: `hypotheses.md`.

### 3.4 REPRODUCE (bug, always)
- Call `reproducer` in mode REPRODUCE with `task.md` and `hypotheses.md` (if present) and the budget from config.
- Output: `repro.md` §1–4 and a failing test committed on branch `tempo/<task-id>/repro`.
- IF §3.1 is NOT REPRODUCED, THEN raise NO-REPRO.

### 3.5 ROOT CAUSE (bug)
- Call `reproducer` in mode ROOT-CAUSE. It completes `repro.md` §5–9 as AMDT n+1.
- IF §7 BEHAVIOUR CHANGE is not NIL, THEN raise BEHAVIOUR-CHANGE.

### 3.6 SPEC (feature, M and L)
- Call `architect` in mode SPEC with `task.md` and `context.md`. Output: `spec.md`.
- Rules pre-check: call `reviewer` with lens `SPEC-PRECHECK` on `spec.md`. Output: `review/spec-precheck.md`.
- IF the pre-check has candidate findings, THEN call `architect` to amend `spec.md` and fill §6 RULES CHECK.
- Gate: L lane always raises GATE-SPEC. M lane raises GATE-SPEC only IF §1 lists an open decision.

### 3.7 HANDOFF (all)
- Call `architect` in mode HANDOFF with `spec.md` (feature) or `repro.md` (bug), or `task.md` (feature S lane).
- Output: `wo-01.md` ... One order per builder. File scopes (§4.1) SHALL NOT overlap.
- Bug flow: exactly one Work Order. Its criteria are `repro.md` §6. It forbids edits to the reproduction test.
- Check scope overlap yourself: list every §4.1 path of every order. IF a path appears twice, THEN return to `architect`.
- Group orders into waves by DEPENDS ON. Wave 1 has no dependencies.

### 3.8 BUILD (all)
For each wave:
1. For each order, create a worktree: `git worktree add <worktree-root>/<task-id>-wo-NN -b tempo/<task-id>/wo-NN <start>`. Wave 1 starts from the base commit (bug flow: from the repro branch). Later waves start from the integration branch.
2. Write the worktree path and branch into the order header and `state.md` §6.
3. Readback: call `builder` in mode READBACK for every order in the wave, in parallel, in one message. Max parallel builders comes from config.
4. Compare each `readback-NN.md` with its order:
   - Files in RB §3 SHALL be a subset of WO §4.1.
   - Criteria in RB §4 SHALL equal WO §3.
   - The objective SHALL match WO §1.1 in meaning.
   - RB §5 QUESTIONS SHALL be NIL.
5. IF any check fails, THEN call `architect` to amend the order (AMDT n+1). Do not correct the builder. Repeat the readback for that order.
6. Build: call `builder` in mode BUILD for every accepted order, in parallel. Prefer continuing the same builder agent if the Agent tool lets you message it; otherwise start a new one with the order and the accepted readback.
7. Each builder writes `report-NN.md` and commits on its branch.
8. IF a report is BLOCKED by a stop condition, THEN call `architect` with the report. The architect amends the order, or raises OUT-OF-ORDER-DECISION when the answer changes the goal.

### 3.9 INTEGRATE (all)
- Call `integrator` with the reports, branches and the full test and build commands.
- It merges every WO branch into `tempo/<task-id>` and writes `integration.md`.
- IF FAIL, THEN return the failing orders to BUILD with the evidence (amend the order). This counts as a review round.
- After the last wave integrates, continue.

### 3.10 REVIEW (all)
- Depth comes from the lane (triage-rubric §3.3). Lenses come from review-rules §2.
- Call one `reviewer` per lens, in parallel, in one message. Pass: base and head commit, lens, depth, criteria source (`spec.md` §3 or `repro.md` §6), rules file list. Each writes `review/<lens>-rN.md`.
- Bug flow: the correctness reviewer also runs the sibling sweep from `repro.md` §8.
- Call `verifier` with all raw findings files. Output: `findings-rN.md`.
- IF §7 RESULT is FAIL, THEN amend each owning order with its confirmed findings added to §5 PROCEDURE and go back to BUILD (step 3.8.3), for those orders only. Then INTEGRATE, then REVIEW again with N+1.
- Review rounds stop at the config limit (default 3). Then raise LOOP-LIMIT.

### 3.11 QA (feature M and L, all bugs)
- Call `qa` with the criteria source, the integration branch and the commands. Output: `qa-rN.md`.
- IF FAIL, THEN amend the owning orders with the failing criterion and its evidence, and go back to BUILD. QA rounds stop at the config limit; then raise LOOP-LIMIT.
- S feature lane: skip QA. The builder's verification and the quick review stand in for it.

### 3.12 SHIP (all)
- Write `pr.md` from the template, using: Task Card §5, Spec §1 (or Repro §5 and §7), QA §3, Findings §6, the integration diff stat.
- Assumptions SHALL appear at the top of the PR body, before the summary list.
- Push `tempo/<task-id>` and open a pull request against the base branch with `pr.md` as the body. Open it as a draft unless config says otherwise. Use `gh pr create` if available.
- IF pushing or `gh` fails, THEN stop, keep the branch local, and give Jorge the exact commands.
- Remove the task's worktrees with `git worktree remove`. Keep the branches.
- Raise GATE-PR: give Jorge the PR link and a 3-line summary. Jorge merges. TEMPO never merges.
- Set `state.md` stage DONE.

## 4 Gates and escalations

4.1 The only moments to stop for Jorge:

| Kind | When | What Jorge gets |
|---|---|---|
| GATE-CLARIFY | Task Card §6 not NIL | 1–3 questions with options found in the code |
| GATE-SPEC | L lane; M lane with open decisions | the Spec, with assumptions and open decisions on top |
| GATE-PR | PR open | PR link with QA evidence per criterion |
| NO-REPRO | bug not reproduced within budget | what was tried, and the user details that would help |
| BEHAVIOUR-CHANGE | the fix changes intended behaviour | old vs new behaviour, and who it affects |
| OUT-OF-ORDER-DECISION | the architect cannot answer a builder's question without changing the goal | the decision and options |
| LOOP-LIMIT | review or QA passes the round limit | the finding that keeps coming back, and options |
| HARD-TO-UNDO | new dependency, migration on real data, secrets, deploys, force-push, deleting branches | the action and its effect |

4.2 To raise one:
1. Write `esc-N.md` from the template. It SHALL include a recommended option.
2. Set `state.md` §3.2 to WAITING-ON-JORGE and §7 to the file.
3. Send Jorge one message: the question, the options, the recommendation, and "Reply yes to accept, or /tempo:resume <task-id> <answer> later."
4. End your turn. Do not continue other stages of this task while waiting, except read-only work.
4.3 On Jorge's answer, record it in `esc-N.md` as AMDT 1, set the state back to RUNNING and continue from §8 NEXT ACTION.

## 5 Rules for the orchestrator

5.1 Give each agent only the files its stage reads (see the index in the artifact-templates skill). Do not paste conversation history into an agent prompt.
5.2 Every agent prompt SHALL state: task ID, mode or lens, the absolute path of each input, the absolute path of each output, the template path, and the checker command.
5.3 Run independent agents in parallel, in one message.
5.4 Do not write production code yourself. Builders write code. You MAY fix a mechanical document error (§2.3).
5.5 Do not skip a stage the route lists. To skip one, raise an escalation.
5.6 Never merge the PR. Never push to the base branch. Never force-push.
5.7 Keep Jorge's messages short: one progress line per stage, one message per gate.
