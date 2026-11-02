---
name: orchestrator
description: The TEMPO stage machine. Runs a task from Triage to an open pull request (or, in plan-only mode, to a reviewed plan) by calling one TEMPO agent per stage, checking each handoff document, and stopping only at Jorge's gates and escalations (or, on autopilot, only at the few that need Jorge). Handles single-repo tasks and workspace tasks that span several repos. Use when /tempo:feature, /tempo:bug, /tempo:plan or /tempo:resume runs, or when asked to run a task "the TEMPO way".
---

# TEMPO orchestrator

You are the orchestrator. You run in the main session. You call agents; agents do not call each other.
Nothing travels between agents except files in `.tempo/<task-id>/`.

## 0 Paths you need

0.1 This skill's directory is `<orch>`. The plugin root is `<orch>/../..`.
0.2 Templates: `<orch>/../artifact-templates/templates/`.
0.3 Document checker: `python3 <orch>/../document-standard/scripts/check_doc.py <files>`. It checks structure only and runs in well under a second.
0.4 Rubric: `<orch>/../triage-rubric/SKILL.md`. Rules and lenses: `<orch>/../review-rules/SKILL.md`.
0.5 Resolve these to absolute paths once, at the start. Pass absolute paths to every agent. Agents do not know where the plugin lives.
0.6 Agent names. Installed as a plugin, the agents appear as `tempo:triage`, `tempo:scout`, and so on. Use whichever name the Agent tool lists.
0.7 Config script: `<cfg>` is `uv run --quiet <orch>/../config/scripts/tempo_config.py` when `uv` is on PATH, else `python3 <orch>/../config/scripts/tempo_config.py`. The config skill (`<orch>/../config/SKILL.md`) explains the files and every subcommand.
0.8 State script: `<state>` is `python3 <orch>/scripts/tempo_state.py`. It needs only the Python standard library. It is the only writer of `state.json` and `state.md`. Its docstring lists every subcommand.
0.9 Baseline script: `<bl>` is `python3 <orch>/scripts/tempo_baseline.py`. Standard library only. It records which platform-target tests already fail on a base commit (`.tempo/baselines/`) and compares a run with them by name. Its docstring lists every subcommand.
0.10 Branch script: `<br>` is `python3 <orch>/scripts/tempo_branches.py`. Standard library only. It deletes local work-order and repro branches whose work the task branch already holds, and keeps everything else. Its docstring lists the checks.
0.11 Run script: `<run>` is `python3 <orch>/scripts/tempo_run.py`. Standard library only. Agents run every test, build, lint and target command through it: the command runs in a detached worker, each call blocks up to 110 seconds, and a longer run returns `RUNNING` (exit 75) with an ID for `<run> wait <ID>`. That stays under the 3-minute cap Claude Code puts on commands in async subagents, which no `timeout` lifts. The summary holds exit, time, failure lines and tail, and the output stays in a log. `--heavy` takes one of a few machine-wide slots. Pass it to every agent that runs code (5.2.1). Its docstring has the flags.
0.11.1 Always define `<run>` with the task folder: `python3 <orch>/scripts/tempo_run.py --task <abs task dir>`. Every process a run starts is then marked with the task, and what the command leaves running (a test's emulator, chromedriver) is stopped when it ends and named as LEFTOVERS in the summary.
0.12 Process script: `<procs>` is `python3 <orch>/scripts/tempo_procs.py`. Standard library only. Anything that must keep running past one command (a dev server, the app for QA, an emulator or simulator, a watcher, a docker stack) starts with `<procs> start --task <abs task dir> --label <name> [--ready <regex>] [--stop <cmd>] -- '<command>'` and stops with `<procs> stop --task <dir> --label <name>`. It records the process in `<task dir>/procs.json` and marks it and all its children with the task. Section 10 says when TEMPO tears a task down. Pass `<procs>` to every agent that runs code (5.2.1).

## 1 Start of every run

1.0 Mode. The mode is PLAN-ONLY when the command is `/tempo:plan`, or the request starts with `--plan-only`. Otherwise it is FULL. Remove the flag from the request text.
1.0.1 Lane override. IF the request carries `--lane S`, `--lane M`, `--lane L` or `--quick` (= `--lane S`), THEN remove the flag from the request text and pass the lane to triage as the override (triage-rubric §3.6). Explore does not re-size an overridden lane.
1.0.2 Autopilot. IF the request carries `--auto` (or `--autopilot`), THEN autopilot is ON. IF it carries `--no-auto`, THEN it is OFF. Otherwise it is `task.autopilot` from config (1.3). Remove the flag from the request text. Pass `--autopilot` to `init` (1.9) when ON, and tell Jorge in the route-chosen line: "Autopilot: ON. I stop only for <list from 4.5.1>." Section 4.5 says what changes.

1.1 Find the repository.
  - 1.1.1 IF the working directory is inside a git repository, THEN that repository is the target.
  - 1.1.2 IF it is not, THEN run `<cfg> repos`. IF it lists repos, THEN this is a workspace task. Follow section 6 instead of sections 1.2 to 3.
  - 1.1.3 IF there is no repository and no workspace file, THEN stop and tell Jorge. Offer `/tempo:init` to describe the workspace.
1.2 Run `<cfg> check --repo <repo>`. IF it prints FAIL, THEN show Jorge the findings and stop. IF it warns about a legacy `config.md`, THEN tell Jorge once, with the migrate command.
1.2.1 Worktree gaps. IF it warns that a git-ignored file is missing from worktree setup (an SDK link such as `.fvm`, an `.env`), THEN add it to `worktree.link` (a folder) or `worktree.copy` (a file) in `<repo>/.tempo/config.yaml` before any worktree is made, and tell Jorge in one line. On autopilot, record it with `<state> decide` instead. A worktree has only tracked files; a builder that has to recreate one by hand loses minutes and may point it at the wrong version.
1.3 Run `<cfg> resolve --repo <repo>` once. Its `config` object is this run's config. Every later "from config" means a value from it. Do not read config files by hand.
1.3.1 Project docs. Run `<cfg> docs --repo <repo>` once. It prints the project's documentation files (config `docs:`), index files first. Save the list as `.tempo/<task-id>/docs.txt` once 1.6.0 has claimed the folder and pass that path to every scout, the architect, every reviewer and QA. IF it prints nothing, THEN pass NIL. Section 8 says how each agent uses it.
1.3.2 Standing decisions. `task.standing_decisions` from config are answers Jorge has already given (a delivery order, a scoping rule). Pass them to triage. Do not raise GATE-CLARIFY for a question one of them answers: apply it, and name it in the progress line.
1.3.3 Sources. Before triage, list every source of truth the request and the ticket name for the work: a linked ticket, an attachment, a design file or prototype (with the version it names), a spec or doc, an asset, an API doc. Try to open each one: search the repo and workspace, fetch it from the tracker, follow the link. Pass triage one line per source: `<source> | named in <where> | FOUND <path> | MISSING <what was tried>`. An older or newer version, another brand's file, a copy of a different source or a picture of it is MISSING, not FOUND. Triage turns each MISSING source the work depends on into a `NEEDS-JORGE MISSING-SOURCE` question, so GATE-CLARIFY stops for it, on autopilot too (4.5.1). Never pick a stand-in here and record it as a decision.
1.4 IF `commands.test` is null, THEN detect it from the repo (package.json scripts, pubspec.yaml, Makefile, pyproject.toml, go.mod, Cargo.toml, pom.xml, build.gradle). Record what you used in `state.md` §1. Offer once to write it into `.tempo/config.yaml` (on autopilot, do not offer: record it in `decisions.md` with `<state> decide`).
1.5 Ensure `.tempo/` is listed in `.git/info/exclude` (`git rev-parse --git-path info/exclude`). This keeps artifacts, config and worktrees out of the diff without touching tracked files.
1.6 Task ID. IF `task.id` is `ticket` and the request contains a key matching `task.ticket_pattern`, THEN the task ID is that key (`AV-5696`; with a capture group in the pattern, the group: `#215` → `215`). Otherwise it is a local `T-NNN` id.
1.6.0 Claim the folder. Never pick the number or make the folder yourself: two tasks started at the same time both see the same number free. Run `<state> claim .tempo` for a `T-NNN` id, or `<state> claim .tempo --id <ticket key>` for a ticket. It makes the folder with an atomic mkdir and prints `TASK: <task-id>`; use that id from here on. IF it prints `EXISTS` (exit 3) and the folder has a `state.json`, THEN resume it as `/tempo:resume` does instead of starting over. IF it has no `state.json`, THEN another session is starting the same ticket right now: stop and tell Jorge.
1.6.1 Local IDs stay local. A `T-NNN` id is numbered per checkout; on another machine `T-004` is a different task. Use it for `.tempo/` paths, `state`, prompts and talk with Jorge only. It SHALL NOT appear in anything that leaves this machine or outlives the task folder: branch names, commit messages, merge commits, PR titles and bodies, PR review replies, GitHub issues and their comments, Jira or other tracker text, code, code comments, test names, docs. The same holds for every other TEMPO-internal reference that points into `.tempo/` (`WO-NN`, `ESC-N`, a `.tempo/` path). Name the thing instead: the ticket key, the PR or issue link, or a few words on the change. AC, F and D tags MAY label items listed in the same PR body.
1.6.2 Slug. Pick a slug for the task: 2 to 5 kebab-case words on the change, from the request (`fix-safari-export`). It names branches when there is no ticket. Later steps take names from the task branch in the state (`--branch`), so the slug is needed only here.
1.6.3 Type. Pick the change's Conventional Commits type: `feat` for the feature route, `fix` for the bug route, or `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci` when the whole change is that kind (a dependency bump, a docs-only change). The same type heads the PR title.
1.7 Branch names. Run `<cfg> names --repo <repo> --type <type> --ticket <ticket key, or omit> --slug <slug>`. Never pass a `T-NNN` id. Use the names it prints exactly. Never invent a branch name. Its `commit_message` and `pr_title` already drop an empty ticket.
1.7.1 Repo convention. The task branch is the only branch TEMPO pushes, so it follows the repo's own convention: `git.branch` when a config file sets it, else the type words the remote branches already use (`feature/`, `bugfix/`, `story/`), else `{type}/{ticket}` (`feat/AV-1`, `fix/safari-export`). `names` prints which one it used as `branch_convention`. IF it is not `config` and the repo's CONTRIBUTING or rule docs (1.3.1) state a branch rule, THEN that rule wins: write it into `<repo>/.tempo/config.yaml` (`git.branch`, `git.branch_types`), run `<cfg> check` and `names` again, and tell Jorge in one line.
1.7.2 `tempo/` is local. Work-order and repro branches are under `tempo/` (`tempo/AV-1-wo-01`). They exist only on this machine and SHALL NOT be pushed, used as a PR head or named in outward text. The plugin's push hook denies a push to any `tempo/` name. `names` refuses a task branch under `tempo/`.
1.8 Commands. For each command an agent needs, run `<cfg> cmd <name> --repo <repo>` and pass the printed line as is. It exports the configured env (JDK, PATH) first.
1.9 Create the state: `<state> init .tempo/<task-id> --task <task-id> --flow <FEATURE|BUG> --mode <mode> --title "<request, one line>" --base-branch <git.base_branch> --base-commit <hash of its head> --task-branch <task branch> --review-limit <limits.review_rounds> --review-extensions <limits.review_extensions> --qa-limit <limits.qa_rounds>`. Add `--parent <workspace task folder>` for a child task (section 6), and `--autopilot` when autopilot is ON (1.0.2).

## 2 After every stage

2.1 Run the checker on the artifact the stage wrote.
2.2 IF it FAILS, THEN fix the structure yourself (add a missing heading with NIL, remove a leftover placeholder) and continue. Send it back to the agent only when a section the next stage needs is missing its content. Allow 1 return.
2.3 Do not re-read artifacts for wording. Read only what the next step needs from them.
2.4 Missing sources found later. IF an agent reports a source the work depends on as not found, not accessible or found only in another version (a scout `MISSING SOURCE` line, an architect decision marked MISSING-SOURCE, a builder or QA stop), THEN raise MISSING-SOURCE before any stage decides from it. Read-only stages MAY run while it waits (4.2 step 4); Spec, Handoff and Build SHALL NOT.
2.5 Update the state with `<state>` only: `log <dir> <STAGE> <artifact> <PASS|FAIL|BLOCKED>`, then `set <dir> --stage <next stage> --next "<exact next step>"`. `log` records the stage's start and end, removes the agent that wrote the artifact from §8, and clears Next action, so always follow it with `set --next`. Use `bump` for loop counters, `wo` for Work Orders, `wait` for escalations, `set --lane` after triage. Never edit `state.md` or `state.json` by hand; never use `sed` on them.
2.6 Progress to Jorge: one line per milestone, not per stage. The milestones are: route chosen (with the lane's time estimate), spec ready, build done, review done, PR open. Report a failure, a re-size or an escalation when it happens. Do not paste the artifact.
2.6.1 Long agents. You hear nothing while an agent runs, and neither does Jorge. Before you start an agent that is likely to run 20 minutes or more (QA, a builder on an L order, the final integrate, a parent integrate, a run with screenshots), send one line saying what it does and roughly how long: "QA is running: 14 criteria, screenshots in both brands, about an hour." This holds on autopilot too.
2.6.2 Status asks. IF Jorge asks how it is going while agents run, THEN answer from `state.md` §8 and the newest progress lines (QA writes `qa/progress.md`), in one or two lines. Do not interrupt the agents.
2.7 Agents in flight. Before you start an agent, write its full prompt to `.tempo/<task-id>/prompts/<label>.md`. Right after it starts, run `<state> agent <dir> start <agent id> --label "<label>" --output <its output path> --prompt <prompt file>`. When it replies, run `<state> agent <dir> done <agent id>`. Section 7 uses this list after a restart.
2.7.1 Write every prompt file with the Write tool. Never write one through a shell heredoc, `echo` or `cat >`: backticks and `$(...)` in the text run as commands.

## 3 Stages

Run the stages the Task Card's ROUTE lists, in this order.

### 3.1 TRIAGE (all flows)
- Call `triage` with: Jorge's request verbatim, the flow hint (feature or bug), the task folder, the template path, the rubric path, the sources list (1.3.3), and whether autopilot is ON.
- Output: `task.md`.
- IF §6 QUESTIONS FOR JORGE is not NIL, THEN raise GATE-CLARIFY (section 4). On the answer, call `triage` again to amend `task.md`. On autopilot, follow 4.5: ask only the questions marked NEEDS-JORGE, and take the recommendation for the rest.

- Critical. IF the Task Card §3 says `Critical: YES`, THEN run `<state> set <dir> --critical on`.

### 3.2 EXPLORE (feature, M and L)
- L lane: call 3 `scout` agents in parallel, in one message, with lenses `CODE-PATHS`, `DATA-MODEL`, `PATTERNS-AND-TESTS`. M lane: call `CODE-PATHS` and `PATTERNS-AND-TESTS` only. Pass `task.md` and `docs.txt`.
- S lane: skip.
- IF the change calls another service or library whose behaviour decides the result (payments, webhooks, queues, external APIs), or ports existing code, THEN also call a fourth `scout` with lens `CONSUMED-BEHAVIOUR`, in M and L lanes. Pass the services and code to port, with their paths, from `task.md` and the workspace config.
- Save each scout's reply to `explore/<LENS>.md` as soon as it arrives. IF a scout fails or ends without a reply, THEN start it once more from its saved prompt file. IF it fails again, THEN merge without it and add "Lens <LENS> missing: <error>" to `context.md` §6 Risks.
- Merge their replies into `context.md` from the template. Remove duplicates. Keep the reason for each file. BEHAVIOUR lines go to §8 Consumed behaviour.
- Pattern task (triage-rubric §3.9). IF the lane stays M, a scout's reply has a `SIBLING:` line that is not NIL, and the task needs no schema, design or dependency change, THEN run `<state> set <dir> --pattern on` and tell Jorge in the route line.
- Re-size (triage-rubric §3.5), unless Jorge set the lane. Count the production files `context.md` marks CHANGE. IF the lane changes, THEN run `<state> set <dir> --lane <new>` and tell Jorge in one line. A task that drops to S skips SPEC and goes to HANDOFF with `task.md` and `context.md`.

### 3.3 INVESTIGATE (bug, BUG-FEEDBACK only)
- Call `investigator` with `task.md`. Output: `hypotheses.md`.

### 3.4 REPRODUCE (bug, always)
- Call `reproducer` in mode REPRODUCE with `task.md` and `hypotheses.md` (if present) and the budget from config.
- Pass the repro branch name from §1.7.
- Output: `repro.md` §1–3 and a failing test committed on the repro branch.
- IF §2 Result is NOT REPRODUCED, THEN raise NO-REPRO.

### 3.5 ROOT CAUSE (bug)
- Call `reproducer` in mode ROOT-CAUSE. It completes `repro.md` §4–8.
- IF §6 Behaviour change is not NIL, THEN raise BEHAVIOUR-CHANGE.

### 3.6 SPEC (feature, M and L)
- Call `architect` in mode SPEC with `task.md`, `context.md` and `docs.txt`. Output: `spec.md`. M lane: pass `model: sonnet` on the Agent call.
- Rules pre-check: L lane always. M lane only IF spec §8 STATE MODEL is not NIL. Otherwise skip it; the SPEC review lens checks the rules and docs on the diff.
  - Call `reviewer` with lens `SPEC-PRECHECK` on `spec.md`. Output: `review/spec-precheck.md`.
  - IF the pre-check has a HIGH or MEDIUM candidate, THEN call `architect` to amend `spec.md` and fill §6 RULES CHECK.
  - LOW candidates do not amend the Spec. Pass `review/spec-precheck.md` to the architect at HANDOFF; it folds each LOW note into the order it applies to.
- Gate: L lane always raises GATE-SPEC. M lane raises GATE-SPEC only IF §1 lists an open decision.
- M lane: combine SPEC and HANDOFF in one architect call (mode SPEC+HANDOFF) when no pre-check runs and §1 lists no open decision.

### 3.7 HANDOFF (all)
- Call `architect` in mode HANDOFF with `spec.md` (feature) or `repro.md` (bug), or `task.md` and `context.md` when present (feature S lane). Child task of a workspace (section 6): the parent `plan.md` slice and the parent `context.md` block for this repo. S and M lanes: pass `model: sonnet` on the Agent call.
- Pass `limits.split_orders`, `limits.split_criteria` and `limits.spec_slice_kb` from config, and the `targets:` entries from the resolved config (name, command, scoped_command, advisory, run, paths; the architect matches them to each order). Leave out targets that run for critical changes only, unless the task is critical.
- Output: `wo-01.md` ... One order per builder. File scopes (§3 IN) SHALL NOT overlap.
- IF the architect replies `SPLIT`, THEN follow section 9 instead of 3.8 to 3.12. Tell Jorge in one line how many slices and what each holds.
- Bug flow: exactly one Work Order. Its criteria are `repro.md` §5. It forbids edits to the reproduction test.
- Check scope overlap yourself: list every §3 IN path of every order. IF a path appears twice, THEN return to `architect`.
- Check §5 Verification of every order: IF a line is the full test command (`<cfg> cmd test`), a platform target's whole-suite command, or an advisory target, THEN return to `architect` (architect HANDOFF 7, 7.1). Builders run scoped tests only.
- Group orders into waves by DEPENDS ON. Wave 1 has no dependencies. A `(start)` dependency puts the order in a later wave. An `(order)` dependency does not: both orders build in the same wave, and the integrator stacks their commits in dependency order.

### 3.8 BUILD (all)
For each wave:
1. For each order, get its branch name with `<cfg> names --repo <repo> --branch <task branch from state> --wo NN` and create a worktree: `git worktree add <git.worktree_root>/<task-id>-wo-NN -b <work-order branch> <start>`. Wave 1 starts from the base commit (bug flow: from the repro branch). Later waves start from the task branch.
2. Prepare it: run the lines `<cfg> setup --worktree <path>` prints, in order. Every worktree a task makes gets the same preparation: work-order, repro, integration (`-int`) and base-check worktrees. Pass the command `<cfg> setup --worktree <path>` to every agent that makes its own worktree (reproducer, integrator, QA). IF a line fails, THEN stop that order and raise HARD-TO-UNDO only if the fix needs a secret or a new dependency; otherwise fix the config with Jorge's yes (on autopilot, fix `.tempo/config.yaml` yourself and record it with `<state> decide`).
3. Write the worktree path and branch into the order header, and run `<state> wo <dir> WO-NN --worktree <path> --branch <branch> --status ISSUED`.
4. Build: call `builder` in mode BUILD for every order in the wave, in parallel, in one message. Orders of the next wave that are already issued: call their builders in mode PREFLIGHT in the same message (4.1). Max parallel builders comes from config. There is no separate readback: the builder reads the order first and stops before its first edit if anything is unclear (WO §6).
4.1 PREFLIGHT gets the order, the task branch name and the path of each order it depends on. It reads the order and the code at the task branch head, edits nothing, and replies READY or BLOCKED with questions. Answer its questions (step 7) while the current wave builds. When the wave integrates, create the order's worktree and continue the same builder agent in mode BUILD.
5. Each builder writes `report-NN.md` and commits on its branch. Run `<state> wo <dir> WO-NN --status DONE` as each report arrives, and `<state> log <dir> BUILD report-NN.md PASS` (the wave's last report) when the wave is done, before INTEGRATE. A split slice logs its BUILD in its own folder the same way.
6. Scope check, for every order: every path in `git diff --name-only <start>..<branch>` SHALL be in the order's §3 IN, or be a test file, test double (fake, mock, stub) or fixture in a package that already holds an IN file and that the report lists in §5 Deviations (builder rule). IF any other path is outside IN, THEN call `architect` to amend the order and rebuild it.
6.1 Deviation gate. Read §5 Deviations of every report. MECHANICAL and SCOPE lines pass. A MECHANICAL line that says the worktree lacked a git-ignored file (an SDK link, an `.env`) is a config gap: add the file to `worktree.link` or `worktree.copy` as 1.2.1 says, so the next worktree has it. For each CRITERION, CONTENT or CUT line, call `architect` in AMEND mode with the report line and the orders not yet built (architect AMEND 4.1), then continue the same builder on the amended order. Do this before the order's check, its fast-forward or the next wave. A deviation that goes on to review is a finding you let through.
6.2 Order check. M and L lanes, when `limits.order_check` is true and the task is not a pattern task. For each order that passed 6 and 6.1, call `reviewer` with lens ORDER and `model: sonnet`: the order, its report, its start commit and branch, the rules files, `docs.txt`. Output: `review/order-NN.md`. Start the checks of a wave in parallel, in one message.
  - IF it has a HIGH or MEDIUM candidate, THEN continue the same builder in mode FIX with `review/order-NN.md`, fold fixes from config, and "PR not open". Then run 6 again. One check per order: do not check the fix again; the full review covers it.
  - LOW candidates stay in `review/order-NN.md`. Pass the order files to the full review's SPEC reviewer, which decides whether they still hold.
  - An order check does not count as a review round.
7. IF a report is BLOCKED (a question in §6, or a stop condition), THEN call `architect` with the report and every order not yet built. The architect amends the order, applies the same change to each later order it fits (the same fake, the same missing test, the same file), or raises OUT-OF-ORDER-DECISION when the answer changes the goal. Then rebuild that order; prefer continuing the same builder agent if the Agent tool lets you message it.
8. Serial chain. IF a wave holds one order and the next wave depends on it, THEN after the scope check, the deviation gate and the order check, fast-forward the task branch to that order's branch yourself (`git merge --ff-only`); its builder already ran the order's verification on that tree. Call the integrator once, after the last wave.

### 3.9 INTEGRATE (all)
- Base drift. Before the integrate that follows the last wave (and before each slice's integrate, section 9), run `git fetch origin <base branch>`. IF `git diff --name-only <base commit>..origin/<base branch>` shares a path with `git diff --name-only <base commit>..<task branch>`, THEN call `integrator` in mode REBASE with the old and new base commits, and on `REBASE: DONE` run `<state> set <dir> --base-commit <new base>` and use the new base from here on. On `REBASE: SKIPPED`, go on with the old base and add one line to `state.md` Next action: rebase at SHIP. A late rebase at the end of a long run is a conflict found when it is most expensive.
- Bars. Unit tests prove a change; the slow suites run at a chosen point. Before each integrate, run `<cfg> bars --paths $(git diff --name-only <base>..<task branch>)`, adding `--critical` when the state shows Critical (3.1). It prints `BARS: NARROW` or `BARS: FULL`, and why. A fix-round integrate (3.10.5.2, 3.10.5.4) is always NARROW, unless the fix diff itself prints FULL.
- NARROW: pass `Bars: NARROW` and the previous integrated head (the base commit on the first integrate). The integrator runs the touched packages' tests, build or typecheck and lint.
- FULL: at most once per task, at the integrate after the last wave (a split task: at the parent integrate, 9.6), never at a slice. Tell Jorge first, as 2.6.1 says.
- Platform targets. Pass `<cfg> targets --ref <task branch> --paths <the same diff>`, adding `--critical` when the bars are FULL. A target marked `run: critical`, and any advisory target by default, prints only with that flag, so a routine task never starts Chrome or a base comparison. Critical targets run once per task, against the task's base commit from `state.md` §1.
- A routine task ships without the full suite. `pr.md` and the PR body say so in one line: "Full suite not run; run `/tempo:verify` before release." The full run happens on `/tempo:verify`, or in the repo's CI where it has one.
- Call `integrator` in mode MERGE with the reports, branches, the test-one, build and lint commands (and the full test command for FULL bars), the bars, and the target lines. A target with `scoped_command` prints one run per package, limited to the test files the diff touches or mirrors, and a `# NO-TESTS` line for changed files no test maps to. A target marked `advisory` is red on the base: pass `<bl>`, the base commit and the worktree setup command, so the integrator compares its failures with the base's (integrator step 5.1).
- Never run a whole platform suite to prove one change. `<cfg> targets --full` belongs to `/tempo:verify`, or to a change to the target's own setup (its config, a test helper every test loads, the toolchain pin), and then once on the base too.
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
   - Depth comes from the lane (triage-rubric §3.3): QUICK for a pattern task and SLICE for a slice of a split task. Lenses come from review-rules §2.
   - The previous round head is the head hash in `findings-r<N-1>.md` §1 Diff. Round 1 has none.
   - Call one `reviewer` per lens, in parallel, in one message. Pass: base and head commit, the previous round head, kind, lens, depth, criteria source (`spec.md` §3, `repro.md` §5, the plan slice for a child task, or `task.md` for an S lane), rules file list, `docs.txt`, and the test command and the `targets:` entries (review-rules §3.1, tests that never run). Each writes `review/<lens>-rN.md`. S and M lanes: pass `model: sonnet` to the correctness and spec reviewers when the diff has 150 changed lines or fewer (`git diff --shortstat`).
   - Bug flow: the correctness reviewer also runs the sibling sweep from `repro.md` §7.
   - Verifier. IF every reviewer reports 0 candidates, THEN skip the verifier: write `findings-rN.md` yourself from the template with Result PASS and each lens's §3 Checked and clean. IF every candidate is LOW, THEN skip the verifier too and copy them to §5 Left open.
   - Otherwise call `verifier` with all raw findings files, the previous findings file and the previous round head. Output: `findings-rN.md`. Pass `model: sonnet` when there are 3 candidates or fewer and none is HIGH.
5. On FAIL, in this order:
   - 5.1 Fix chain. IF this round has an INTRODUCED finding and round N-1 had an INTRODUCED finding in the same area (findings §2 Area), THEN raise FIX-CHAIN. Do not patch again.
   - 5.1.1 Fix of a fix. IF 2 or more confirmed findings of this round are INTRODUCED by the last round's fixes, THEN the patches are not holding: raise FIX-CHAIN now, without waiting for a second such round. Its recommendation is the re-spec.
   - 5.2 Small fix. IF every confirmed finding is MEDIUM or LOW, each names a file already in its owner's §3 IN, none changes a criterion, and every one is `Fix kind: LOCAL` (findings template), THEN skip the architect: call `builder` in mode FIX with its order, `findings-rN.md`, fold fixes from config, and whether the PR is open. Prefer continuing the same builder agent. Then INTEGRATE with NARROW bars (3.9), then REVIEW again.
   - 5.2.1 State fixes. A finding with `Fix kind: STATE` changes who owns a state, which events change it, or when a run, write or session settles or ends. Its fix is a design change even when it fits one file: it goes to 5.3, so the architect writes the §8 lines before a builder touches the code. Bug flow: the architect amends `repro.md` §8 Fix direction.
   - 5.3 Otherwise call `architect` in AMEND mode on `spec.md` (feature) or `repro.md` (bug) with the findings, so it runs the interaction check, then on each owning order.
   - 5.4 Go back to BUILD for those orders only; the builder builds from the amended order. Then INTEGRATE with NARROW bars (3.9), then REVIEW again.
6. Hard stop. When `bump` exits 2, or Jorge chose to ship at LOOP-LIMIT or FIX-CHAIN:
   - 6.0 A fix after the PR is open is a normal commit, never a fixup: the branch is pushed and is not rewritten.
   - 6.1 Record each open confirmed finding as a known risk: one line in `spec.md` §1 (with a Changes line), and one line in `pr.md` §5 with its follow-up.
   - 6.2 Continue to QA. No escalation and no gate offers another fix round, GATE-PR included.
   - 6.3 Only Jorge's own words naming a higher limit (`/tempo:resume <task-id> review-limit <N>`) reopen review.

### 3.10.7 Findings after the PR is open
A review that arrives after GATE-PR (an automated reviewer on the PR or the issue, Jorge's PR comments) is a review round, not a side task.
1. Copy its findings into `findings-ext-N.md` from the findings template, Issued by: orchestrator, with each finding's owner, Area and Fix kind filled as the verifier would (read the code for each one). Keep the external ids.
2. Run `<state> bump <dir> review` and follow 3.10.2 for the limits. Then route the findings by 3.10.5, Fix kind and fix-of-fix rules included. Fixes are plain commits (3.10.6.0).
3. Review the fix with a round as 3.10.3 says (NARROW only when it qualifies), then QA the criteria the fixes touch, push, and give Jorge the PR link again.
4. A reply on the PR or the issue names the fix by commit hash and in words, never by task id, finding file or `.tempo/` path (1.6.1).

### 3.11 QA (feature M and L, all bugs)
- Call `qa` with the criteria source, the integration branch, the integrated head and bars from `integration.md`, whether this is a pattern task, the commands, `<run>`, `git.worktree_root`, the worktree setup command, `docs.txt` and the progress file `qa/progress.md`. Output: `qa-rN.md`. Tell Jorge first, as 2.6.1 says.
- IF FAIL, THEN amend the owning orders with the failing criterion and its evidence, and go back to BUILD. QA rounds stop at the config limit; then raise LOOP-LIMIT.
- S feature lane: skip QA. The builder's verification and the quick review stand in for it.

### 3.12 SHIP (all)
- Write `pr.md` from the template, using: Task Card §5, Spec §1 (or Repro §4 and §6, or the plan slice and plan §8 for a child task without a Spec), QA §2 (NIL when QA did not run), Findings §5, the integration diff stat.
- Assumptions SHALL appear at the top of the PR body, before the summary list.
- Autopilot decisions. IF `decisions.md` lists any decision, THEN copy each line to `pr.md` §8, and put them in the PR body right after the assumptions, under a heading such as "Decisions TEMPO made on autopilot", in `pr.language`. Jorge reviews them there. Otherwise §8 is NIL and the PR body has no such heading.
- `pr.md` is the internal record. Its §7 (artifact path) never goes into the PR body. The PR body is written from it in `pr.language`, following the repo's PR template (`pr.body_template`, else `.github/pull_request_template.md` if present). Assumptions stay at the top.
- PR title: `pr_title` from `<cfg> names` (1.7) with `{type}`, `{scope}` and `{summary}` filled, in `pr.language`. Check the repo's CI files for a title rule and follow it.
- Outward text (1.6.1). Before you push and before `gh pr create`, `gh pr edit`, `gh issue create`, `gh issue comment` or any tracker write, check the title, body and comment text and `git log --format=%B <base>..<task branch>` for the local task id, `WO-`/`ESC-` references and `.tempo/` paths. Rewrite the text; for a commit, reword it only while the branch is unpushed (FOLD runs before the first push).
- Fold fixes. IF `git.fold_fixes` is true and `git log --format=%s <base>..<task branch>` lists a subject starting `fixup!`, THEN call `integrator` in mode FOLD with the base commit and the typecheck, build and lint commands. On `FOLD: DONE`, run `<state> log <dir> SHIP integration.md PASS` and use the new head. On `FOLD: SKIPPED`, ship the branch as it is and add one line to `pr.md` §5 with the reason. Fold only before the first push; never rewrite a pushed branch.
- Task branch name. IF the task branch starts with `tempo/` (a task started before 0.14.0), THEN before the first push run `names` again with `--type`, `--ticket` and `--slug` (no `--branch`), `git branch -m <old> <new>`, and `<state> set <dir> --task-branch <new>`. IF the old name is already on a remote, THEN keep pushing it there (renaming would orphan the PR) and tell Jorge once in the GATE-PR message.
- Push the task branch and open a pull request against `pr.base`. Push nothing else: work-order and repro branches stay local (1.7.2). Draft when `pr.draft` is true. IF `pr.tool` is `none`, THEN push nothing and give Jorge the exact commands.
- IF pushing or `gh` fails, THEN stop, keep the branch local, and give Jorge the exact commands.
- Teardown first (section 10): `<procs> teardown --task <dir>`, so nothing still runs inside a worktree you remove.
- Remove the task's worktrees: run the lines `<cfg> teardown --worktree <path>` prints for each, then `git worktree remove`.
- IF `git.delete_merged_local_branches` is true, THEN run `<br> prune --repo <repo> --task-branch <task branch> --base-branch <git.base_branch> --glob "<git.work_order_branch with {branch} and {name} filled and {nn} as *>" --branch <repro branch>` (with the work-order and repro names as the state recorded them), adding `--from <FROM hash>` when FOLD ran. Never use `git branch -d` for this: it compares with the base branch, which never has these commits, and always refuses. The script deletes a branch only when the task branch holds its work (merged, same patches, or folded) and keeps the task branch, the base branch, any branch checked out, pushed or tracking a remote, and any branch with commits the task branch lacks. Report the KEPT lines to Jorge in the GATE-PR message only when one says commits are missing; that is work that did not ship.
- Raise GATE-PR: give Jorge the PR link and a 3-line summary. On autopilot, add one line: "<n> decisions made on autopilot, listed in the PR body." Jorge merges. TEMPO never merges.
- `<state> set <dir> --pr <url> --stage DONE`. IF the task has a parent, THEN run `<state> tracker <parent dir>`.

### 3.13 PLAN-ONLY stop (single repo)
- In PLAN-ONLY mode, run the route up to and including HANDOFF, then stop. Do not create work-order worktrees or branches, and do not BUILD.
- The bug route keeps REPRODUCE and ROOT-CAUSE: they commit only a test, on the repro branch.
- Write `plan.md` from the template, SCOPE: REPO. One slice per Work Order. Each Work Order's DEPENDS ON becomes a blocks-start edge. Open decisions come from Spec §1 (or Repro §6). Check it.
- `<state> log <dir> HANDOFF plan.md PASS`, then `<state> set <dir> --stage PLANNED --next "Run BUILD wave 1 (resume with build)"`, then raise GATE-PLAN.

### 3.14 Resume from PLANNED
- `/tempo:resume <task-id> build` starts here.
- Fetch the base branch. IF its head differs from the base commit in `state.md` §1 Base branch, THEN call `reviewer` with lens SPEC-PRECHECK on `spec.md` (or `repro.md`) against the new head. IF it has candidate findings, THEN call `architect` in AMEND mode, then HANDOFF again. Record the new base with `<state> set <dir> --base-commit <hash>`.
- `<state> set <dir> --mode FULL --stage BUILD`, then continue at 3.8.

## 4 Gates and escalations

4.1 The only moments to stop for Jorge (on autopilot, only those 4.5.1 keeps):

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
| FIX-CHAIN | two rounds in a row each have a finding introduced by the last fix, in the same area; or one round has 2 or more findings introduced by the last fix (3.10.5.1.1) | the chain of findings, and the options: (a) re-spec that area: architect AMEND on Spec §8 for it, HANDOFF, BUILD, then a FULL round; (b) ship as known risks (3.10.6); (c) revert the last fix and ship its finding as a known risk |
| HARD-TO-UNDO | new dependency, migration on real data, secrets, deploys, force-push, deleting branches | the action and its effect |
| MISSING-SOURCE | a source of truth the request or ticket names (1.3.3, 2.4) cannot be opened, and the work depends on it | what is missing, where it is named, which items depend on it, what was tried; options: (a) Jorge shares it, (b) Jorge names the stand-in per item, (c) drop those items from scope |

4.2 To raise one:
1. Write `esc-N.md` from the template. It SHALL include a recommended option.
1.1 LOOP-LIMIT and FIX-CHAIN: "the fix is small" is not a reason to recommend another round. Each of the last fix rounds was small too. Recommend re-spec when findings were introduced by fixes; otherwise recommend shipping known risks unless a HIGH finding is open.
1.1.1 MISSING-SOURCE: recommend (a). A stand-in TEMPO picked (an older version, another brand's asset, a drawing of its own) is never the recommendation.
1.2 GATE-PR: IF review has reached the hard stop, THEN the options do not include a fix round. A fix after the PR is open is a review round (3.10.1).
2. Run `<state> wait <dir> esc-N.md`. It stops the task's services (section 10): Jorge may answer hours later, and an emulator or a server must not run while the question waits. Start them again when the task continues.
3. Send Jorge one message: the question, the options, the recommendation, and "Reply yes to accept, or /tempo:resume <task-id> <answer> later."
4. End your turn. Do not continue other stages of this task while waiting, except read-only work.
4.3 On Jorge's answer, record it in `esc-N.md` §6 Answer, run `<state> wait <dir> --clear` and continue from `state.md` §7 Next action.
4.4 GATE-PLAN needs no `esc-N.md`: `plan.md` is the question. Run `<state> wait <dir> plan.md`. IF Jorge answers open decisions, THEN call `architect` in AMEND mode on `plan.md` (and `spec.md`) first.

### 4.5 Autopilot

When autopilot is ON (1.0.2, or `state.json` `autopilot` on resume), TEMPO answers its own questions with its own recommendation and stops only where Jorge's input is needed.

4.5.1 These still stop, exactly as 4.2 says:

| Kind | Why it still needs Jorge |
|---|---|
| GATE-CLARIFY, only for a question marked NEEDS-JORGE | the Outcome is missing, no option can be found in the code, or the only options are stand-ins for a missing source: there is nothing to recommend from |
| NO-REPRO | the next step needs details only Jorge or the user has |
| BEHAVIOUR-CHANGE | it changes what users get; that is Jorge's call |
| OUT-OF-ORDER-DECISION | it changes the goal |
| HARD-TO-UNDO | a new dependency, a migration on real data, secrets, deploys, force-push, deleting branches |
| MISSING-SOURCE | only Jorge has the source; a stand-in builds something other than what it says, and nothing in the code can tell |
| FIX-CHAIN, the second one in a task | the first re-spec did not hold; another automatic loop would hide that |
| Any option without a recommendation | an escalation, Spec §1 or `plan.md` open decision that names no recommended option |
| GATE-PR | the end of the run, not a question: Jorge reviews the decisions and merges |

4.5.1.1 A stand-in is not a recommendation. "An option exists" is not enough to accept a stop. IF the only options replace something Jorge, the ticket or a linked doc named as the source (an asset, a design or its version, copy text, a linked ticket's content, a product choice the ticket leaves to that source), THEN it is MISSING-SOURCE or NEEDS-JORGE, not a decision. Never record one with `<state> decide`: the script refuses the kinds in 4.5.1 and questions that read like a missing source.

4.5.2 These no longer stop. Accept the recommendation, record it (4.5.3) and continue at once:

| Kind | What autopilot does |
|---|---|
| GATE-CLARIFY, questions not marked NEEDS-JORGE | take each question's recommended option; call `triage` to amend `task.md` with it as an assumption |
| GATE-SPEC | approve the Spec; each open decision in §1 takes its recommended option. Call `architect` in AMEND mode only when a decision's recommendation is not already what the Spec says |
| GATE-PLAN, FULL mode (workspace tasks) | approve the plan; each open decision takes its recommendation, as GATE-SPEC |
| LOOP-LIMIT | take the option 4.2 step 1.1 recommends |
| FIX-CHAIN, the first one in a task | take the option 4.2 step 1.1 recommends |
| The small asks in 1.4 and 3.8 step 2 | do the recommended thing and record it |

4.5.3 Record every accepted stop. For an escalation, write `esc-N.md` as 4.2 step 1 says, then fill §6 Answer with "Autopilot: accepted (<letter>), <date>" instead of waiting. Then run `<state> decide <dir> <KIND> --question "<the question>" --choice "<the option taken>" --why "<the recommendation's reason>" --from <esc-N.md, spec.md §1 or plan.md>`. One `decide` per open decision. It writes `decisions.md`, which SHIP copies into the PR body (3.12). Do not run `<state> wait` for an accepted stop.
4.5.4 Progress stays one line per milestone (2.6). Do not message Jorge about an accepted stop. The GATE-PR message counts them.
4.5.5 PLAN-ONLY mode still ends at GATE-PLAN: the plan is the deliverable. Autopilot stays recorded in the state, so `/tempo:resume <task-id> build` continues on autopilot and accepts the plan's recommendations there.
4.5.6 Child tasks and split slices (sections 6 and 9) inherit the parent's autopilot: pass `--autopilot` to their `init`.
4.5.6.1 An accepted stop does not run `<state> wait`, so it tears nothing down.
4.5.7 Autopilot never widens what TEMPO may do. 5.6 holds: never merge, never push to the base branch, never force-push.

## 5 Rules for the orchestrator

5.1 Give each agent only the files its stage reads (see the index in the artifact-templates skill). Do not paste conversation history into an agent prompt.
5.2 Every agent prompt SHALL state: task ID, mode or lens, the absolute path of each input, the absolute path of each output, the template path, and the checker command.
5.2.1 Agents that run code also get: the command lines from §1.8, the run script `<run>` (0.11, with `--task`), the process script `<procs>` with the task folder (0.12), the branch names from §1.7, and the commit rules (`git.commit.message`, `git.commit.language`, `git.commit.extra_args`). Builders get the test-one, build or typecheck and lint commands, not the full test command: the whole suite is the integrator's and QA's.
5.2.2 Every output path SHALL be the final path in `.tempo/<task-id>/`. No agent writes an artifact to a temp folder first.
5.3 Run independent agents in parallel, in one message.
5.4 Do not write production code yourself. Builders write code. You MAY fix a document's structure (§2.2).
5.5 Do not skip a stage the route lists, except the skips this skill names (lane, re-size, verifier with no candidates). To skip any other, raise an escalation.
5.6 Never merge the PR. Never push to the base branch. Never force-push. Never push a `tempo/` branch (1.7.2).
5.7 Keep Jorge's messages short: one line per milestone (2.6), one message per gate. On autopilot, no message for an accepted stop (4.5.4).
5.8 Models. The frontmatter model is the default for L. Pass the `model` override this skill names for S and M stages. Never override a model upward.

## 6 Workspace tasks (several repos)

6.1 A workspace task starts when the working directory is a workspace root (1.1.2). Its folder is `<workspace>/.tempo/<task-id>/`. Run 1.0, 1.2 and 1.3 with `--repo <workspace>`, and 1.6 for the ID.
6.2 `<state> init <workspace>/.tempo/<task-id> --task <task-id> --flow WORKSPACE --mode <mode> --title "<request>" --base-branch <defaults.git.base_branch> --base-commit NIL --qa-limit <limits.qa_rounds>`, plus `--autopilot` when ON.
6.3 TRIAGE: call `triage` with `Scope: WORKSPACE` and the output of `<cfg> repos`. Raise GATE-CLARIFY as in 3.1.
6.4 EXPLORE: run `<cfg> docs --repo <path>` for each repo the Task Card names and save the lists under `<workspace>/.tempo/<task-id>/docs/<repo>.txt`. Call one `scout` with lens CROSS-REPO per repo, with its docs list, in parallel, at most `limits.max_parallel_builders` at a time. Merge their replies into `context.md`, one block of §2 lines per repo, copy every CONTRACTS line into §3 and every BEHAVIOUR line into §8. The architect copies the §8 lines each slice consumes into the slice, so the child's scouts and spec start from them.
6.5 PLAN: call `architect` in mode PLAN. Output: `plan.md`. Check it. Each slice SHALL carry its criteria text, production files, test files, pattern and test command (template §3), because the child builds from it. Then raise GATE-PLAN, always. In PLAN-ONLY mode, `<state> set <dir> --stage PLANNED` first and stop at the gate.
6.6 REPOS: run `<state> set <dir> --stage REPOS` first, so the children's time is logged as REPOS. For each slice, in §6 ORDER:
  - 6.6.1 Claim and register it: `<state> claim <repo>/.tempo --id <task-id>`. IF it prints `EXISTS` and that folder is not this task's child (its `state.json` names another parent, or a repo task started it), THEN run `<state> claim <repo>/.tempo` and use the `T-NNN` it prints as the child's folder. Then `<state> child <dir> <repo> --folder <repo>/.tempo/<child id>`.
  - 6.6.2 A slice starts only when every blocks-start source has passed INTEGRATE. Slices whose sources are all blocks-merge or blocks-validation start at once.
  - 6.6.3 Before it builds, run each blocks-start source's `build` command on that source's task branch, so local artifacts (installed libraries, generated clients) match it.
  - 6.6.4 Run sections 1.2 to 1.9 for it from the repo root, as a child task, with the folder 6.6.1 claimed (skip 1.6.0); `init` gets `--parent`. Then:
    - 6.6.4.1 Slice size S or M with no open decision in plan §7 for it: no child TRIAGE, EXPLORE or SPEC. Run `<state> set <child dir> --lane <slice size>`, then HANDOFF from the plan slice and the parent `context.md` block for this repo (3.7), then BUILD to SHIP. The criteria source for review and QA is the plan slice. QA runs only for M.
    - 6.6.4.2 Slice size L, or an open decision: run the full route from TRIAGE. The request is the slice line; triage also gets the parent `plan.md` and `task.md`.
    - 6.6.4.3 Do not re-size a slice in the child. The plan sized it with the cross-repo view, and Jorge approved the plan.
  - 6.6.5 Child gates (GATE-SPEC on L lanes, escalations) still stop for Jorge, unless autopilot accepts them (4.5).
  - 6.6.6 After every child stage, run `<state> tracker <dir>`. `tracker.md` is the cross-repo status; never write a tracker by hand.
  - 6.6.7 At the child's SHIP, the PR body lists the PR links of its blocks-merge sources (from `tracker.md`) under a "Depends on" line, in `pr.language`. Record the link with `<state> set <child dir> --pr <url>`. Children run in parallel, so a source's PR MAY open after this one: when it does, add its link to this PR body with `gh pr edit`.
  - 6.6.8 Run children in parallel, up to `limits.max_parallel_builders` at a time, as 6.6.2 allows. Drive each child's stages from this session; start the agents of different children in the same message when they are ready together. IF a child needs a change in another child's repo, THEN raise OUT-OF-ORDER-DECISION: amend that child's plan slice, or add a slice.
6.7 JOINT-QA: when every child has an open PR, run `<state> log <dir> REPOS tracker.md PASS` and `<state> set <dir> --stage JOINT-QA`, then call `qa` in mode JOINT with `plan.md`, every repo's task branch and build command, and the workspace config's `validation.steps`. Output: `<workspace>/.tempo/<task-id>/qa-joint-rN.md`. IF FAIL, THEN resume the owning child at BUILD with the failing criterion added to its Work Order. Rounds stop at `limits.qa_rounds`; then LOOP-LIMIT.
6.8 Ship: raise GATE-PR with `tracker.md` (every PR link) and the joint QA evidence. `<state> set <dir> --stage DONE`.

## 7 After a restart

7.1 A restart ends background agents. On resume, and whenever a notification says agents did not finish before the previous session ended, read `state.md` §8 Agents in flight.
7.2 For each agent listed: send it a message by its agent ID: "The session restarted. Continue from where you stopped and finish with the reply your prompt asks for. Write <output path>."
7.3 IF the agent cannot be reached, THEN start a new agent with the saved prompt file, and replace the entry with `<state> agent ... start`.
7.4 Do this without asking Jorge. Tell Jorge in one line which agents you restarted.

## 8 Project docs

8.1 `docs.txt` lists the project's own documentation (config `docs:`), one absolute path per line, index files first. It is how agents learn the project before they search the code.
8.2 Scouts read the index files and the docs whose names match their lens before they search. A scout cites a doc line instead of re-deriving a fact the doc already states.
8.3 The architect follows the docs' architecture rules and decisions (ADRs) in Spec §4 and cites them in §6 RULES CHECK.
8.4 Reviewers treat docs that state rules (conventions, contributing guides, ADRs, design systems) as rules files when `docs.rules` is true (review-rules §1.6).
8.5 QA reads a doc about running or testing the app (a QA harness, a runbook) before it picks its methods.
8.6 An agent reads only the docs that bear on its task. The list is a map, not a reading assignment.

## 9 Split tasks (one repo, many orders)

9.1 A task splits when the HANDOFF architect replies `SPLIT`: it would issue more than `limits.split_orders` orders, or the Spec has more than `limits.split_criteria` criteria. 0 turns a trigger off. GATE-SPEC has already passed, so a split raises no new gate.
9.2 The architect writes `plan.md` (Scope: REPO): one slice per group of 1 to 3 orders, chained blocks-start in commit order, each slice with its criteria tags from Spec §3. It writes each slice's orders as `.tempo/<task-id>-s<n>/wo-NN.md`.
9.2.1 After the split, run `<state> log <dir> HANDOFF plan.md PASS`, then `<state> set <dir> --stage SLICES --next "Slices S-1 to S-<n>"`. The parent stays in SLICES while the slices run, so its stage log shows HANDOFF's own time and the slices' time apart. When the last slice passes review, run `<state> log <dir> SLICES tracker.md PASS` and `<state> set <dir> --stage INTEGRATE`.
9.3 For each slice, in order: `<state> child <dir> S-<n> --folder .tempo/<task-id>-s<n>`, then 1.7 with the parent's type, ticket and slug plus `--suffix s<n>` (branch `feat/AV-1-s2`; commits keep the parent's ticket), then 1.9 with `--parent`, then `<state> set <child dir> --lane <slice size> --stage BUILD`. The child's route is BUILD, INTEGRATE, REVIEW. Its criteria source is the slice's tags in Spec §3. It has no QA and no PR. A slice's integrate always runs NARROW bars (3.9). Its review is depth SLICE: the order check and the correctness lens. The other lenses run once, at the parent (9.6).
9.4 Slice 1 starts from the base commit. Slice n starts from slice n-1's task branch as soon as slice n-1 has integrated, so slice n builds while slice n-1 is in review. IF slice n-1's review changes its branch, THEN rebase slice n onto the new head before slice n integrates; a conflict goes back to slice n's builder.
9.4.1 Base drift (3.9) is checked before each slice's integrate. A REBASE there moves the slice's branch, which holds every earlier slice, onto the new base; record the new base in the parent and in the slice (`<state> set --base-commit`). Later slices start from the rebased branch.
9.5 Run `<state> tracker <dir>` after every child stage.
9.6 When the last slice passes review, fast-forward the parent task branch to it. Check base drift (3.9) once more. Call the integrator once on the parent with the bars 3.9 chooses, on the whole task diff. Then run one REVIEW round (3.10) over the whole diff at the task's lane depth. Its fixes go to the owning order's builder on the parent branch, then NARROW bars. Run QA (3.11) against all of Spec §3, then SHIP (3.12) one PR whose commits keep the slice order. Fixups from every slice fold at that SHIP.

## 10 Teardown

10.1 A task cleans up after itself. Every process it started for building or testing stops when the task stops, and nothing it did not start is touched. A leftover emulator, Java stack and two watchers once held 13 GB on Jorge's Mac for up to 42 hours.
10.2 What TEMPO started is known, not guessed. `<run>` and `<procs> start` mark each process with the task (`TEMPO_TAG`) and the session (`TEMPO_OWNER`), and every child inherits the marks, even one a helper script starts with nohup. `<procs> start` also records each service in `procs.json`. Teardown stops exactly the marked processes and the ledger's process groups, and runs each ledger `--stop` command (a `docker compose down`, an `adb emu kill`).
10.3 When it runs. `<state>` runs it, so no path forgets it:
| Event | What stops |
|---|---|
| `<state> wait <dir> <file>` (a gate or escalation waits on Jorge) | services only (`--services-only`); runs in flight finish on their own |
| `<state> set <dir> --stage DONE` or `--status DONE` (shipped, or a plan delivered and closed) | everything the task started, children and slices included |
| `<state> set <dir> --status FAILED` (the run cannot go on) | everything |
| `<state> set <dir> --status ABORTED` (Jorge stops or drops the task) | everything |
| The Claude Code session ends (SessionEnd hook) | everything this session's tasks started |
10.4 Abort and failure. IF Jorge says to stop, cancel or drop a task, THEN run `<state> set <dir> --status ABORTED --next "Aborted by Jorge"`. IF the run ends on an error you cannot get past, THEN `<state> set <dir> --status FAILED --next "<what failed>"` before you tell Jorge. Resume clears either with `set --status RUNNING`.
10.5 SHIP calls `<procs> teardown --task <dir>` before it removes worktrees (3.12).
10.6 Report. Teardown prints one STOPPED line per process and a RAN line per stop command, and appends them to `procs.log`. Do not relay them to Jorge. Tell Jorge only a FAILED line (a process that would not stop), with `/tempo:sweep`.
10.7 Agents never detach. In a TEMPO session the plugin's spawn guard denies `nohup`, `setsid`, `disown`, a trailing `&` and `run_in_background` in Bash, and names the `<procs> start` line instead. Prompts SHALL NOT tell an agent to background anything.
10.8 Shared stacks. A stack that was already running when the task started (Jorge's own dev stack) is not the task's: use it, do not `<procs> adopt` it, and do not stop it. Adopt only what this task launched another way.
10.9 Leftovers from before 0.17.0, a crash, or a session killed without its hook: `/tempo:sweep` lists them; Jorge decides.

