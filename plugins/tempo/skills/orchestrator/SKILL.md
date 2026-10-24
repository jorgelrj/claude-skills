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
0.7 Config script: `<cfg>` is `uv run --quiet <orch>/../config/scripts/tempo_config.py` when `uv` is on PATH, else `python3 <orch>/../config/scripts/tempo_config.py`. The config skill (`<orch>/../config/SKILL.md`) explains the files and every subcommand.

## 1 Start of every run

1.1 Find the repository.
  - 1.1.1 IF the working directory is inside a git repository, THEN that repository is the target.
  - 1.1.2 IF it is not, THEN run `<cfg> repos`. IF it lists repos, THEN ask Jorge which repos the request touches, with a recommendation from the request. Run one task per chosen repo, in the listed order, each from its repo root.
  - 1.1.3 IF there is no repository and no workspace file, THEN stop and tell Jorge. Offer `/tempo:init` to describe the workspace.
1.2 Run `<cfg> check --repo <repo>`. IF it prints FAIL, THEN show Jorge the findings and stop. IF it warns about a legacy `config.md`, THEN tell Jorge once, with the migrate command.
1.3 Run `<cfg> resolve --repo <repo>` once. Its `config` object is this run's config. Every later "from config" means a value from it. Do not read config files by hand.
1.4 IF `commands.test` is null, THEN detect it from the repo (package.json scripts, pubspec.yaml, Makefile, pyproject.toml, go.mod, Cargo.toml, pom.xml, build.gradle). Record what you used in `state.md` §1. Offer once to write it into `.tempo/config.yaml`.
1.5 Ensure `.tempo/` is listed in `.git/info/exclude` (`git rev-parse --git-path info/exclude`). This keeps artifacts, config and worktrees out of the diff without touching tracked files.
1.6 Task ID. IF `task.id` is `ticket` and the request contains a key matching `task.ticket_pattern`, THEN the task ID is that key (`AV-5696`). Otherwise it is `T-` plus the next free 3-digit number in `.tempo/`. IF `.tempo/<task-id>/` already exists, THEN resume it with `/tempo:resume` instead of starting over. Create `.tempo/<task-id>/` and `state.md` from the template.
1.7 Branch names. Run `<cfg> names --repo <repo> --task <task-id> --ticket <ticket or task-id>`. Record the task branch, repro branch and work-order pattern in `state.md` §1. Use these names exactly. Never invent a branch name.
1.8 Commands. For each command an agent needs, run `<cfg> cmd <name> --repo <repo>` and pass the printed line as is. It exports the configured env (JDK, PATH) first.
1.9 Record the base branch and its commit hash in `state.md` §1.3.

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
- Pass the repro branch name from §1.7.
- Output: `repro.md` §1–4 and a failing test committed on the repro branch.
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
1. For each order, get its branch name with `<cfg> names --task <task-id> --wo NN` and create a worktree: `git worktree add <git.worktree_root>/<task-id>-wo-NN -b <work-order branch> <start>`. Wave 1 starts from the base commit (bug flow: from the repro branch). Later waves start from the task branch.
2. Prepare it: run the lines `<cfg> setup --worktree <path>` prints, in order. IF a line fails, THEN stop that order and raise HARD-TO-UNDO only if the fix needs a secret or a new dependency; otherwise fix the config with Jorge's yes.
3. Write the worktree path and branch into the order header and `state.md` §6.
4. Readback: call `builder` in mode READBACK for every order in the wave, in parallel, in one message. Max parallel builders comes from config.
5. Compare each `readback-NN.md` with its order:
   - Files in RB §3 SHALL be a subset of WO §4.1.
   - Criteria in RB §4 SHALL equal WO §3.
   - The objective SHALL match WO §1.1 in meaning.
   - RB §5 QUESTIONS SHALL be NIL.
6. IF any check fails, THEN call `architect` to amend the order (AMDT n+1). Do not correct the builder. Repeat the readback for that order.
7. Build: call `builder` in mode BUILD for every accepted order, in parallel. Prefer continuing the same builder agent if the Agent tool lets you message it; otherwise start a new one with the order and the accepted readback.
8. Each builder writes `report-NN.md` and commits on its branch.
9. IF a report is BLOCKED by a stop condition, THEN call `architect` with the report. The architect amends the order, or raises OUT-OF-ORDER-DECISION when the answer changes the goal.

### 3.9 INTEGRATE (all)
- Call `integrator` with the reports, branches and the full test and build commands.
- Pass the task branch and the work-order branch names from §1.7.
- It merges every WO branch into the task branch and writes `integration.md`.
- IF FAIL, THEN return the failing orders to BUILD with the evidence (amend the order). This counts as a review round.
- After the last wave integrates, continue.

### 3.10 REVIEW (all)
- Depth comes from the lane (triage-rubric §3.3). Lenses come from review-rules §2.
- Call one `reviewer` per lens, in parallel, in one message. Pass: base and head commit, lens, depth, criteria source (`spec.md` §3 or `repro.md` §6), rules file list. Each writes `review/<lens>-rN.md`.
- Bug flow: the correctness reviewer also runs the sibling sweep from `repro.md` §8.
- Call `verifier` with all raw findings files. Output: `findings-rN.md`.
- IF §7 RESULT is FAIL, THEN amend each owning order with its confirmed findings added to §5 PROCEDURE and go back to BUILD (step 3.8.4), for those orders only. Then INTEGRATE, then REVIEW again with N+1.
- Review rounds stop at the config limit (default 3). Then raise LOOP-LIMIT.

### 3.11 QA (feature M and L, all bugs)
- Call `qa` with the criteria source, the integration branch and the commands. Output: `qa-rN.md`.
- IF FAIL, THEN amend the owning orders with the failing criterion and its evidence, and go back to BUILD. QA rounds stop at the config limit; then raise LOOP-LIMIT.
- S feature lane: skip QA. The builder's verification and the quick review stand in for it.

### 3.12 SHIP (all)
- Write `pr.md` from the template, using: Task Card §5, Spec §1 (or Repro §5 and §7), QA §3, Findings §6, the integration diff stat.
- Assumptions SHALL appear at the top of the PR body, before the summary list.
- `pr.md` is the internal record. The PR body is written from it in `pr.language`, following the repo's PR template (`pr.body_template`, else `.github/pull_request_template.md` if present). Assumptions stay at the top.
- PR title: `pr.title` with `{type}` and `{summary}` filled, in `pr.language`. Check the repo's CI files for a title rule and follow it.
- Push the task branch and open a pull request against `pr.base`. Draft when `pr.draft` is true. IF `pr.tool` is `none`, THEN push nothing and give Jorge the exact commands.
- IF pushing or `gh` fails, THEN stop, keep the branch local, and give Jorge the exact commands.
- Remove the task's worktrees with `git worktree remove`.
- IF `git.delete_merged_local_branches` is true, THEN delete the local work-order and repro branches with `git branch -d` (never `-D`, never a remote branch). Keep the task branch.
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
5.2.1 Agents that run code also get: the command lines from §1.8, the branch names from §1.7, and the commit rules (`git.commit.message`, `git.commit.language`, `git.commit.extra_args`).
5.2.2 Every output path SHALL be the final path in `.tempo/<task-id>/`. No agent writes an artifact to a temp folder first.
5.3 Run independent agents in parallel, in one message.
5.4 Do not write production code yourself. Builders write code. You MAY fix a mechanical document error (§2.3).
5.5 Do not skip a stage the route lists. To skip one, raise an escalation.
5.6 Never merge the PR. Never push to the base branch. Never force-push.
5.7 Keep Jorge's messages short: one progress line per stage, one message per gate.
