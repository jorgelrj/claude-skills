---
name: orchestrator
description: The TEMPO stage machine. Runs a task from Triage to an open pull request (or, in plan-only mode, to a reviewed plan) by calling one TEMPO agent per stage, checking each handoff document, and stopping only at Jorge's gates and escalations. Handles single-repo tasks and workspace tasks that span several repos. Use when /tempo:feature, /tempo:bug, /tempo:plan or /tempo:resume runs, or when asked to run a task "the TEMPO way".
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
0.8 State script: `<state>` is `python3 <orch>/scripts/tempo_state.py`. It needs only the Python standard library. It is the only writer of `state.json` and `state.md`. Its docstring lists every subcommand.

## 1 Start of every run

1.0 Mode. The mode is PLAN-ONLY when the command is `/tempo:plan`, or the request starts with `--plan-only`. Otherwise it is FULL. Remove the flag from the request text.

1.1 Find the repository.
  - 1.1.1 IF the working directory is inside a git repository, THEN that repository is the target.
  - 1.1.2 IF it is not, THEN run `<cfg> repos`. IF it lists repos, THEN this is a workspace task. Follow section 6 instead of sections 1.2 to 3.
  - 1.1.3 IF there is no repository and no workspace file, THEN stop and tell Jorge. Offer `/tempo:init` to describe the workspace.
1.2 Run `<cfg> check --repo <repo>`. IF it prints FAIL, THEN show Jorge the findings and stop. IF it warns about a legacy `config.md`, THEN tell Jorge once, with the migrate command.
1.3 Run `<cfg> resolve --repo <repo>` once. Its `config` object is this run's config. Every later "from config" means a value from it. Do not read config files by hand.
1.4 IF `commands.test` is null, THEN detect it from the repo (package.json scripts, pubspec.yaml, Makefile, pyproject.toml, go.mod, Cargo.toml, pom.xml, build.gradle). Record what you used in `state.md` §1. Offer once to write it into `.tempo/config.yaml`.
1.5 Ensure `.tempo/` is listed in `.git/info/exclude` (`git rev-parse --git-path info/exclude`). This keeps artifacts, config and worktrees out of the diff without touching tracked files.
1.6 Task ID. IF `task.id` is `ticket` and the request contains a key matching `task.ticket_pattern`, THEN the task ID is that key (`AV-5696`). Otherwise it is `T-` plus the next free 3-digit number in `.tempo/`. IF `.tempo/<task-id>/` already exists, THEN resume it as `/tempo:resume` does instead of starting over.
1.7 Branch names. Run `<cfg> names --repo <repo> --task <task-id> --ticket <ticket or task-id>`. Use these names exactly. Never invent a branch name.
1.8 Commands. For each command an agent needs, run `<cfg> cmd <name> --repo <repo>` and pass the printed line as is. It exports the configured env (JDK, PATH) first.
1.9 Create the state: `<state> init .tempo/<task-id> --task <task-id> --flow <FEATURE|BUG> --mode <mode> --title "<request, one line>" --base-branch <git.base_branch> --base-commit <hash of its head> --task-branch <task branch> --review-limit <limits.review_rounds> --review-extensions <limits.review_extensions> --qa-limit <limits.qa_rounds>`. Add `--parent <workspace task folder>` for a child task (section 6).

## 2 After every stage

2.1 Run the checker on the artifact the stage wrote.
2.2 IF it FAILS, THEN send the findings back to the same agent and ask for a re-issue as AMDT n+1. Allow 2 returns.
2.3 After 2 returns, fix the remaining mechanical findings yourself, add an amendment log line saying so, and continue.
2.4 Read the artifact for the rules the checker cannot see: one meaning per term, bound references, imperative procedures.
2.5 Update the state with `<state>` only: `log <dir> <STAGE> <artifact> <PASS|FAIL|BLOCKED>`, then `set <dir> --stage <next stage> --next "<exact next step>"`. Use `bump` for loop counters, `wo` for Work Orders, `wait` for escalations, `set --lane` after triage. Never edit `state.md` or `state.json` by hand; never use `sed` on them.
2.6 Post one line of progress to Jorge: stage, artifact, result. Do not paste the artifact.
2.7 Agents in flight. Before you start an agent, write its full prompt to `.tempo/<task-id>/prompts/<label>.md`. Right after it starts, run `<state> agent <dir> start <agent id> --label "<label>" --output <its output path> --prompt <prompt file>`. When it replies, run `<state> agent <dir> done <agent id>`. Section 7 uses this list after a restart.

## 3 Stages

Run the stages the Task Card's ROUTE lists, in this order.

### 3.1 TRIAGE (all flows)
- Call `triage` with: Jorge's request verbatim, the flow hint (feature or bug), the task folder, the template path, the rubric path.
- Output: `task.md`.
- IF §6 QUESTIONS FOR JORGE is not NIL, THEN raise GATE-CLARIFY (section 4). On the answer, call `triage` again to amend `task.md`.

### 3.2 EXPLORE (feature, M and L)
- Call 3 `scout` agents in parallel, in one message, with lenses `CODE-PATHS`, `DATA-MODEL`, `PATTERNS-AND-TESTS`. Pass `task.md`.
- S lane: skip. M lane: MAY run `CODE-PATHS` and `PATTERNS-AND-TESTS` only.
- IF the change calls another service or library whose behaviour decides the result (payments, webhooks, queues, external APIs), or ports existing code, THEN also call a fourth `scout` with lens `CONSUMED-BEHAVIOUR`, in M and L lanes. Pass the services and code to port, with their paths, from `task.md` and the workspace config.
- Merge their replies into `context.md` from the template. Remove duplicates. Keep the reason for each file. BEHAVIOUR lines go to §9 CONSUMED BEHAVIOUR.

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
3. Write the worktree path and branch into the order header, and run `<state> wo <dir> WO-NN --worktree <path> --branch <branch> --status ISSUED`.
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
- IF FAIL, THEN return the failing orders to BUILD with the evidence (amend the order). This counts as a review round: run `<state> bump <dir> review` and follow 3.10.2. The REVIEW that follows the repaired integration does not bump again.
- After the last wave integrates, continue.

### 3.10 REVIEW (all)
1. Round number. Run `<state> bump <dir> review` before the reviewers start. The new count is N. Every review round counts, extensions and fixes after GATE-PR included.
2. Limits. IF `bump` exits 1, THEN raise LOOP-LIMIT before reviewing. IF it exits 2, THEN follow 3.10.6. Do not review.
3. Round kind. Round 1 is FULL. A later round is NARROW when all hold:
   - 3.1 The fix diff, `git diff --shortstat <previous round head>..<head>`, changes `limits.narrow_fix_lines` lines or fewer.
   - 3.2 The amendment changed no criterion Jorge approved.
   - 3.3 The round does not follow a FIX-CHAIN re-spec.
   Otherwise it is FULL. Review-rules §2.1 says which lenses and diff a NARROW round uses.
4. Review:
   - Depth comes from the lane (triage-rubric §3.3). Lenses come from review-rules §2.
   - The previous round head is the head hash in `findings-r<N-1>.md` §1.3. Round 1 has none.
   - Call one `reviewer` per lens, in parallel, in one message. Pass: base and head commit, the previous round head, kind, lens, depth, criteria source (`spec.md` §3 or `repro.md` §6), rules file list. Each writes `review/<lens>-rN.md`.
   - Bug flow: the correctness reviewer also runs the sibling sweep from `repro.md` §8.
   - Call `verifier` with all raw findings files, the previous findings file and the previous round head. Output: `findings-rN.md`.
5. On FAIL, in this order:
   - 5.1 Fix chain. IF this round has an INTRODUCED finding and round N-1 had an INTRODUCED finding in the same area (findings §3 Area), THEN raise FIX-CHAIN. Do not patch again.
   - 5.2 Otherwise call `architect` in AMEND mode on `spec.md` (feature) with the findings, so it runs the interaction check, then on each owning order.
   - 5.3 Go back to BUILD for those orders only. Skip the READBACK when the amended order adds no file to §4.1 and changes no criterion text; the builder builds from the amended order. Then INTEGRATE, then REVIEW again.
6. Hard stop. When `bump` exits 2, or Jorge chose to ship at LOOP-LIMIT or FIX-CHAIN:
   - 6.1 Record each open confirmed finding as a known risk: one line in `spec.md` §1 (AMDT n+1), and one line in `pr.md` §6 with its follow-up.
   - 6.2 Continue to QA. No escalation and no gate offers another fix round, GATE-PR included.
   - 6.3 Only Jorge's own words naming a higher limit (`/tempo:resume <task-id> review-limit <N>`) reopen review.

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
- `<state> set <dir> --pr <url> --stage DONE`. IF the task has a parent, THEN run `<state> tracker <parent dir>`.

### 3.13 PLAN-ONLY stop (single repo)
- In PLAN-ONLY mode, run the route up to and including HANDOFF, then stop. Do not create work-order worktrees or branches, and do not BUILD.
- The bug route keeps REPRODUCE and ROOT-CAUSE: they commit only a test, on the repro branch.
- Write `plan.md` from the template, SCOPE: REPO. One slice per Work Order. Each Work Order's DEPENDS ON becomes a blocks-start edge. Open decisions come from Spec §1 (or Repro §7). Check it.
- `<state> log <dir> HANDOFF plan.md PASS`, then `<state> set <dir> --stage PLANNED --next "Run BUILD wave 1 (resume with build)"`, then raise GATE-PLAN.

### 3.14 Resume from PLANNED
- `/tempo:resume <task-id> build` starts here.
- Fetch the base branch. IF its head differs from the base commit in `state.md` §1.3, THEN call `reviewer` with lens SPEC-PRECHECK on `spec.md` (or `repro.md`) against the new head. IF it has candidate findings, THEN call `architect` in AMEND mode, then HANDOFF again. Record the new base with `<state> set <dir> --base-commit <hash>`.
- `<state> set <dir> --mode FULL --stage BUILD`, then continue at 3.8.

## 4 Gates and escalations

4.1 The only moments to stop for Jorge:

| Kind | When | What Jorge gets |
|---|---|---|
| GATE-CLARIFY | Task Card §6 not NIL | 1–3 questions with options found in the code |
| GATE-SPEC | L lane; M lane with open decisions | the Spec, with assumptions and open decisions on top |
| GATE-PLAN | plan-only mode reached PLANNED; every workspace task after PLAN | `plan.md`: slices, typed dependencies, external blockers, open decisions; how to build later (`/tempo:resume <task-id> build`) |
| GATE-PR | PR open | PR link with QA evidence per criterion |
| NO-REPRO | bug not reproduced within budget | what was tried, and the user details that would help |
| BEHAVIOUR-CHANGE | the fix changes intended behaviour | old vs new behaviour, and who it affects |
| OUT-OF-ORDER-DECISION | the architect cannot answer a builder's question without changing the goal | the decision and options |
| LOOP-LIMIT | review or QA passes the round limit | the open findings, how many were introduced by fixes, and the options: (a) one extension round, only while `limits.review_extensions` allows; (b) ship them as known risks (3.10.6) |
| FIX-CHAIN | two rounds in a row each have a finding introduced by the last fix, in the same area | the chain of findings, and the options: (a) re-spec that area: architect AMEND on Spec §8 for it, HANDOFF, BUILD, then a FULL round; (b) ship as known risks (3.10.6); (c) revert the last fix and ship its finding as a known risk |
| HARD-TO-UNDO | new dependency, migration on real data, secrets, deploys, force-push, deleting branches | the action and its effect |

4.2 To raise one:
1. Write `esc-N.md` from the template. It SHALL include a recommended option.
1.1 LOOP-LIMIT and FIX-CHAIN: "the fix is small" is not a reason to recommend another round. Each of the last fix rounds was small too. Recommend re-spec when findings were introduced by fixes; otherwise recommend shipping known risks unless a HIGH finding is open.
1.2 GATE-PR: IF review has reached the hard stop, THEN the options do not include a fix round. A fix after the PR is open is a review round (3.10.1).
2. Run `<state> wait <dir> esc-N.md`.
3. Send Jorge one message: the question, the options, the recommendation, and "Reply yes to accept, or /tempo:resume <task-id> <answer> later."
4. End your turn. Do not continue other stages of this task while waiting, except read-only work.
4.3 On Jorge's answer, record it in `esc-N.md` as AMDT 1, run `<state> wait <dir> --clear` and continue from §8 NEXT ACTION.
4.4 GATE-PLAN needs no `esc-N.md`: `plan.md` is the question. Run `<state> wait <dir> plan.md`. IF Jorge answers open decisions, THEN call `architect` in AMEND mode on `plan.md` (and `spec.md`) first.

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

## 6 Workspace tasks (several repos)

6.1 A workspace task starts when the working directory is a workspace root (1.1.2). Its folder is `<workspace>/.tempo/<task-id>/`. Run 1.0, 1.2 and 1.3 with `--repo <workspace>`, and 1.6 for the ID.
6.2 `<state> init <workspace>/.tempo/<task-id> --task <task-id> --flow WORKSPACE --mode <mode> --title "<request>" --base-branch <defaults.git.base_branch> --base-commit NIL --qa-limit <limits.qa_rounds>`.
6.3 TRIAGE: call `triage` with `Scope: WORKSPACE` and the output of `<cfg> repos`. Raise GATE-CLARIFY as in 3.1.
6.4 EXPLORE: call one `scout` with lens CROSS-REPO per repo the Task Card names, in parallel, at most `limits.max_parallel_builders` at a time. Merge their replies into `context.md`, one block of §3 lines per repo, copy every CONTRACTS line into §4 and every BEHAVIOUR line into §9. The architect copies the §9 lines each slice consumes into the slice, so the child's scouts and spec start from them.
6.5 PLAN: call `architect` in mode PLAN. Output: `plan.md`. Check it. Then raise GATE-PLAN, always. In PLAN-ONLY mode, `<state> set <dir> --stage PLANNED` first and stop at the gate.
6.6 REPOS: for each slice, in §6 ORDER:
  - 6.6.1 Register it: `<state> child <dir> <repo> --folder <repo>/.tempo/<task-id>`.
  - 6.6.2 A slice starts only when every blocks-start source has passed INTEGRATE.
  - 6.6.3 Before it builds, run each blocks-start source's `build` command on that source's task branch, so local artifacts (installed libraries, generated clients) match it.
  - 6.6.4 Run sections 1.2 to 3 for it from the repo root, as a child task: the request is the slice line; triage also gets the parent `plan.md` and `task.md`; `init` gets `--parent`.
  - 6.6.5 Child gates (GATE-SPEC on L lanes, escalations) still stop for Jorge.
  - 6.6.6 After every child stage, run `<state> tracker <dir>`. `tracker.md` is the cross-repo status; never write a tracker by hand.
  - 6.6.7 At the child's SHIP, the PR body lists the PR links of its blocks-merge sources (from `tracker.md`) under a "Depends on" line, in `pr.language`. Record the link with `<state> set <child dir> --pr <url>`.
  - 6.6.8 Run children one at a time. IF a later child needs a change in an earlier child's repo, THEN raise OUT-OF-ORDER-DECISION: amend the earlier child's plan slice, or add a slice.
6.7 JOINT-QA: when every child has an open PR, call `qa` in mode JOINT with `plan.md`, every repo's task branch and build command, and the workspace config's `validation.steps`. Output: `<workspace>/.tempo/<task-id>/qa-joint-rN.md`. IF FAIL, THEN resume the owning child at BUILD with the failing criterion added to its Work Order. Rounds stop at `limits.qa_rounds`; then LOOP-LIMIT.
6.8 Ship: raise GATE-PR with `tracker.md` (every PR link) and the joint QA evidence. `<state> set <dir> --stage DONE`.

## 7 After a restart

7.1 A restart ends background agents. On resume, and whenever a notification says agents did not finish before the previous session ended, read `state.md` §9 AGENTS IN FLIGHT.
7.2 For each agent listed: send it a message by its agent ID: "The session restarted. Continue from where you stopped and finish with the reply your prompt asks for. Write <output path>."
7.3 IF the agent cannot be reached, THEN start a new agent with the saved prompt file, and replace the entry with `<state> agent ... start`.
7.4 Do this without asking Jorge. Tell Jorge in one line which agents you restarted.
