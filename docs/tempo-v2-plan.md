# TEMPO v2: plan for 0.24.0 to 0.28.0

Status on 2026-11-11: 0.22.0 (dashboard, event log, `tempo_run.py stop`, kill-by-name guard) and 0.23.0 (test load and
safety) are built. Everything below 0.23.0 in this file is a plan: nothing in it is written yet. Jorge stopped the build
at 0.23.0; pick a version up from here when he asks.

## Where this comes from

An analysis of three Herdr story runs on pod1um (POD-10, POD-11, POD-12: 116 subtask PRs, all on TEMPO 0.21.0) and 12
tasks from a second account, with every time claim re-derived by two checkers. Three designs were written from it
(minimal-diff, script-first, story-first), scored by two judges, and merged into this plan. The minimal-diff design won.

What the runs showed:
- A top-tier session steering Sonnet agents does not make one task faster. Median task: 66 min with an Opus main loop
  (POD-10), 28 min and 60+ min with Sonnet (POD-11, POD-12). 83 to 90% of a run is waiting on agents, which wait on tests.
- The top model changed the outcome at two points only: the spec gate (37 of 67 answers changed something) and the
  read of the diff before merge (14 of about 116 PRs sent back after TEMPO's review and QA had passed them).
- The large losses are in test execution on one shared Mac and in story-level stalls: whole suites inside critical
  tasks (833 INTEGRATE minutes on 3 tasks, about 5 h of one story), a heavy-slot queue of 175 to 414 min in one story
  because main sessions wrote `--heavy` on every command, one modal question that froze a story for 114 min, and a
  serial end of story of 45 to 60 min.
- On default config, the Opus pins cost 7 to 34 min per lane-L task and review rounds that chase MEDIUM and LOW
  findings about 15 min per task.
- Inside one quiet all-Sonnet run there is no big bottleneck; the flow changes there are estimates of a few minutes.
- Not proven, so not built on: that more parallelism helps on this Mac. POD-12 stayed 2.3 times slower than POD-11
  after the full Chrome suite was banned and nobody found why. No cap is raised.

## Decisions Jorge took (2026-11-11)

- D1. A single `/tempo:feature` or `/tempo:bug` run is one session that drives Sonnet stage agents directly. A script
  runs the stage machine: prompts, test commands, `--heavy`, state, events. No runner session per task.
- D2. One explicit top-tier read of the final diff before the PR, as its own agent call with a model from config.
- D3. Model roles live in config; Sonnet by default; the frontmatter Opus pins go.
- D4. Whole test suites run once on the integration branch, not inside a subtask. A lone critical task keeps its
  single whole-suite run at its final integrate (`gates.full_bars: verify`, added in 0.23.0, is opt-in). Review fixes
  HIGH and above by default; the rest goes to a follow-ups section of the PR body.
- D5. A question for Jorge never blocks other work: it goes to a queue the dashboard shows.
- D6. Story runs move into TEMPO as `/tempo:story`, with Herdr optional.
- D7. The dashboard is local and read-only.
- Order: the runner-session spike (0.28.0 below) comes before the one-session story (0.27.0 below). A subtask is about
  18 agent calls, and the story orchestrators already needed manual compaction while only answering gates and merging,
  so one session driving a 40-subtask story is the riskier bet. The version numbers below keep the plan's original
  order; swap the two when building.

## The plan in one paragraph

The plan starts from the minimal-diff design and has six small versions. 0.23.0: test load and safety, no flow change (heavy slot decided from the command, an opt-in value that defers whole suites, owner fix, state lock, run records). 0.24.0: Sonnet for every stage agent from a `models` map, review fixes HIGH only, and one Opus read of the final diff that the push hook enforces. 0.25.0: the script renders prompts and reads results (`call`, `done`), and questions go to a queue. 0.26.0: the script sequences the stages (`start`, `next`, `ship`). 0.27.0: /tempo:story in one session, which works in plain Claude Code and spawns nothing. 0.28.0: runner sessions (headless or Herdr) after a spike. Three keys are added to the config and no default changes for whole suites: a lone critical task keeps its one full run at its final integrate. Not in the plan, offered to you as a separate choice: a top-tier read of the spec's open decisions on autopilot.

## Versions


### 0.23.0: Test load and safety (BUILT)

**Goal.** Take the two verified story losses that need no flow change, close the code hazards, and record how every run ends. No default changes.

**Saves.** Per baseline, not to be added. Heavy slot queue on a loaded story (POD-12): 175 to 414 min, 5 to 11 min per task (verify-evidence T-4); 0 on POD-11, which had no slot wait. Part of it stays until 0.25.0 for a command configured as `build` when a main session still writes `--heavy`. Whole VM suite inside critical subtasks, only where the story checkout sets `verify`: about 23 min per task as a mean, median 0, 3 of 36 tasks, about 5 h of one story as a counterfactual (verify-evidence rank 1; the window also holds the 04:06 exit, and the brief already bans the full Chrome suite). The other items save 0 minutes.

**Protections.** 2026-10-30 leftovers: SessionEnd still stops everything the session started; only how the owner is found changes (tempo_procs.py), and guard_spawn calls the same function. Heavy slots still guard whole suites, now decided in tempo_run.py. Critical means FULL bars: unchanged under the default; under `verify` it is deferred and said in the PR body. pod1um #64 and T-008 to T-014 (scoped tests and targets, baselines): untouched. Kill by name: the guard and `<run> stop`, with the KILLED line as the fallback when something outside TEMPO kills a run.

**Risks.** Whole-package runs take no slot under this rule, as designed in 0.21.0; the accidental throttle of "--heavy on everything" goes away, and many such runs at once may load the Mac. The run-end events exist to measure that on the first story. A whole suite spelled differently from the config (an alias) is not recognised as heavy. With `verify` a critical subtask's regression is found on the story branch, not in the task. The owner hazard was read from code and never reproduced.

**Tests.** test_run: matcher table with pod1um's strings: `cd flutter-client && melos run test` heavy; the same with an `export ...;` prefix and with `2>&1 | tail -40` heavy; `melos run test:web:full` heavy; `cd <app> && flutter test a_test.dart --heavy` light; the scoped Chrome line follows the flag; lint light with the flag; `test_one: null` with `npm test` heavy and `npx jest a.test.ts` following the flag; no `--task` honours the flag; exit -9 prints KILLED and writes the event. test_procs: a fake process table where a Claude ancestor beats a foreign TEMPO_OWNER and no ancestor falls back to it; reap_job leaves another owner's rows. test_state: two concurrent `wo` updates both persist; QA counter and limit line; SHIP entry on `--pr`; a 0.21.0 state.json accepts every old command. Config: a 0.21.0 config passes `check`; `bars --critical` prints FULL under on_demand and NARROW with DEFERRED under verify. By hand, once: in a scratch task have a builder subagent try `nohup sleep 1 &` and a `pkill`, to confirm the hooks see subagent Bash calls.

**Changes.**
- `hooks/ (the kill guard) and skills/orchestrator/scripts/tempo_run.py `stop <ID>``: Planned outside this plan; they ship in this version at the latest. Added here: the guard also matches `kill $(pgrep ...)`, `kill `pgrep ...`` and `pgrep ... | xargs kill`; its deny reason names `<run> stop <ID>` and `<procs> stop`.
- `skills/orchestrator/scripts/tempo_run.py`: main(): after parsing, when `task` is set, read the config with `tempo_procs.cfg(<task dir>/../.., 'resolve', '--format', 'json')` and set `opts['heavy']` with a new function `decide_heavy(cmd, flag, cfg)` (the three rules in script_cli); on any error keep `a.heavy`. Add `task` to `opts`. worker(): turn a negative exit into 128+n; when the exit is 137 or 143 put the `KILLED:` line first in the summary; after result.txt, call `tempo_procs.event(task, ev='run-end', ...)` with exit, seconds, waited, `os.getloadavg()[0]`, killed and the leftovers count. wait(), dead-worker path (lines 188-190): print the same `KILLED:` line and append the event.
- `skills/orchestrator/scripts/tempo_procs.py`: find_owner(): walk the ancestors first and return the nearest Claude process; read `TEMPO_OWNER` only when there is none (a detached worker). New `cfg(repo, *args)`: run tempo_config.py with `uv run --quiet` when uv is on PATH, else python3, return stdout. session_end(): put `owner` in the reap job. reap_job(): mark as stopped only the ledger rows whose `owner` is that owner (today it marks every row of every folder the session registered).
- `skills/orchestrator/scripts/tempo_state.py`: main(): take `fcntl.flock` on `<dir>/.state.lock` before `load` and release it right after `save` and `emit`, before the teardown at lines 469-472. One command writes one state.json; data from other folders is read without a lock. `log`: an artifact `qa-rN.md` raises the QA counter to N and prints the `LIMIT:` or `HARD STOP:` line `bump` prints. `set --pr`: append a SHIP log entry when the last entry is not SHIP. Status DONE: clear `next`.
- `skills/config/scripts/tempo_config.py and skills/config/schema/tempo-config.schema.json`: Schema: add `verify` to the `gates.full_bars` enum and its description. `bars`: a first branch for `verify` that prints NARROW plus the DEFERRED line. `targets`: flag `--scoped-only`; where the code prints `full` for a path-matched target, print the `# DEFERRED whole suite` line instead. defaults.yaml: only the comment on `full_bars`.
- `skills/orchestrator/SKILL.md`: 0.11: replace the `--heavy` sentence with "the script decides the slot for the commands the config knows". 3.9 Bars: one sentence, on a DEFERRED line pass `targets --critical --scoped-only` and write the full-suite line in pr.md. Section 10: one line, cancel a run with `<run> stop <ID>`, never by name. Net zero lines.
- `agents/builder.md, integrator.md, qa.md`: Running commands, one bullet each: a summary that starts `KILLED:` is not a failure; run the command again once, and report BLOCKED if it is killed again. The `--heavy` wording stays: it is still honoured for target lines and app builds.
- `tests/test_procs.py, test_run.py, test_state.py (new, unittest, same style as test_dash.py)`: See tests.
- `pod1um-workspace/.claude/skills/pod-story-run/SKILL.md (project file, Jorge's edit, optional)`: 3.2: add `gates: {full_bars: verify}` to the story checkout's untracked config. Optional: move `melos run analyze` from `commands.build` to `commands.typecheck` in pod1um's config (the key exists in 0.21.0), so a hand-written `--heavy` no longer queues it.

**As built (differs from the text above).** Read this before trusting a line of the 0.23.0 section.
- Heavy slot: the whole-suite rule looks at every `&&` part of the line, not only the last, and a leading `fvm` or `fvm exec` is dropped on both sides (agents wrote `fvm flutter test` in about two of three prompts). The `run` event logs the decided value, not the flag.
- `KILLED:` prints only on exit 137 or 143, not on every signal: a segfault is a failure. `run-end` is written just before `result.txt`, and its load key is `load1`. The dead-worker path of `wait` also stops what is marked with that run, and writes `result.txt` so a second `wait` prints the same.
- QA: `log qa-rN.md FAIL` at or past the limit prints `LIMIT: qa rounds N of L; raise LOOP-LIMIT`, as SKILL 3.11 says. The planned "line `bump` prints" was `HARD STOP ... ship open findings as known risks`, one round late and also on a PASS.
- `verify`: the orchestrator adds `--scoped-only` to every targets call under `verify`, and `--critical` on a `DEFERRED:` line at the last integrate only. `tempo_config.py targets` itself does not read `gates.full_bars` (the architect's HANDOFF call needs the whole commands). The integrator is told a `# DEFERRED whole suite` line is not a command.
- Known gaps, not fixed:
  - The integrator has no BLOCKED reply and SKILL 3.9 has no branch for one, so two kills in a row most likely end as `RESULT: FAIL` and cost a rebuild and a review round. The builder's BLOCKED goes to the architect (3.8 step 7), who has nothing to amend.
  - A worker that crashes by itself (binary not on PATH with an argument list, cwd gone) is reported as `KILLED: signal unknown`; the cause is in `worker.err`.
  - The dead-worker cleanup finds the command only by its `TEMPO_RUN` mark, which macOS hides for system binaries (`xcodebuild`, `/usr/bin/git`); such a command keeps running while the agent starts it again.
  - The config read (up to 60 s, normally 0.1 s) runs before `--max` starts counting.
  - `test_one` with a folder as its argument (`flutter test test/`) is forced light.
  - A parent session's end no longer kills what a child session started; it relies on the child's own SessionEnd hook, which Claude Code runs on SIGTERM.
  - `SKILL.md` 154 still allows `targets --full` inside a task for a change to the target's own setup, also under `verify`.
  - Not done: the two-minute hand test of whether hooks see Bash calls inside subagents.

### 0.24.0: Models, fix severity, final read (planned)

**Goal.** D2, D3 and the review half of D4: Sonnet for every stage agent from config, review fixes HIGH only, and one top-tier read of the final diff that is enforced before the push in this same version.

**Saves.** Default-pin run (work account, any lone task without the story brief): 7 to 34 min per lane-L task, closer to 7 on ordinary tickets (verify-design rank 3: plan phase 44.2 min on POD-10 against 10.0 on POD-11, lane-confounded, a third of it advisor wait). HIGH-only on the same Opus-era baseline: about 10 to 15 min per task as a mean (verify-evidence rank 4); it comes from the same POD-10 runs and does not add to the models figure. Jorge's all-Sonnet story runs: 0 for both, the brief already forces them. Cost everywhere: the final read, about 4 to 5 min per task, partly beside QA (ESTIMATE from the 4.8 min Opus correctness review).

**Protections.** PR #203 (order check) and the spec pre-check: untouched, still HIGH and MEDIUM. Review limits, FIX-CHAIN and the hard stop (SKILL 3.10.6): untouched; a read that ran but did not pass ships at the hard stop with its items as known risks. tempo/ pushes (0.14.0): the same hook, the old check first. Never rewrite a pushed branch: fixes after the PR stay plain commits and each gets a read before its push, which also closes the case of a last fix shipped with no review (work account, a work-account task).

**Risks.** What all-Sonnet review lets through was never measured on the same diff; the final read is the backstop, and each final-read FAIL after a passing round is now a recorded miss to count. MEDIUM defects ship as follow-ups. The hook sees only pushes made through Claude's Bash and fails open. Until 0.25.0 the main session still passes the model by prose; the frontmatter (sonnet, and opus on final-read) is what holds when it forgets. A prompt line cannot guarantee the Opus read skips the user's advisor setting (about 134 s per call).

**Tests.** Schema: a 0.21.0 config passes; `models` and `fix_severity` accepted; an unknown models key fails. test_state: `log` of a final file stores head and tree; `cleared` for each case (no diff, covered PASS, covered FAIL with and without ship-risks, tree moved, clean merge, conflicted merge); `set --pr` refusal; a state without `final` is never refused. Hook test: push of a covered and of an uncovered task branch, of a branch no task owns, with `TEMPO_ALLOW_PUSH=1`, and the old tempo/ cases. One real lane-M task on a scratch repo.

**Changes.**
- `skills/config/schema/tempo-config.schema.json and defaults.yaml`: Add `$defs/models` (closed object, the keys in config_keys) and reference it from repoFile, repoEntry and the workspace file's `defaults`. Add `limits.fix_severity` (enum). defaults.yaml: `models: {default: sonnet, final_read: opus}` and `limits.fix_severity: HIGH`.
- `agents/architect.md, reviewer.md, verifier.md, investigator.md, reproducer.md`: Frontmatter `model: opus` becomes `model: sonnet`. The line stays, so no agent inherits the main session's model.
- `agents/final-read.md (new, about 25 lines)`: Frontmatter `model: opus`, tools Read, Grep, Glob, Bash, Write. Inputs: base and head (or the head it read last and the new head), the criteria source, the last findings file, the output path `review/final-<n>.md`, the findings template, the checker. It reads the whole diff against the criteria, reports HIGH findings only, writes the file in the Findings layout (Issued by: final-read; section 1 Diff holds the head; section 6 Result PASS or FAIL), edits nothing, and ends with "Do not call the advisor tool".
- `agents/verifier.md and skills/artifact-templates/templates/findings.md`: verifier Inputs: the fix severity. Steps 5 and 8 and the template's Result line: findings below the fix severity go to section 5 Left open; PASS means none at or above it remains outside section 5.
- `skills/orchestrator/scripts/tempo_state.py`: `init --final-read MODEL` stores `final: {required: true}`. `log`: an artifact named `final-<n>.md` is read for its Result and head; store `final.head`, `final.tree` (`git -C <dir> rev-parse <head>^{tree}`) and `final.result`; exit 1 when the Result argument disagrees with the file. `set --ship-risks on|off`; `bump` sets it when it exits 2. New module-level function `cleared(dir, state, branch)`: true when the final read is not required, or the branch has no diff against the base commit, or the branch's tree equals `final.tree` and the result is PASS or ship-risks is on, or the head is a merge with no conflict resolution (`git show --cc` empty) whose first parent's tree is covered and whose second parent is on the PR base. `set --pr` exits 1 when it is false.
- `hooks/guard_push.py`: bad_pushes(): also return every destination branch. main(): for each one, look for `<main checkout>/.tempo/*/state.json` whose `task_branch` is that branch; when `tempo_state.cleared` is false and the command lacks `TEMPO_ALLOW_PUSH=1`, deny with the reason and the final-read step. It keys on the tree, so FOLD does not undo a read. A task without `final.required` (every 0.21.0 folder) is not checked. Errors still let the command through.
- `skills/orchestrator/SKILL.md`: 5.8 becomes one line: pass `models.<agent>`, else `models.default`, on every Agent call. Delete the model clauses in 3.6, 3.7, 3.8 step 6.2 and both in 3.10.4. 1.9: add `--final-read <models.final_read>`. 3.10.4: pass `limits.fix_severity` to the verifier. 3.10.5.2: delete "every confirmed finding is MEDIUM or LOW"; LOCAL, in the owner's IN and no criterion change remain. New 3.10.8 FINAL READ, 5 lines: when to call it, the `log` line, FAIL is a review round the verifier does not filter, call it again on the diff since its head after any later commit, `set --ship-risks on` at 3.10.6. 3.10.7: Jorge's own comments are fixed whatever their severity. 3.12: findings section 5 becomes the Follow-ups section of the PR body. Net zero or fewer lines.
- `skills/review-rules/SKILL.md, README.md`: review-rules 3.4: delete "Run it on sonnet". README: models, fix severity and the final read, and how to restore 0.21.0.
- `pod1um-workspace/.claude/skills/pod-story-run/scripts/brief.sh (project file, optional)`: Models line: add "except final-read". Without the edit the flow still works: the runner's final read runs on Sonnet and the Opus orchestrator's own diff read stays.

### 0.25.0: The script renders prompts and reads results; question queue (planned)

**Goal.** First half of D1 and all of D5 for a single task: `call` and `done` replace hand-written prompts and bookkeeping; a question blocks only what depends on it. The stage order stays in SKILL.md.

**Saves.** ESTIMATE: part of the about 3 min per task of bookkeeping (verify-design rank 5, ceiling 5.5). Not in minutes: no hand-written `--heavy` (151 of 619 prompt files, 35 of 38 POD-12 sessions) and no hand-written test command (`melos run test:web:full` written into the POD-177 and POD-197 integrator prompts after the script printed scoped lines). The rest of the 0.23.0 heavy saving lands here.

**Protections.** Heredoc prompts (0.7.0): the main session writes no prompt. pod1um #64: the prompt table gives builders no full test command, and `done` reports an order with a whole-suite line. T-007: the scope check runs in `done`; scout replies are still saved by the main session with one retry. PR #203: `done` prints the deviation tags and the order-check result. AV-6033: SKILL 1.3.3 stays; `decide` still refuses the stop kinds and missing sources; `--by supervisor` is refused for them. 2026-10-30: `wait` without `--blocks` still stops services at once. Question lines (0.17.2): the esc template and its question-line form are unchanged.

**Risks.** The readers depend on the templates' fixed lines; a miss is UNPARSED and costs a judgement turn, never a wrong PASS. Sessions running when the plugin updates keep the old text and the old commands, which all stay. Plugin versions are assumed to live in separate folders, so an old session keeps its old scripts; not verified.

**Tests.** test_flow: golden prompt files per table row (a builder prompt holds no full test command, no `--heavy`, no model name; a final-read prompt ends with the advisor line; every code-running prompt holds the stop line); each reader on a real artifact copied from a pod11, pod12 and work-account folder, and on a broken one (UNPARSED). test_state: `wait --blocks WO-02` leaves status RUNNING and stops nothing; old `wait` forms unchanged; `--by supervisor` refused for NO-REPRO; `done` exit 5 logs nothing. Hook: AskUserQuestion denied for the driver, allowed for a reader session and for a 0.21.0 folder.

**Changes.**
- `skills/orchestrator/scripts/tempo_flow.py (new module, no command line, about 350 lines)`: PROMPTS table (agent, mode or lens: inputs, output, template, flags, stage); `render(state, dir, cfg, agent, ...)` in the fixed layout of script_cli; readers, one per artifact, each keyed on the template's fixed line: task.md (Lane, Critical, section 6), spec.md (section 1 open decisions, section 8), wo-NN.md (header Depends on, section 3 IN, section 5), report-NN.md (Result, section 5 tags, section 6), integration.md and qa-rN.md (Result), raw findings (candidate headings and severity), findings (severity, Owner, Fix kind, INTRODUCED, Area, Result). A reader that finds nothing returns UNPARSED.
- `skills/orchestrator/scripts/tempo_state.py`: Subcommands `call` and `done` (script_cli). `call` emits the same event shape as `agent start` with id = label plus `model`; `done` emits `closed`. `done` runs check_doc, the reader, `log`, the counter bump with its limit check, the scope diff (`git diff --name-only <start>..<branch>` against IN) and the Verification whole-suite check. `wait`: flags `--blocks`, `--kind`, `--answer`, `--by`; a `questions` list in state (`file, kind, blocks, asked, answered, by`); `waiting` is the oldest open file. The teardown test at line 471 becomes `a.file and not a.clear and not a.blocks`. `init` writes `questions: []`. `log`, `bump` and `agent` refuse on a task with `driver` set.
- `hooks/guard_spawn.py and hooks.json`: hooks.json: a second PreToolUse entry with matcher `AskUserQuestion` that runs guard_spawn.py. guard_spawn.py: when the tool is AskUserQuestion and one of the session's open tasks has `driver` equal to this session's owner, deny with the reason: write the esc file, run `<state> wait <dir> esc-N.md --blocks ...`, show Jorge the question as text. A session that only reads a task (the Herdr orchestrator) is not its driver and is not denied.
- `skills/orchestrator/SKILL.md`: Delete 2.1, 2.5's log and bump rules, 2.7, 2.7.1, 5.1 to 5.2.2 and section 7's restart by agent id (one line stays: after a restart, `call` each agent in flight again). In section 3 each stage keeps its order and judgement and loses "what the agent gets": the bullet names `<state> call <dir> <agent> --mode ...`. 4.2 steps 2 and 4 and 4.3 become the queue: `wait --blocks`, go on with what is not blocked, `wait --clear --answer`. Keep every section number another file cites. About 376 to about 310 lines (ESTIMATE).
- `commands/resume.md`: Step 4.1: call the agents in flight again with `<state> call`. Step 5: record an answer with `wait --clear <file> --answer`; an answer already in esc section 6 is used.
- `skills/orchestrator/scripts/tempo_dash.py`: agents(): `x['model'] = e.get('model') or model(id)`, because a label is not an agent id. One line.
- `pod1um-workspace/.claude/skills/pod-story-run/scripts/brief.sh (project file, optional)`: Remove the Models line and "put this in the prompt of every agent". Nothing breaks if they stay: the script renders target lines from tempo_config.py, which never prints the full Chrome command for a task, and the model comes from the CALL line.

### 0.26.0: The script sequences the stages (planned)

**Goal.** D1 complete: `start`, `next` and `ship`. The two overlaps with a measured bound become table edges.

**Saves.** All ESTIMATES on a quiet 28 min run. Bookkeeping: the rest of about 3 min (verify-design rank 5). QA beside round-1 review: 1.4 min (rank 6, bound 44 min over 31 tasks). Order check off the wave's path: about 1 min per order (verdict on R-17). One planning call on M: 1 to 2 min (rank 10); none on S, which has no Spec stage. Integrator skip: 1.3 to 2.5 min on one-order lane-M tasks, 0 where main sessions already skip it (all 12 one-order tasks on POD-11). Not in minutes: PREFLIGHT and SPEC+HANDOFF actually run (2 of 63 and 3 of 29 on Sonnet main sessions).

**Protections.** 2026-11-03 stale base: in `start`, in `next` for a new driver, and at PLANNED to BUILD. 2026-11-02 claim (0.17.1): in `start`. AV-6033: `next` holds triage until sources.txt exists. T-007: PREFLIGHT, the split and the scope check are started by `next` and `done`. PR #203: deviation gate and order check in `done`; FOLD is called before `ship`. T-008 to T-014: setup lines inside every worktree RUN line; STATE fixes go to the architect; FIX-CHAIN is counted by the script. Local ids (0.11.0) and tempo/ branches (0.14.0): checked in `ship` before the push line prints, and the push still passes guard_push. Prune (0.12.0): `ship` prints the tempo_branches.py line, never `git branch -d`. 2026-10-30: push, gh, setup and teardown are RUN lines, so every hook still sees them and nothing long runs inside the state script; a fully blocked task stops its services. The long-agent notice (pod1um #64): a SAY line.

**Risks.** The largest step: about 600 new lines across the two scripts by now. QA is redone when round 1 fails. A next-wave order may build on a defect the order check then finds (HIGH or MEDIUM in 27% of orders); the fix arrives as a later commit of the earlier order. Workspace and split parents change with thin data behind them (3 and 1 tasks). Every `next` pays one or two tempo_config.py starts.

**Tests.** test_flow: a scratch repo walked through S, M, L and bug with stub artifacts, comparing printed lines; each edge and its fallback (FULL bars keep the integrator; a state model keeps the pre-check). `next --dry` replayed over copies of the real pod11, pod12 and work-account folders, including the 3 workspace and the 1 split folder, and a 0.21.0 state.json taken mid-BUILD (agents keyed by id, `waiting` set). `ship` refuses a local id in a commit subject and an unread tree. One real lane-S and one lane-M task on pod1um, compared with the 28 min POD-11 median.

**Changes.**
- `skills/orchestrator/scripts/tempo_flow.py`: ROUTES (flow and lane to stages, slices and workspace children from the parent's state); `next_lines(state, dir, cfg)`: position from stage, lane, counters, orders, open questions and files on disk; waves from Depends on; fix routing (severity, Fix kind, owner, FIX-CHAIN); bars and targets asked from tempo_config.py; the RUN lines and their effect checks (worktree and `setup-<name>.ok`, fast-forward, push, PR). Edges: QA in the same output as the round-1 lenses; the order check in the same output as the next wave's builders; PREFLIGHT with each wave; SPEC+HANDOFF for M; the guarded integrator skip. About 250 more lines.
- `skills/orchestrator/scripts/tempo_state.py`: Subcommands `start`, `next`, `ship`. `start` is handled beside `claim`, before the `register` call at line 327, so the repo is never registered as a task. `start` runs SKILL 1.0 to 1.9 and names the read-only base worktree `base-<task id>` (today `base-<first 8 of HEAD>`, which tasks at the same head share). `next` runs the base sync when the driver is new and at PLANNED to BUILD, sets `driver`, and adopts a 0.21.0 folder (final read required when the stage is before SHIP). `ship` uses `cleared`. `set --stage` refuses every stage but DONE on a driven task.
- `skills/orchestrator/SKILL.md`: Section 1 becomes: write the request, run `start`; 1.3.3 sources, 1.6.1 local ids and 1.7.1 repo convention stay. Section 2 becomes the loop plus 2.2, 2.4 and 2.6. Section 3 keeps its numbers and only the judgement of each stage; 3.12 becomes pr.md, the body and `ship`. Section 7 is one line. Sections 6 and 9: children and slices start with `start --parent` and run the loop; their own rules stay. About 310 to about 220 lines (ESTIMATE).
- `commands/feature.md, bug.md, plan.md, resume.md`: Point at `start` and the loop. resume: run `next`.
- `agents/architect.md`: Mode SPEC+HANDOFF: it is the default for M and stops after the Spec when section 1 has an open decision or section 8 is not NIL (2 lines).

### 0.27.0: /tempo:story in one session (planned)

**Goal.** D6 on plain Claude Code: a story of subtasks, each with its PR into a story branch, a merge queue, an integration bar and one story PR. Nothing is spawned.

**Saves.** Up to 114 min in a story where a modal question would have frozen it (H-1, once in 10 question rounds). Whole VM suite off critical subtasks without a config edit (the 0.23.0 figure, not a new one). ESTIMATE: part of about 2.5 min per task of repair for cross-task breaks found late (5 breaks plus 3 Chrome-only in 78 PRs). ESTIMATE: under 10 min at the end of a story from the readers running beside the suites. No minutes are claimed for the visual pass, for less polling or for independence from Herdr.

**Protections.** Never merge to base (SKILL 5.6): kept, with the carve-out checked in `merge` and in the hook. The silent failed merge of POD-10: MERGED is re-read first. Whole suites: a story child never gets FULL; a critical batch gets it on the story branch, and everything runs once at the end. Kill by name: the guard and `<run> stop` are prerequisites of this version. Claims, base sync, teardown on DONE: unchanged, per subtask.

**Risks.** One session drives up to three children; over a 40-subtask story its context will compact, and resume from files is what carries it. The bar adds one run per merge batch on a Mac where load is the unexplained limit; it is serialized, and one line in `next` drops it if it queues. The STOP_KINDS now reach Jorge through the queue; the Opus Herdr orchestrator ruled on some of them itself (dependency approvals). Chrome-only breaks still surface at the end.

**Tests.** test_story: scheduler on fake child states (dependencies, cap, blocked keys, merge order); `merge` with a stub `gh` on PATH refuses a PR with another base, a story branch equal to the base, a head no final read covers; one bar at a time; resume reconciles a merged PR. A three-subtask story on a scratch repo with one conflict and one red bar.

**Changes.**
- `commands/story.md (new, about 20 lines)`: Load the orchestrator skill, run `start --flow story`, follow SKILL section 11.
- `skills/orchestrator/scripts/tempo_flow.py and tempo_state.py`: Flow STORY and stage SUBTASKS; the story lines of `next` (start, drive, merge, bar, end, the counts event); `merge`; `start --parent` for a story child (base and PR base from the parent, bars NARROW from the parent's flow, one retry of the base sync). About 300 lines in all (ESTIMATE).
- `hooks/guard_push.py`: Deny `gh pr merge <n>` unless a story state in this repo lists that PR as checked by `merge`.
- `agents/integrator.md`: Mode BARS, 4 lines: no merge; the given bars over a given range on a given head in the story worktree; result in `bar-<n>.md` (Integration Report layout).
- `skills/orchestrator/SKILL.md`: New section 11 Story, about 25 lines: plan, answer, merge, bar, end, what the project supplies. 5.6 and 4.5.7 reworded: never merge into the base branch; a story merges subtask PRs into its own story branch only.
- `skills/artifact-templates/templates/plan.md and state.md`: Add STORY to the Scope and Flow lists (one word each).

### 0.28.0: Runner sessions: headless and Herdr (planned)

**Goal.** Each subtask in its own Claude Code session, for stories too large for one session and for watching runners in Herdr. Ships only what the spike proves.

**Saves.** No minutes claimed. It removes the context limit of the one-session story and lets Jorge watch and type into a runner.

**Protections.** 2026-10-30: runners carry the story's tag and are stopped at the story's end and listed by sweep; a runner's own SessionEnd stops only what it started (the 0.23.0 owner fix). Spawn guard: the detach happens inside the script; the guard's own rules are unchanged. Kill guard: hooks stay on in runners because `--bare` and `--safe-mode` are never passed.

**Risks.** Everything in the spike list. A gate answer costs a session resume, not seconds. A runner that outlives its supervisor has no timeout and no cost stop; nobody merges until a supervisor runs again. The hc and herdr-app calls are taken from the project skill's text.

**Tests.** test_story with a stub `claude` on PATH: launch environment has no TEMPO_OWNER or TEMPO_SVC; a live id is never resumed; DEAD with no stop; an interrupted `watch` reconciles. Stub `hc` and `herdr-app`. A two-subtask story on a scratch repo, once headless and once with Herdr.

**Changes.**
- `spike, before any code`: On a scratch repo and on the work account: do plugin hooks (kill, spawn, push, SessionEnd) fire in `claude -p`; do plugin agents and skills resolve there; does a nested `claude` start from a process a Claude session launched; what happens at turn end with an agent in the background; does `--resume <uuid>` keep id and context; what `--permission-prompts none` denies under each account's settings. If headless fails, ship the Herdr launcher only.
- `skills/orchestrator/scripts/tempo_state.py and tempo_flow.py`: `launch` (the argument list and environment in story_flow, pid, start time and session id on the child row), `watch`, DEAD and STALLED lines, the story teardown by tag. About 120 lines (ESTIMATE).
- `hooks/guard_spawn.py`: Add `tempo_state\.py watch` to the commands allowed as a background Bash.
- `skills/orchestrator/scripts/tempo_procs.py`: Docstring: the teardown table gains the runner row (outlives the supervisor's session, ends at its next stop, stopped by the story's teardown, listed by sweep).

## The single-task flow at 0.26.0

State of the flow at 0.26.0. `<state>` is tempo_state.py. The session Jorge starts is the main session, on any model.

THE LOOP (all lanes)
- Main: writes the request text to a file, picks slug and type, runs `<state> start`.
  - Script: strips the flags, config check, base sync, info/exclude, claim, docs.txt, names, init with the final read required. Prints the first lines.
- Main: does every printed line. All CALL lines of one output go in one message (side by side). After the replies: `<state> done <dir> <labels>`.
  - Script at `done`: closes the agents, runs the document checker, reads each result from the checked file (never from reply text), logs the stage, bumps counters through the limit check, runs the stage's file checks, sets the stage, renders the next prompts, prints the next lines.
- Main never writes a prompt, a test command, `--heavy`, a model name, a branch name or a stage change.
- Main decides only at: slug and type; the sources list; merging scout replies into context.md; DECIDE lines; pr.md, PR title and body; showing a question to Jorge.
- A file the script cannot parse becomes `DECIDE UNPARSED <file>`, never PASS.

LANE S (feature)
- TRIAGE: DO sources.txt (SKILL 1.3.3), then CALL triage.
  - Script reads lane, Critical and questions from task.md. Questions: DECIDE GATE-CLARIFY (queue, or autopilot's recommendation).
- HANDOFF: CALL architect HANDOFF (one order from task.md).
  - Script: scope-overlap check; an order whose Verification holds a whole-suite line goes back once.
  - Script prints one RUN line per order: worktree add plus the setup lines, through `<run>`. It records the order when the worktree and its ok-marker exist.
- BUILD: CALL builder BUILD.
  - Script: scope diff against the order's IN; deviation tags (CRITERION, CONTENT, CUT: DECIDE with the ready `call architect --mode AMEND` line); BLOCKED: DECIDE.
- INTEGRATE: script prints the bars and target lines from tempo_config.py as they are. CALL integrator MERGE.
  - Skipped only when all hold: one order (or a fast-forwarded chain), bars NARROW, no platform target line, and the report shows build or typecheck and lint green on that tree. The script then prints the fast-forward as a RUN line and writes integration.md citing the report.
- REVIEW round 1: CALL reviewer CORRECTNESS (QUICK).
  - No candidate above LOW: script writes findings PASS. Otherwise CALL verifier with the fix severity.
- FINAL READ: CALL final-read (model `models.final_read`) on base...head. Script records the tree it read.
- SHIP: CALL integrator FOLD when fixups exist. DO pr.md and the PR body. `<state> ship` checks the outward text and the final read, then prints the push, `gh pr create`, teardown and prune lines as RUN lines. The next `ship` call checks their effect and sets DONE.

LANE M
- TRIAGE as S.
- EXPLORE: CALL scout CODE-PATHS and PATTERNS-AND-TESTS side by side; CONSUMED-BEHAVIOUR too when task.md names a consumed service or ported code. DO: save the replies, merge context.md. Script re-sizes and sets the pattern flag from context.md.
- PLAN: one CALL architect SPEC+HANDOFF. The architect stops after the Spec when section 1 has an open decision or section 8 is not NIL.
  - Section 8 not NIL: CALL reviewer SPEC-PRECHECK; HIGH or MEDIUM: CALL architect AMEND; then CALL architect HANDOFF.
  - Open decision: DECIDE GATE-SPEC.
  - Script after HANDOFF: scope overlap, whole-suite lines, waves from Depends on.
- BUILD per wave: RUN lines for the worktrees, then CALL the wave's builders side by side (cap `limits.max_parallel_builders`, unchanged) plus PREFLIGHT builders for issued orders of the next wave.
  - On each report: scope and deviation checks, then CALL reviewer ORDER. The next wave's builders are in the same output; the order check no longer holds them. HIGH or MEDIUM: CONTINUE the builder in FIX.
  - A one-order wave that the next wave depends on: fast-forward as a RUN line.
- INTEGRATE: script checks base drift (CALL integrator REBASE when paths overlap), prints bars and targets. CALL integrator MERGE.
- REVIEW round 1 and QA side by side: CALL reviewer CORRECTNESS, reviewer SPEC and qa in one output; SECURITY when review-rules 2.2 applies (DECIDE, yes or no).
  - FAIL, routed by the script: fix chain: DECIDE FIX-CHAIN. Every finding LOCAL, in its owner's IN, no criterion change (a HIGH included): CONTINUE builder FIX. STATE or a criterion change: CALL architect AMEND, then the builder. Then NARROW integrate and a NARROW round on the fix diff.
  - QA FAIL: script bumps the QA counter; builder FIX; past the limit: DECIDE LOOP-LIMIT. After a fix, QA re-checks the criteria the fix touches.
- FINAL READ: CALL final-read when the findings pass, beside QA if QA still runs.
  - FAIL: its HIGH findings are a review round, routed as above; the verifier and the severity cut do not drop them.
  - Any commit after a read (its fix, a QA fix, a fix after the PR, a conflicted merge): CALL final-read on the diff since the head it read.
  - At the review hard stop its open items ship as known risks.
- SHIP as S.

LANE L: as M, except
- 3 scouts.
- CALL architect SPEC alone; SPEC-PRECHECK always; AMEND on HIGH or MEDIUM; DECIDE GATE-SPEC always; then CALL architect HANDOFF.
- A SPLIT reply: SKILL section 9; each slice is started with `start --parent` and runs BUILD, INTEGRATE, REVIEW through the same loop.
- DEEP review: CORRECTNESS, SECURITY, SPEC.
- Critical or a `gates.full_paths` hit: FULL bars once, at the final integrate, with the lines the script printed (unchanged from 0.21.0).

BUG FLOW
- TRIAGE as S. BUG-FEEDBACK only: CALL investigator.
- CALL reproducer REPRODUCE. NOT REPRODUCED: DECIDE NO-REPRO, always queued for Jorge.
- CALL reproducer ROOT-CAUSE. Behaviour change: DECIDE BEHAVIOUR-CHANGE, always queued.
- CALL architect HANDOFF (one order, criteria from the repro, from the repro branch). Then BUILD, INTEGRATE, REVIEW with the sibling sweep beside QA (QA in every lane), FINAL READ, SHIP.

PLAN-ONLY: the same chain up to HANDOFF, DO plan.md, then `PLANNED`. `/tempo:resume <id> build` runs `next`, which syncs the base first.

BEFORE 0.26.0
- 0.24.0: the stage order is still SKILL prose; the final read is one new step and the push hook enforces it.
- 0.25.0: the order is still prose, but every agent starts with `<state> call` and ends with `<state> done`.

## Script commands

All new commands are subcommands of skills/orchestrator/scripts/tempo_state.py (`<state>`). The route table, the prompt table, the renderer and the file readers live in a new module beside it, tempo_flow.py, which has no command line of its own (so tests can import it; tempo_state.py keeps everything inside main()). Both call tempo_config.py as a subprocess each time (uv when present, else python3) through a new helper `tempo_procs.cfg(repo, *args)`. There is no config snapshot.

0.23.0
- `tempo_run.py [--task DIR] [--heavy] ... -- COMMAND`: with `--task` and a readable config, the script decides the slot.
  - Always heavy: the last `&&` part (after dropping a trailing `2>&1`, `| tail ...`, `| tee ...`) equals the last part of `commands.test` or of a target's `command`.
  - Never heavy, whatever the flag: the command matches `commands.test_one` with at least one test argument, or its last part equals that of `commands.typecheck` or `commands.lint`.
  - Everything else (a target's scoped line, an app build, `commands.build`, an unknown command): the caller's `--heavy` decides, as today.
  - Without `--task`, or when the config cannot be read: as today. No run is refused.
- tempo_run.py summary: exit 137 or 143 (a negative code becomes 128+n first) prints a first line `KILLED: signal <n>. Stopped from outside, not a test failure. Run it again once.` The dead-worker path of `wait` prints the same.
- tempo_run.py appends `{"ev":"run-end","id","exit","seconds","waited","load1","killed","leftovers"}` to events.jsonl when a run ends.
- `tempo_config.py bars`: with `gates.full_bars: verify` prints `BARS: NARROW  WHY: gates.full_bars is verify`, plus `DEFERRED: critical change` or `DEFERRED: gates.full_paths matches <paths>`.
- `tempo_config.py targets --scoped-only`: a target that would print its whole `command` prints `<name>\t# DEFERRED whole suite` instead.
- `<state> log <dir> QA qa-rN.md <result>`: raises the QA counter to N, and on a FAIL at or past the limit prints `LIMIT: qa rounds N of L; raise LOOP-LIMIT` (exit stays 0). A PASS prints nothing; `bump` is unchanged.

0.24.0
- `<state> init ... --final-read MODEL`: marks the task as needing a final read.
- `<state> log <dir> REVIEW review/final-<n>.md PASS|FAIL`: reads Result and the head from the file itself, stores the head's tree. Exit 1 when the argument and the file disagree.
- `<state> set <dir> --ship-risks on|off`: the hard-stop ship (SKILL 3.10.6). `bump` exit 2 sets it by itself.
- `<state> set <dir> --pr URL`: exit 1 with the reason when the final read is required and does not cover the branch.

0.25.0
- `<state> call <dir> <agent> [--mode M | --lens L] [--wo NN] [--round N] [--note-file F]`
  - Renders `prompts/<label>.md`, records the agent in flight under its label, sets the stage that agent belongs to, sets this session as driver.
  - Prints `CALL <agent> MODEL <model> LABEL <label> PROMPT <abs file>`. The main session calls that agent type with that model and the prompt "Read <file> and follow it."
  - Exit 0; 1 unknown agent, mode or order.
- `<state> done <dir> <label>[:<agent id>] [<label> ...]`
  - Prints per label `RESULT <label>: PASS|FAIL|BLOCKED <the file's result line>`, then `FACT` lines the next step needs (lane, critical, questions, open decisions, state model, deviation tags, paths outside IN, whole-suite lines, candidates by severity), then `LIMIT:` or `HARD STOP:` when a counter passes its limit.
  - Exit 0; 5 `CHECK FAIL <file>: <finding>` (nothing logged; fix the structure or call once more); 1 label not in flight.
- `<state> wait <dir> FILE --blocks ALL|PLAN|SHIP|WO-NN[,..]|<child key>[,..] [--kind KIND]`: adds a queue entry; status and services stay as they are.
- `<state> wait <dir> --clear FILE --answer TEXT [--by jorge|supervisor]`: writes the answer into the esc file's section 6 and closes the entry. `--by supervisor` is refused for the STOP_KINDS.
- `<state> wait <dir> FILE` and `<state> wait <dir> --clear` with no other flag: exactly as 0.21.0.
- On a task with a driver, the commands `log`, `bump` and `agent` refuse (exit 1, naming `done`).

0.26.0
- `<state> start <repo> --flow feature|bug|story --request-file F --slug S --type T [--id KEY] [--parent DIR]`
  - Prints `TASK: <id>  DIR: <abs>`, `BASE: <branch> <head> [UPDATED n]`, `BRANCH: <name> (<convention>)`, `AUTOPILOT: ON|OFF`, `MODE: FULL|PLAN-ONLY`, WARN lines, then the output of `next`.
  - Exit 0; 2 config FAIL or BASE STOP (nothing claimed); 3 the folder exists (prints `RESUME: <state> next <dir>`).
  - `--parent` takes base, PR base, route, lane and autopilot from the parent's state and plan; it refuses a key the parent has not registered. There is no `--base` and no `--route` flag.
- `<state> next <dir> [--takeover] [--dry]`
  - Recomputed every time from state.json and the files on disk. Lines:
    - `CALL <agent> MODEL <m> LABEL <l> PROMPT <file>`
    - `CONTINUE <label> PROMPT <file>` (message the agent started under that label; call it fresh if it cannot be reached)
    - `RUN <shell line>` (its effect is checked at the next `next`)
    - `DO <what> THEN <command>` (sources.txt, context.md, plan.md, pr.md)
    - `DECIDE <KIND> <file>: <one line>`, followed by the commands allowed
    - `SAY <one line for Jorge>` (milestones, and the notice before an agent of 20 minutes or more)
    - `WAITING <esc file> blocks <scope>`, `IDLE <n> in flight: <labels>`, `PLANNED <plan.md>`, `DONE <pr url>`
  - Exit 0; 3 `BUSY driven by pid <n>` (another live Claude session; `--takeover` overrides); 4 everything left is blocked by open questions (it sets WAITING-ON-JORGE and stops the task's services); 1 error. `--dry` writes nothing.
  - A new driver session (a restart or a resume) gets the agents in flight again as CALL lines from their saved prompts, and the base sync runs first.
- `<state> ship <dir> --title T --body-file F`
  - Exit 2 with the hits when the title, body or `git log base..branch` holds a local id, `WO-`, `ESC-` or `.tempo/`; when findings or QA did not pass; or when no final read covers the tree.
  - First call prints RUN lines: rename of a legacy `tempo/` branch, `git push -u origin <branch>`, `gh pr create` (draft and base from config or the parent), teardown, worktree removal, prune.
  - Next call reads the remote head and `gh pr view`, then logs SHIP, records the PR and sets DONE. `pr.tool: none`: prints `MANUAL:` lines for Jorge and sets DONE without a PR.
- On a driven task `set --stage` refuses every stage but DONE.

0.27.0 and 0.28.0
- `<state> merge <story dir> <KEY>`: checks, then prints the `gh pr ready` and `gh pr merge <n> --squash` RUN lines; the next call re-reads MERGED, prints the story-branch fast-forward and teardown lines, and marks the child merged. Prints `MERGED <KEY> <hash>`, `CONFLICT <paths>` or `NOT MERGED <reason>` (exit 1).
- `<state> launch <story dir> <KEY> [--herdr]` (0.28.0): prints `LAUNCHED <KEY> <pid or terminal>`.
- `<state> watch <story dir> [--max SECONDS]` (0.28.0): run as a background Bash; exits when a child needs the supervisor and prints the same lines as `next`. Exit 0 on an event, 75 on `--max`.

HOW PROMPTS ARE RENDERED
- One table in tempo_flow.py keyed by agent and mode or lens: input files, output file, template, and three flags (commands, commit rules, targets).
- Fixed layout: header (task, agent, mode or lens, lane, round, kind, depth); absolute input paths; output path; template path; checker command; the values the agent file lists (limits, fix severity, base, head, branches, worktree); the commands block; the note.
- The commands block appears only for agents that run code: `<run>` with `--task`, `<procs>`, test-one, build or typecheck, lint, target lines exactly as tempo_config.py printed them, bars, commit rules, the setup command, and "Stop a run with `<run> stop <ID>`. Never kill, pkill or killall."
- What varies: the header values, the table row, the commands block, and the text of `--note-file` (an answer, the findings to fix).
- A prompt for an agent whose model is not `models.default` ends with "Do not call the advisor tool."
- Never in a prompt: the full test command for a builder, `--heavy`, a model name, any attribution text.

## Config keys

### `models`
- Values: closed object. `default`: string. `final_read`: string. Optional strings, one per agent: triage, scout, architect, builder, integrator, reviewer, verifier, qa, investigator, reproducer. Each value is a model name the Agent tool accepts (sonnet, opus, haiku). Added as `$defs/models` and referenced from repoFile, repoEntry and the workspace file's `defaults`.
- Default: default: sonnet; final_read: opus; every agent key unset (falls back to default)
- Replaces: `model: opus` in architect.md, reviewer.md, verifier.md, investigator.md and reproducer.md; SKILL 5.8 and the five per-stage "pass model: sonnet" clauses; later the Models line of the project's brief.sh.
- A config written for 0.21.0: A 0.21.0 config has no `models` and still passes `check`. From 0.24.0 its lane-L architect, reviewer, verifier, investigator and reproducer run on Sonnet (they ran on Opus), and one Opus read is added before each PR. To get the old pins back: `models: {architect: opus, reviewer: opus, verifier: opus, investigator: opus, reproducer: opus}`. A config that names `models` fails `check` on a plugin older than 0.24.0, so do not add it to a tracked config until every machine is updated; the defaults need no key.

### `limits.fix_severity`
- Values: enum: HIGH | MEDIUM
- Default: HIGH
- Replaces: The fixed "HIGH or MEDIUM" in verifier.md step 8, the findings template's Result line and SKILL 3.10.5; the standing decision "review fixes only CRITICAL or HIGH" that the story skill writes into each story config. TEMPO's scale has no CRITICAL; its HIGH is the top.
- A config written for 0.21.0: Absent means HIGH: a diff-review round fails only on a confirmed HIGH; confirmed MEDIUM and LOW go to findings section 5 and from there to a Follow-ups section of the PR body. It applies to diff-review rounds, the final read and automated findings after the PR. It does not apply to the spec pre-check or the order check (both still act on HIGH and MEDIUM), nor to Jorge's own PR comments (always fixed). `MEDIUM` restores 0.21.0. Same older-plugin warning as `models`.

### `gates.full_bars`
- Values: enum: on_demand | integrate | verify (verify is new)
- Default: on_demand (unchanged)
- Replaces: The story skill's standing decision and brief line that no subtask runs the full suite.
- A config written for 0.21.0: Nothing changes for a config that does not name the key or names `on_demand` or `integrate`: a lone critical task or a `full_paths` hit still runs the whole suite once, at its final integrate. `verify` never runs FULL bars inside a task: `bars` prints NARROW with a DEFERRED line, targets print scoped lines only, and the PR body says the full suite was not run. Until /tempo:story exists, set it only in the story checkout's untracked config (the story skill already edits that file). From 0.27.0 a child of a story is deferred by its parent's state, whatever the key says.


## The story flow (`/tempo:story`)

/tempo:story <STORY> [--cap N] [--auto]. Ships in 0.27.0 in one session; runner sessions come in 0.28.0.

ROLES
- Supervisor: the session Jorge starts. It plans, drives or launches the subtasks, answers, merges and ships. It writes no production code.
- Subtask: an ordinary task folder whose parent is the story folder. Its base and PR base are the story branch, taken from the parent's state. No separate story checkout and no config edit is required by TEMPO.
- Everything between supervisor and subtask goes through files: the child's state.json, its esc files, the answer in esc section 6.

STEPS
1. Start. `<state> start <repo> --flow story --id <STORY>`: config check, base sync, claim `.tempo/<STORY>/`, story branch named by `tempo_config.py names --type feat --ticket <STORY>`. Prints RUN lines that create it at the base head and push it (subtask PRs need it on origin). Stage PLAN.
2. Plan. DO plan.md from the existing template with Scope STORY: one slice per subtask (key, objective, source file, feature or bug, lane hint), blocks-start edges, open decisions.
   - Each open decision becomes an esc file and `wait <story dir> esc-N.md --blocks <keys>` at once. Subtasks that do not depend on it start anyway. No direct question (the hook denies it).
   - `done <story dir> plan` checks the file, registers the children and moves to SUBTASKS (one new stage name).
3. Start subtasks. `next <story dir>` prints `RUN <state> start <repo> --flow feature|bug --parent <story dir> --id <KEY> ...` for each subtask whose blocks-start sources are merged and that no open question blocks, while live subtasks are below the cap (`limits.max_parallel_builders`, default 3, or `--cap`).
   - Each `next` appends one event with ready, live, cap and blocked counts, so the first story shows whether the cap or the chains bound it.
4. Run a subtask.
   - 0.27.0, plain Claude Code: the supervisor runs each child's own loop (`next <child dir>`, the CALL lines, `done <child dir>`), as SKILL 6.6.8 does for workspace children today. Agents of different children start in the same message. Nothing is spawned, so no owner, SessionEnd or permission question arises.
   - 0.28.0, runner sessions: `launch <story dir> <KEY>` runs the child's `start` itself, then starts `claude -p --session-id <uuid> --model <models.default> --permission-prompts none "<fixed prompt>"` in its own process session. The fixed prompt needs no slash command: load the orchestrator skill, run `<state> next <child dir>`, do what it prints until DONE or WAITING, end the turn with that line, never ask the user.
     - Environment: every TEMPO variable removed, then `TEMPO_TAG=<story tag>` and `TEMPO_RUNNER=<KEY>`. No owner, no service label, no ledger row. A services-only teardown spares it; the story's own teardown and /tempo:sweep find it by the tag.
     - `--bare` and `--safe-mode` are never passed; the argument list is fixed in code.
     - With `--herdr`: the same prompt goes to `herdr-app do space.new` with an interactive `claude`; the terminal and space ids are stored on the child row. A later wake is `hc send <terminal> "..."`.
     - The supervisor starts `watch <story dir>` as a background Bash and ends its turn; its exit wakes it. It reads files only.
     - DEAD: a RUNNING, unblocked child whose recorded runner process is gone. `launch` again resumes it (`--resume <uuid>`, else a fresh session; the position is in files). STALLED: no state change for 15 minutes and no run in flight.
5. Answer. A child's question is an esc file with `--blocks`. The supervisor answers from plan.md's decisions and the sources when the kind is not one of the STOP_KINDS: `wait <child dir> --clear esc-N.md --answer "..." --by supervisor`. The STOP_KINDS, NEEDS-JORGE questions and options with no recommendation go to Jorge; they show on the dashboard and in `next <story dir>` as WAITING lines. A child's question blocks that child at most.
6. Merge queue. `next` prints `RUN <state> merge <story dir> <KEY>` for each child that is DONE with an open PR, one at a time.
   - `merge` refuses unless: the PR base equals the story branch recorded in the story state; that branch is neither `git.base_branch` nor `pr.base`; the PR head is the child's task branch; findings and QA passed; the final read covers the PR head's tree.
   - Then RUN lines: `gh pr ready` if draft, `gh pr merge <n> --squash`. The next call re-reads MERGED before anything else, prints `git fetch origin <story>:<story>` and the child's teardown and worktree lines, and marks the child merged in the story state.
   - CONFLICT: the child merges the story branch into its branch (no rebase, no force-push), reruns NARROW bars, the final read reads the resolution, and it pushes.
   - This is the one carve-out of SKILL 5.6 and 4.5.7: TEMPO merges a subtask PR into its own story branch, never anything into the base. guard_push denies any other `gh pr merge`.
7. Integration bar. After a merge, when no bar runs and the story head differs from the last bar's head, `next` prints one CALL integrator in mode BARS: no merge, bars over `<last green head>..HEAD` in a story worktree, result in `bar-<n>.md`.
   - Bars come from `tempo_config.py bars --paths <range diff>`, with `--critical` when a merged child in the range is critical. So the whole VM suite runs on the story branch only for a batch that holds a critical or lockfile change, through a heavy slot.
   - One at a time. Merges never wait for it; the next bar covers every merge since the last green head.
   - FAIL: DECIDE BAR-FAIL. A red result is compared with the base before it counts. The supervisor adds a fix subtask to plan.md.
8. End of story, when every subtask is merged or moved out and the last bar is green. `next` prints together:
   - RUN lines for the whole suites, once, through `<run>`: test, build, lint, and `targets --full` when any subtask was critical, else `targets --critical --paths <story diff>`.
   - CALL final-read (model `models.final_read`) on base...story head against plan.md's decisions and answers.
   - CALL reviewer SECURITY on the story diff.
   - The readers only read, so they run beside the suites. Anything that opens a browser or emulator (the project's visual pass) starts after the suites.
   - A HIGH finding or a new red suite: fix subtasks, merge, bar, rerun only the failed line.
9. Ship. DO the story PR body from tracker.md (subtask, change, PR), the decisions, each child's follow-ups and the checks. `<state> ship <story dir>` prints the `gh pr create` line, story branch to base. Jorge merges it.
10. Resume. `/tempo:story <STORY>` again, or `/tempo:resume <STORY>`. `next` rebuilds from the files and a read-only `gh pr list --base <story branch> --state all`: merged on GitHub but not recorded is recorded; DONE with an open PR gets a merge line; a dead runner gets a launch line. No run log is needed.

WHAT STAYS A PROJECT FILE
- `<repo>/.tempo/story-brief.md`, optional: its path is one input line in the triage, architect and builder prompts of story children (prototype path, screenshots folder, ADR-number claims, dependency pin rule).
- The project skill, much shorter: read the story and subtasks from Jira into `sources/`, tracker moves on the start and MERGED lines, follow-up tickets, the hotspot-file judgement, the visual pass, the QA handoff, tracker-specific config (ticket pattern, commit template). `references/project.md` stays as it is.
- Gone from the project skill once /tempo:story is in use: brief.sh's model, scope and Chrome lines, watch.sh, the Herdr launch, answer and merge procedure, the base-branch config edits, the resume reconciliation.
- Until then pod-story-run keeps working on /tempo:feature in every version of this plan.

## The question queue

FORMAT
- One `esc-N.md` per question, from the existing escalation template, in the task folder. A story-level question sits in the story folder.
- state.json gains `questions`: a list of `{file, kind, blocks, asked, answered, by}`. `waiting` is the oldest open file, so the 0.22.0 dashboard shows the queue with no change.

WHO WRITES
- The main session writes the esc file, then runs `<state> wait <dir> esc-N.md --blocks <scope>`. From 0.26.0 the DECIDE line prints that command with the scope already filled from the kind.
- Agents never write to the queue; they reply BLOCKED, QUESTIONS or ESCALATE as today.
- No modal question in a run: a hook denies AskUserQuestion in the session that drives a task.

WHO ANSWERS, AND HOW
- Jorge, by typing in the session or with `/tempo:resume <task-id> <answer>` from any session. The dashboard only shows the question, the options, the recommendation and that reply line (D7).
- The session records it with `<state> wait <dir> --clear esc-N.md --answer "<his words>"`, which writes section 6 Answer and the date.
- In a story the supervisor may answer a subtask's question from the plan's decisions and the sources, with `--by supervisor`. The script refuses that for the STOP_KINDS.

WHAT CONTINUES MEANWHILE
- Everything the question does not block. Scopes: `WO-NN` (the other orders build and get their checks; integrate waits), `PLAN` (read-only stages run; Spec, Handoff and Build wait: GATE-CLARIFY, MISSING-SOURCE), `SHIP`, a child key on a story (every other subtask starts and merges), `ALL` (GATE-SPEC, NO-REPRO, BEHAVIOUR-CHANGE, LOOP-LIMIT, FIX-CHAIN).
- Only when nothing unblocked is left and no agent or run is open does the task become WAITING-ON-JORGE; its services stop then, so the 2026-10-30 rule holds at the moment it matters.

WHICH QUESTIONS MAY TAKE THE RECOMMENDED OPTION
- Exactly the ones SKILL 4.5.2 lists, and only on autopilot: clarify questions not marked NEEDS-JORGE, GATE-SPEC, GATE-PLAN in FULL mode, LOOP-LIMIT, the first FIX-CHAIN, the small config asks. They are recorded with `decide` and never queued.
- Never: the STOP_KINDS in tempo_state.py (NO-REPRO, BEHAVIOUR-CHANGE, OUT-OF-ORDER-DECISION, HARD-TO-UNDO, MISSING-SOURCE, GATE-PR), a NEEDS-JORGE question, an option with no recommendation, the second FIX-CHAIN.
- There is no timeout that applies a default. Off autopilot nothing takes its own recommendation.

## Removed by the plan

- Frontmatter `model: opus` on five agents, SKILL 5.8 and the five per-stage "pass model: sonnet" clauses (0.24.0): every one of the 607 + 662 agent rows of POD-11 and POD-12 already ran on Sonnet through one sentence in the brief (verify-evidence D-3); config replaces both.
- The severity clause of SKILL 3.10.5.2, "every confirmed finding is MEDIUM or LOW" (0.24.0): with HIGH-only fixing it is never true, and every fix would go through the architect.
- SKILL 2.7, 2.7.1 and 5.1 to 5.2.2, prompts written by the main session (0.25.0): the Sonnet main session wrote `--heavy` as the generic run line in 151 of 619 prompt files (35 of 38 POD-12 sessions) and wrote the full Chrome command by hand in POD-177 and POD-197. `call` renders them.
- The `agent start` and `agent done` turns around every agent and SKILL section 7's restart by agent id (0.25.0): two state calls per agent served restart recovery once in 80 sessions (verify-design, verdict on W-6). `call` and `done` record the agent; a restart calls it again from its saved prompt. The subcommands stay for old folders.
- SKILL 2.1 and 2.5 as separate turns (checker, log, set, bump) (0.25.0): about 17 s per hop over 15 to 20 hops per task (verify-design rank 5); they run inside `done`. The QA counter was 0 in 62 of 65 tasks with a QA report.
- SKILL 1.0 to 1.9 as separate steps (0.26.0): one `start`.
- The stage order and "which agent gets what" in SKILL 3.1 to 3.11 (0.26.0): the route and prompt tables. Only each stage's judgement stays. Sonnet main sessions skipped PREFLIGHT (2 of 63 builders against 38 on Opus) and the single planning call (3 of 29 against 9 of 14).
- SKILL 3.12's serial ship commands (0.26.0): one `ship` that prints them. SHIP was logged in 17 of 79 finished tasks.
- SKILL 4.2 step 4, "End your turn. Do not continue other stages", and the modal question (0.25.0): one AskUserQuestion froze a story for 114.4 min.
- `--heavy` in rendered prompts (0.25.0). The flag stays in tempo_run.py and in integrator.md and qa.md for target lines and app builds.
- From the project story skill, once /tempo:story is in use (not this repo): brief.sh's model, scope and Chrome lines, watch.sh, the Herdr launch, answer, merge and resume procedure, the base-branch config edits.
- Cut from the three designs: the agent-call hook, the whole-suite refusal in tempo_run.py, the config snapshot, a Write tool for scouts, the legacy reference file and the citation rename sweep, the load-average rule for builders, script-side merges of order branches, the gate before every merge, the workspace and split migration phase, every `story.*` key, `limits.story_runners`, `targets[].run: merge`, `--route` and `--base` flags, a changed default for `gates.full_bars`.
- Not deleted, because the checkers overrule the readers: PREFLIGHT, SPEC+HANDOFF in one call, the order check (HIGH or MEDIUM in 27% of orders), the verifier, the spec pre-check, the security lens (0 HIGH in 67 runs, but it runs beside the others), model QA, continued agents, every old tempo_state.py subcommand, the `reissue` counter (left unused).

## Open risks

- Offer, not in the plan: a top-tier read of the spec's open decisions. On autopilot with a Sonnet main session nobody top-tier reads the spec gate, and 37 of 67 top-model answers there changed something. It would be one more mode of the final-read agent and one key, `models.spec_gate`, switchable off. One judge asks for it, the other forbids it without your yes, and it is outside D1 to D7.
- The 04:06 cause is unproven. Exit 137 is SIGKILL; `pkill -n` sends TERM to one process, and TEMPO's own stops send TERM first and KILL only after 5 to 10 s, which does not fit two seconds. The four tasks have no procs.log. The kill guard closes one cause; memory pressure or a tool update that morning were never checked. From 0.23.0 a killed run says KILLED, is rerun once, and leaves a record with the load. The guard cannot stop a session outside TEMPO.
- Whole-package test runs still happen in every multi-order subtask (integrator NARROW) and again at the story bar; POD-213 and POD-209 lost 400 INTEGRATE minutes to that and to slot queue. This plan removes the queue part and the single-order case only. After 0.23.0 those runs take no slot, so several at once may load the Mac. Measure the first story from the run-end events (seconds, waited, load) before trusting the heavy figure.
- POD-12 stayed 2.3 times slower than POD-11 for reasons nobody found. No cap is raised and no order is started earlier in parallel, but the integration bar adds one run per merge batch and QA starts earlier. Parallel work orders by file ownership are cut until a run shows headroom.
- What all-Sonnet review lets through was never compared with Opus on the same diff. The final read is the only backstop for a lone run. Count final-read FAILs after passing rounds over the first 20 tasks; if they are frequent, put a lens back on Opus with `models.reviewer`.
- The Opus final read may still call the user's advisor (about 134 s per call). An agent's tools list does not keep it out: the Opus reviewers had one and spent a third of their time there. Only the prompt line is in the plan; unsetting `advisorModel` is the sure fix.
- `models` values are not checked against what the Agent tool accepts (the schema takes any string; Jorge's own session runs a model the plan never passes). A wrong name fails loudly at the first CALL.
- Headless `claude -p` is unverified on every point in the 0.28.0 spike list, and so is whether hooks see Bash calls inside subagents (the pkill came from a builder). 0.27.0 does not depend on the first; the second was due a two-minute hand test in 0.23.0, which was not done.
- The push guard fails open, sees only Claude's Bash, and is skipped with `TEMPO_ALLOW_PUSH=1`. The story skill's own-resolution push of a conflicted merge (pod-story-run 7.3, second sentence) is denied without that marker; sending the conflict back to the runner is the path.
- Fixes after the PR still share the review round counter; a change cycle caused by Jorge's own comment can hit the limit. The guard guarantees each pushed fix was read, but a separate counter is not built.
- The end of a story stays mostly serial (45 to 60 min). Only the readers run beside the suites. Whether a full verify and a browser pass fit on the Mac together needs one measured run; nothing here schedules it.
- Chrome-only breaks (3 of the 8 red merges) still surface only at the end verify for routine subtasks.
- The same target can still run on the same head in builder, integrator, QA, bar and verify. A result cache keyed by commit, target and SDK version is cut; nobody counted the repeats.
- New config keys fail `check` on a plugin older than the version that adds them. pod1um tracks its config, so add none there until every machine is updated; `verify` belongs only in the untracked story checkout config.
- tempo_flow.py reaches about 900 lines by 0.27.0 and reads agent-written markdown; the plugin has one test file today. The golden prompts, the reader tests on real artifacts and the dry replay over real folders are the safety net and must exist before 0.26.0 ships. Workspace and split parents have 3 and 1 real folders to replay.
- The dashboard shows the waiting file with no change, but not yet the question list, the final-read state, the driver or story children. A small dashboard update is needed after 0.25.0 and 0.27.0.
- Cut on purpose: a timeout that applies a default answer, re-attaching a run after its session dies (a run still dies with its session, by the 2026-10-30 rule), QA by script, a visual pass beside the verify, branch deletion on merge (use GitHub's auto-delete), machine-wide runner slots (two stories at once would each use the cap).
- Not checked: nothing was run except `claude --help` and read-only greps, and no file was changed. I read the plugin scripts, SKILL.md, the agent files, both checker files and the project story skill; not the reader files, tempo_dash.py beyond its agent lookup, check_doc.py beyond its template lookup, or the templates beyond their result lines. Line counts and all figures marked ESTIMATE are estimates. The kill guard, `<run> stop`, events.jsonl and the dashboard are assumed as described; the AskUserQuestion hook matcher and the per-version plugin folders are assumed from how Claude Code hooks and plugins normally work.
