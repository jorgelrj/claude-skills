# TEMPO

Task Execution & Multi-agent Pipeline Orchestrator. A Claude Code plugin that takes a feature request or a bug report to an open pull request through a fixed set of stages, each run by an agent with a fresh context. Agents hand work to each other only through structured markdown documents: fixed numbered sections per document type, tagged criteria and findings, and exact paths and commands.

Architecture (draft 2): https://claude.ai/artifact/AuXx9nGXWqDxLeG72K1abT

## Install

TEMPO ships in the `jorgelrj-skills` marketplace (this repo):

```bash
claude plugin marketplace add jorgelrj/claude-skills
claude plugin install tempo@jorgelrj-skills
```

## Install for testing

From inside the project you want to test on, with `<claude-skills>` being your checkout of this repo:

```bash
# Option A: load straight from the working tree for one session
claude --plugin-dir <claude-skills>/plugins/tempo

# Option B: register the checkout as a local marketplace (persists)
/plugin marketplace add <claude-skills>
/plugin install tempo@jorgelrj-skills
```

After editing files here, restart Claude Code (Option A) or run `/plugin marketplace update jorgelrj-skills` and reinstall (Option B).

## Use

| Command | What it does |
|---|---|
| `/tempo:feature <request>` | Feature flow: Triage → Explore → Spec → Work Orders → parallel Build → Integrate → Review → QA → PR. The lane (S, M, L) decides which stages run |
| `/tempo:feature --quick <request>` | Lane S: one Work Order from the Task Card → Build → correctness review → draft PR. `--lane S\|M\|L` sets any lane; `/tempo:bug` takes the same flags |
| `/tempo:bug <report>` | Bug flow: [Investigate] → Reproduce (failing test) → Root cause → Fix → Integrate → Review + sibling sweep → QA → PR |
| `/tempo:plan <request>` | Plan only: Triage → Explore → Spec → Work Orders (or the cross-repo plan), then stop at GATE-PLAN. Also `/tempo:feature --plan-only ...` |
| `/tempo:feature --auto <request>` | Autopilot: TEMPO takes its own recommendation at every gate and escalation and stops only where Jorge is truly needed (see below). Works on `/tempo:bug`, `/tempo:plan` and `/tempo:resume` too; `--no-auto` turns it off |
| `/tempo:plan --offline <request>` | Skip the base fetch and use the local base branch as it is. Without it every command first fetches the base and fast-forwards it, or stops (0.20.0). Works on `/tempo:feature` and `/tempo:bug` too |
| `/tempo:resume <task-id> [build \| answer]` | Continue a task from its last artifact, answer the question it is waiting on, or `build` a planned task |
| `/tempo:sweep [--yes] [task-id]` | List processes TEMPO or a coding session left running (emulators, servers, watchers, Java stacks), with memory and age, and stop the ones you pick (0.17.0) |
| `/tempo:report [--task <id>] [--dry-run] <what went wrong>` | File a GitHub issue on the TEMPO repo about something TEMPO just did wrong, with the run's state, artifacts and transcript path attached; the task keeps going (0.19.0) |
| `/tempo:dash [stop \| status] [folder]` | Start the local, read-only dashboard of running and recent tasks and print its URL; `stop` ends it (0.22.0) |
| `/tempo:init [repo\|workspace] [notes]` | Write or update the TEMPO config for a repo or a multi-repo workspace, detected from the code |

Everything for a task lives in `.tempo/<task-id>/` in the target repo. The task ID is the ticket key when the request names one (`AV-5696`), else `T-NNN`. A `T-NNN` id is local: each machine numbers its own tasks, so it never appears in a branch, commit, PR, issue or tracker (0.11.0). `tempo_state.py claim` hands out the id with an atomic mkdir, so tasks started in parallel never share one (0.17.1). TEMPO adds `.tempo/` to `.git/info/exclude`, so artifacts and config never show up in the diff.

## Several repos (workspace tasks)

Run a command from a folder that holds several repos and has `.tempo/workspace.yaml`. TEMPO then:

1. Triages the request against the workspace's repo list.
2. Sends one CROSS-REPO scout per candidate repo, then the architect writes `plan.md`: one slice per repo, typed dependencies (blocks-start, blocks-merge, blocks-validation) and external blockers.
3. Stops at GATE-PLAN.
4. Runs one child task per repo (`<repo>/.tempo/<task-id>/`), each ending in its own PR, and keeps `tracker.md` in the workspace task folder up to date. Children start together unless a blocks-start edge orders them. An S or M slice goes straight to Work Orders from the plan slice; only an L slice, or one with an open decision, runs its own triage, explore and spec.
5. Runs a joint QA across the task branches with the workspace's `validation.steps`, then hands over every PR link.

Only blocks-start orders the work; see `skills/triage-rubric/SKILL.md` §5.

## Task state

`skills/orchestrator/scripts/tempo_state.py` is the only writer of `.tempo/<task-id>/state.json` and the `state.md` rendered from it. It stamps the stage log with this machine's clock, keeps loop counters and work orders, and records agents in flight with their saved prompts, so `/tempo:resume` can restart them after a session restart. Each command holds a lock on the task's `.state.lock` from its read to its write, so commands that run in parallel never lose each other's change (0.23.0). Tasks started before 0.3.0 are converted with `tempo_state.py adopt <task-dir>`.

## Teardown (0.17.0)

A task cleans up after itself. Every process TEMPO starts, through `tempo_run.py` (tests, builds, targets) or `tempo_procs.py start` (dev servers, the app for QA, emulators, watchers, docker stacks), is marked with the task and the session in its environment, so its children are found too, even ones a helper starts with nohup. `tempo_state.py` tears the task down by itself: services stop when the task waits on Jorge, and everything stops when the task is DONE, FAILED or ABORTED. A SessionEnd hook stops what a closed session's tasks started. When a run's command ends, anything it left running is stopped and named in its summary (Gradle and Kotlin daemons stay until teardown). In a TEMPO session the `guard_spawn.py` hook denies `nohup`, `setsid`, `disown`, a trailing `&` and `run_in_background`, and names the `tempo_procs.py start` line instead. Only marked processes and the ones recorded in `procs.json` are ever stopped. `/tempo:sweep` finds leftovers machine-wide, including unmarked orphans that look like dev tooling, and stops only what you pick.

## Dashboard (0.22.0)

`/tempo:dash` serves one local page for every TEMPO task on this machine that is running, waits on Jorge or changed in the last 24 hours. For each task it shows the stage and status, the stage log, the agents (in flight and finished, with their model), the test and build runs, the long-lived processes, the question the task waits on, QA progress, the verdict of each document, and the documents themselves.

- Start: `/tempo:dash`, or `python3 skills/orchestrator/scripts/tempo_dash.py start [--port N] [--root DIR ...]`. It prints `DASH: http://127.0.0.1:4310/`. Stop: `/tempo:dash stop`. The server outlives the session until then. `--root` adds a folder of checkouts whose `.tempo/` tasks are not in the registry (`~/.cache/tempo/tasks`), such as tasks copied from another machine.
- It changes nothing. It reads each task's `state.json`, `events.jsonl`, `procs.json` and documents. `tempo_state.py` appends one line to `events.jsonl` for every state change, and `tempo_run.py` one line per run; the orchestrator and the agents do nothing extra. Both state files are now written through a temp file and a rename, so a reader never sees half of one.
- Local only: the server listens on `127.0.0.1`, answers GET only, refuses a request whose Host is not `127.0.0.1` or `localhost` (or a name passed with `--allow-host`, such as your `*.ts.net` name behind `tailscale serve`; the page has no login, so anyone who can reach that name can read it), and serves only document types inside a listed task folder. A process row never carries its command line, which can hold passwords, and the files that repeat it (`procs.json`, `procs.log`, the service logs under `procs/`) are never listed or served. A run's label is its command unless `--label` names it, and the page shows the label.
- A task started before 0.22.0 has no `events.jsonl`. It shows its state, documents and the agents still in flight, and no finished agents or runs.
- Tests: `python3 -m unittest discover -s tests -v`.

## Lanes

| Lane | Production files | Stages | Rough time |
|---|---|---|---|
| S | 1–3 | Work Order from the Task Card → Build → correctness review → PR | ~10 min |
| M | 4–8, one area | 2 scouts → spec (+ Work Orders in one architect call) → Build → correctness + spec review → QA → PR. A pattern task, one that copies a sibling feature, skips the order check, gets the correctness review only, and QA checks what no test covers | ~25 min |
| L | more than 8, new design, schema or dependency | 3 scouts → spec → pre-check → spec gate → parallel Build → 3-lens review → QA → PR | 60+ min |

Triage sizes from the request; Explore re-sizes from the files it actually found. In S and M the architect runs on Sonnet, and so do reviewers on diffs of 150 lines or fewer and the verifier on 3 candidates or fewer; L keeps Opus. The spec pre-check runs in L, and in M only when the spec has a state model. The verifier is skipped when reviewers found nothing (or only LOW items). A small MEDIUM/LOW fix goes straight back to the builder (mode FIX) without re-amending the spec.

## Project docs

`docs:` in the config tells TEMPO where the project's own documentation lives: folders, files, globs or `re:` regexes, at the workspace level and per repo. `tempo_config.py docs` lists the files. Scouts read the index and the docs for their lens before searching, the architect follows the ADRs and conventions, reviewers treat rule-stating docs as rules (with `docs.rules: true`), and QA reads the QA harness or runbook. See `skills/config/SKILL.md` §2.6.

## Config

YAML, checked against `skills/config/schema/tempo-config.schema.json`. Later files win:

1. `skills/config/defaults.yaml` (built in)
2. `<workspace>/.tempo/workspace.yaml`: shared defaults, named toolchains, and the repos of a multi-repo workspace with their `depends_on` order
3. `<repo>/.tempo/config.yaml`

```bash
uv run skills/config/scripts/tempo_config.py --repo <repo> check      # validate
uv run skills/config/scripts/tempo_config.py --repo <repo> resolve    # merged result
uv run skills/config/scripts/tempo_config.py migrate <repo>/.tempo/config.md > <repo>/.tempo/config.yaml
```

See `skills/config/SKILL.md` for every key and subcommand. A legacy `.tempo/config.md` still works and is converted on the fly with a warning.

## Where Jorge is needed

Three gates: clarify a vague task, approve the spec (L lane, or M with open decisions), review and merge the PR.
Seven escalations: bug won't reproduce, fix changes intended behaviour, a builder decision that changes the goal, a review or QA loop past 3 rounds, a fix chain (two review rounds in a row whose findings were caused by the last fix), anything hard to undo, a missing source (the ticket says to follow a linked ticket, attachment, design or asset TEMPO cannot open).
Every stop comes with a recommended answer, so "yes" is always enough.

### Autopilot (`--auto`, 0.9.0)

With `--auto` on a command (or `task.autopilot: true` in config), TEMPO says "yes" for Jorge wherever its recommendation is grounded, and keeps going. It still stops for:

- a clarify question triage marks NEEDS-JORGE (the outcome is missing, or nothing in the code gives an option to recommend);
- a bug that won't reproduce, a fix that changes intended behaviour, a builder decision that changes the goal;
- anything hard to undo (new dependency, data migration, secrets, deploys, force-push, deleting branches);
- a missing source (0.13.0): the request or ticket says to follow something TEMPO cannot open (a linked ticket, its attachments, a design or prototype version, a doc, an asset). A stand-in it could pick (an older version, another brand's file, a drawing of its own) is not a recommendation;
- a second fix chain in the same task, and any open decision with no recommended option;
- the PR, which Jorge reviews and merges as always.

Spec approval, the workspace plan, clarify questions with a recommendation, loop limits and the first fix chain are accepted on their recommendation. Each one is logged with `tempo_state.py decide` into `.tempo/<task-id>/decisions.md`, and SHIP copies the list into the PR body under the assumptions, so Jorge reviews them at the PR. `/tempo:plan --auto` still stops at the plan (the plan is the deliverable) and remembers autopilot for `/tempo:resume <task-id> build`.

## Layout

```
.claude-plugin/
  plugin.json                 plugin manifest (listed in the repo root's marketplace.json)
commands/
  feature.md  bug.md  plan.md  resume.md  init.md  cleanup.md  verify.md  sweep.md  report.md  dash.md
agents/
  triage.md        classify, clarity check, size, route → task.md
  scout.md         read-only explorer, one lens per instance → merged into context.md
  investigator.md  user feedback → hypotheses.md
  reproducer.md    failing test + root cause → repro.md
  architect.md     spec.md, then wo-NN.md Work Orders (or stacked slices), and amendments
  builder.md       one Work Order: preflight, stop-and-ask check, then test-first build → report-NN.md
  integrator.md    merge WO branches, full suite → integration.md
  reviewer.md      one lens: correctness | security | spec | spec-precheck → review/<lens>-rN.md
  verifier.md      drop, dedupe, rank, assign → findings-rN.md
  qa.md            per acceptance criterion, with evidence → qa-rN.md
hooks/
  guard_push.py    refuses pushes of local tempo/ branches
  guard_spawn.py   in a TEMPO session, refuses detached starts (nohup, &, setsid, run_in_background) and kills by name (pkill, killall)
  check_update.py  at session start, says when a newer TEMPO is on GitHub main and gives the update commands
  hooks.json       the hooks above, plus SessionEnd teardown
skills/
  orchestrator/              the stage machine the commands run (gates, loops, worktrees, PR, workspaces)
    scripts/tempo_state.py   the only writer of state.json / state.md; tracker for workspace tasks
    scripts/tempo_branches.py  deletes local work-order and repro branches the task branch already holds
    scripts/tempo_run.py       runs one test, build or lint command; prints a summary, waits for a heavy slot, stops what it left
    scripts/tempo_procs.py     starts and tracks long-lived processes, tears a task down, sweeps for leftovers
    scripts/tempo_report.py    collects a run's context and files a TEMPO issue (gh, or a prefilled link)
    scripts/tempo_dash.py      the dashboard's local, read-only server; serves scripts/dashboard.html
  document-standard/         the document shape + scripts/check_doc.py (structure check)
  artifact-templates/        one template per artifact in templates/
  triage-rubric/             clarity questions, task types, S/M/L lanes, routes
  review-rules/              rules files, review depth, the three lenses
  config/                    config schema, defaults, starters, scripts/tempo_config.py
    templates/REVIEW.md      starter REVIEW.md for a target repo
tests/
  test_dash.py     the dashboard server and the event log (unittest, standard library)
  test_run.py      stopping a run, the kill guard, the heavy-slot decision, the KILLED line
  test_procs.py    who owns a process, the config helper, what a session's end marks as stopped
  test_state.py    the state lock, the QA counter, the SHIP entry, a state.json from 0.21.0
  test_config.py   a config from 0.21.0, gates.full_bars: verify (runs through uv; skipped without it)
```

## Document checker

```bash
python3 skills/document-standard/scripts/check_doc.py .tempo/T-001/*.md
```

It checks structure only: a known title line, every template section present and in order, no empty section, no leftover placeholder, no AC tag defined twice. It reads each document type's sections from its template, so editing a template changes the check. Exit 0 is PASS, exit 1 lists findings as `file:line: RULE: message`. Documents in the pre-0.6.0 ICAO layout are reported as LEGACY and pass, so older tasks can finish.

### Why not ICAO any more (0.6.0)

Up to 0.5.0 every artifact followed an aviation-style (ICAO) standard: numbered paragraphs, a DEFINITIONS section in every document, AMDT headers and amendment logs, SHALL/SHOULD capitals, a vague-word lint and a separate builder readback pass. Measured on the xipp runs of 24 to 26 Oct 2026 (20 task folders), definitions, numbering and amendment logs were about 24% of all handoff text, readbacks found a real issue in 4 of 34 cases (all plain builder questions), and none of the 41 review findings traced back to wording. 0.6.0 keeps the parts that did work (fixed sections, AC/F tags, concrete paths and commands, PASS/FAIL lines, the spec state model) and drops the rest. The builder now stops before its first edit when the order is unclear, and the orchestrator checks scope from the diff. Evaluation: https://claude.ai/artifact/R9rqkre5FagHwuEvCyVGFE

### Large tasks and builder stops (0.7.0)

Measured on pod1um T-007 (27 Oct 2026, 0.6.0): 8 Work Orders chained one after another took about 3 hours of build, and 6 of 7 builders stopped on scope. Every stop was a test, fake or shared file missing from §3 IN, and none was a misreading, so dropping the readback did not hurt. The same two fakes stopped two orders in a row. On xipp the same plugin ran fast because the workspace flow cut features into per-repo tasks of 1 to 2 orders. 0.7.0 brings that cut to a single repo and removes the stops:

- **Split.** Past `limits.split_orders` orders (default 4) or `limits.split_criteria` criteria (default 30), Handoff cuts the task into stacked slices of 1 to 3 orders (orchestrator §9). Each slice builds and gets its own short review; slice n builds while slice n-1 is in review. One QA and one PR at the end.
- **Dependents in scope.** Handoff greps for importers, fakes and tests of every type an order changes and puts them in IN. Builders may also edit a test file, test double or fixture in a package they already own without stopping, listed under Deviations; the scope check accepts it.
- **Scope fixes carry forward.** An amendment after a BLOCKED report is applied to every later order that needs it, in the same architect call.
- **Preflight.** The next wave's builders check their orders against the code while the current wave builds, so questions are answered before their turn.
- **Dependency kinds.** `WO-nn (start)` orders build in sequence; `WO-nn (order)` orders build in parallel and the integrator stacks them. A serial chain is fast-forwarded between waves, with one integration at the end.
- **Spec slices.** When the Spec passes `limits.spec_slice_kb` (default 30), each order carries the terms and design lines it uses.
- **Feasibility pre-check.** The spec pre-check flags a criterion that needs a file the Spec forbids, and plan items silently dropped.
- **State.** The stage log records start, end and minutes; work orders show their build time; logging an artifact clears the agent that wrote it and the Next action.
- **Explore.** Each scout reply is saved to `explore/<LENS>.md` when it arrives; a failed scout is retried once.
- **Standing decisions.** `task.standing_decisions` in config are answers Jorge has already given; triage applies them instead of asking.
- **Safety.** Builders delete only what they made, and the orchestrator writes prompts with the Write tool, never a heredoc.

Known cost: a builder's test-file allowance means two parallel orders may touch the same fake. The integrator resolves the conflict, or returns it to an order.

### Fewer fix commits (0.8.0)

Measured on pod1um PR #203 (T-007, 0.6.0): 7 feature commits, then 12 fix and 2 docs commits. All 14 were real defects: 2 from the screen check, 9 from review round 1, 3 from round 2 (each caused by a round-1 fix). Three of them, two HIGH, were already flagged in the builders' own reports. Six came from lock and retry behaviour the spec stated but never tested, four from tests that ran on the VM only or skipped edge inputs, and four from repo rules the builders never saw. 0.8.0:

- **Fixes fold into their commit.** Before the PR is pushed, fixes are `fixup!` commits of the commit they correct (`git.fold_fixes`, default on). At SHIP the integrator squashes them (mode FOLD), checks the tree is unchanged and that each commit still passes the cheapest check, or ships unfolded with a note. After the PR is open, fixes are plain commits.
- **Deviation gate.** Report deviations carry a tag: MECHANICAL, SCOPE, CRITERION, CONTENT or CUT. The last three go back to the architect before the next wave. Builders stop instead of meeting a criterion partly or inventing user-facing words.
- **Order check.** After each order builds, a sonnet reviewer checks its diff (lens ORDER: correctness with edge inputs, the order's criteria as worded, its rules, its deviations). The same builder fixes HIGH and MEDIUM findings before the order integrates (`limits.order_check`, M and L lanes).
- **Specs prove their claims.** The §8 state model covers client state (write queues, optimistic updates, drafts) and concurrent writers, with failure classes (no network, refusal, 429, 5xx, user leaves) as events. Every concurrency promise in §4 is a criterion tested in both orders; the pre-check checks lock claims against foreign keys and indexes. Copied code is checked against §8 too.
- **Platform targets.** `targets:` in config lists extra test runs (e.g. Flutter on Chrome) with the paths they cover. Orders that touch those paths verify on them, and the integrator runs every target the diff touches.
- **Rules reach the builder.** Each order's §3 carries `RULES:` lines from CLAUDE.md, REVIEW.md and rule-stating docs; builders check their diff against them. Spec-wide rules (labels on every control, translated strings) become a test in each order that adds such a thing.

Known cost: the order check adds about 5 to 10 minutes per order. On T-007 that is about 1 to 1.5 hours against the 1h45m its two fix rounds took.

### The rm guard stops asking (0.9.1; removed in 0.21.0)

Up to 0.8.0 the guard turned every `rm` outside the session's working directory into a permission prompt. That caught Claude scratchpads (`/private/tmp/claude-501/...`), `/var/folders` temp files that were not `tmp.*`, `.tempo/<task>` files removed from inside a worktree, and every non-TEMPO session with the plugin installed, so Jorge had to step in far more than the risk warranted. Now it never prompts:

- **Allowed silently:** anything in the project (the main checkout and all its worktrees, found through `git rev-parse --git-common-dir`) and anything under `/tmp`, `/private/tmp`, `/var/folders` and `$TMPDIR`.
- **Refused, with a reason the model reads:** the project root itself, its `.git`, the home folder, `/`, a temp root itself, and any other path. The reason tells the agent to leave the path, carry on and name it in its report, not to ask.

Known cost: a stray delete inside a temp folder is no longer caught, and a delete you actually wanted outside the project (another repo, `~/Library/Caches`) is refused; run it yourself.

### Faster integration, fewer fix-of-fix rounds (0.10.0)

Measured on pod1um after 0.8.0 (T-008 to T-014, 28 Oct): seven PRs with no review fix commits, six of seven passing review in one round. The time went elsewhere. The web target ran the whole Chrome suite, which fails on develop (about 90 failures), so integrators reran it on the base and compared names by hand: 40 to 72 minutes on small bugs, against 10 to 23 when they ran only the touched tests. Four of seven worktrees lacked the git-ignored `.fvm/flutter_sdk` link. On T-007, fixing an external review's 4 MEDIUM findings by the small-fix path caused 4 new ones, two in the settling state model. 0.10.0:

- **Scoped platform targets.** A target's `scoped_command` (`cd {package} && flutter test --platform chrome {tests}`) runs only the changed test files and the tests that mirror changed files, one run per package. Changed files no test maps to are listed, not run. The whole suite runs only when a change touches the target's own setup.
- **Advisory targets and baselines.** `advisory: true` marks a target that is red on the base. The integrator records the base's failures once per base commit in `.tempo/baselines/` (`tempo_baseline.py`) and only NEW failures block; a NEW failure that passes alone is a flake.
- **Worktree gaps caught early.** `tempo_config.py check` warns about git-ignored setup files (`.fvm`, `.env`, `local.properties` ...) that `worktree.link`/`copy` do not cover; the orchestrator adds them before the first worktree, and every worktree (order, repro, integration, base check) gets the same setup.
- **State fixes go through the architect.** The verifier tags each finding `Fix kind: LOCAL | STATE`. A STATE fix (who owns a state, what changes it, when it settles) skips the small-fix path: the architect writes the §8 lines first. A round with 2 or more findings introduced by the last fix raises FIX-CHAIN at once.
- **Findings after the PR are a round.** An external review or PR comments go into `findings-ext-N.md` and follow the same routing, count and limits (orchestrator 3.10.7).
- **Tests that never run.** The correctness lens flags a new test that no configured command or target runs (a `@TestOn('browser')` file with no Chrome target).
- **State tidy-up.** A stage that redoes its artifact keeps one log entry; DONE clears agents left in flight; an order rebuilt after DONE shows its runs separately.

0.10.1: a scoped run picks only files a runner runs (`*_test.*`, `*.test.*`, `*.spec.*` ...); a changed helper or fixture in a test folder is listed as NO-TESTS instead of being passed to the runner.

Known cost: a mirror-name match misses tests named differently from their source; those changes show as `# NO-TESTS` and rely on the order's own verification.


### Local task ids stay local (0.11.0)

A second machine running TEMPO on pod1um numbers its own tasks, so `tempo/T-004`, `fix(T-010): ...`, `T-015: merge WO-03` and issue text naming `T-015` meant nothing there, and a branch could collide with that machine's fourth task. 0.11.0:
- `names` takes `--ticket` and `--slug` and never uses the local id. With no ticket, branches carry a slug of the request (`tempo/fix-safari-export`, with `-2` when that name is already taken locally or on a remote), and the commit and PR templates drop the empty ticket with its brackets (`{type}({ticket}): {summary}` → `{type}: {summary}`). Defaults are `tempo/{ticket}` and `{type}({ticket}): {summary}`; `{task}` in old configs now means the ticket too.
- `check` fails a commit or PR title template that holds a `T-NNN` id. `{scope}` is documented as the code area, never the task id.
- `task.ticket_pattern` may have a capture group: `(?:#|/issues/)(\d+)` makes GitHub issue `#215` the ticket `215`.
- Orchestrator 1.6.1, builder 8.0 and the integrator's merge message keep `T-NNN`, `WO-NN`, `ESC-N` and `.tempo/` paths out of branches, commits, PR text, review replies, issues and trackers. SHIP checks the outward text before it pushes.

### Work branches are deleted after SHIP (0.12.0)

SHIP used `git branch -d` on the work-order and repro branches. `-d` compares with the checked-out branch (the base, e.g. `develop`), which never has those commits until the PR merges, so every run ended with "git refused to delete tempo/...-wo-NN" and the branches piled up. 0.12.0:
- `skills/orchestrator/scripts/tempo_branches.py prune` checks each branch against the task branch itself and deletes it with `-D` only when the task branch holds its work: its tip is merged, every missing commit has an equal patch there (`git cherry`), or it was folded (its tip is in an earlier tip of the task branch, from the reflog or the integrator's new `FOLD ... FROM: <hash>`, whose tree the task branch still has).
- It never deletes the task or base branch, a branch checked out in a worktree, a branch with an upstream or a same-named remote branch, or a branch with commits the task branch lacks; those print `KEPT` with the reason. Remote branches are never touched.
- `/tempo:cleanup` sweeps leftovers from earlier runs for every task at DONE: a dry run first, then deletes after Jorge says yes.

### Autopilot stops for missing sources (0.13.0)

AV-6033 in xipp ran with `--auto`. The ticket said every item follows AV-6018's descriptions, images and assets, and the C6 v25 and +Família v14 prototypes. AV-6018 returned 404 to TEMPO's Jira account and v14 was nowhere on disk. Autopilot logged "use the older local +Família prototype and the C6 extracts" as decision D-3 before triage and carried on, and the architect was told every open decision must name a recommendation. Jorge had to step in. Autopilot stopped only when no option existed, and a stand-in is always an option. 0.13.0:
- Orchestrator 1.3.3: before triage, list every source the request and ticket name and try to open each. Another version or brand's file counts as MISSING. Triage writes them in Task Card §4 Sources and turns each MISSING one the work depends on into a `NEEDS-JORGE MISSING-SOURCE` question (rubric 2.9), so GATE-CLARIFY stops, on autopilot too.
- New escalation MISSING-SOURCE (4.1, 4.5.1) for sources found missing later: scouts report `MISSING SOURCE:` lines, the architect writes `Recommended: NIL. MISSING-SOURCE <source>` instead of choosing a stand-in (orchestrator 2.4). Options: Jorge shares it, names the stand-in per item, or drops those items.
- 4.5.1.1: an option existing is not enough to accept a stop; a stand-in for a named source is never a decision.
- `tempo_state.py decide` refuses the kinds autopilot never accepts and a question that reads like a missing source ("not found", "404", "no access", "only an older version"). `--not-a-source "<why>"` lets through a missing local file that is not a source of truth, such as a git-ignored SDK link.

### Pushed branches follow the repo's convention (0.14.0)

Up to 0.13.0 the task branch defaulted to `tempo/{ticket}`, and it is the branch that gets pushed and opens the PR. pod1um's remote filled with `tempo/5`, `tempo/T-007` ... and a config that fixed `feat/{ticket}` (xipp) put bug fixes on `feat/` too. Jorge's rule: `tempo/` names never reach git; pushed branches use Conventional Commits types or the repo's own convention. 0.14.0:
- Default `git.branch` is `{type}/{ticket}`. The orchestrator picks the type (orchestrator 1.6.3: `feat`, `fix`, `chore`, `docs`, `refactor` ...) and passes `names --type`. New `git.branch_types` maps a type to the repo's word (`{feat: feature, fix: bugfix}`).
- With no branch setting in any config file, `names` reads the type words from the remote branches (`story/`, `bugfix/` ...; `tempo/` ignored) and prints `branch_convention`. A CONTRIBUTING or docs branch rule wins and is written into the repo config (orchestrator 1.7.1).
- `tempo/` now marks local work branches only: work orders are `tempo/{branch}-wo-{nn}`, repro `tempo/{branch}-repro`. `check` fails a `git.branch` under `tempo/`, `names` refuses to make one, and a `feat/{ticket}`-style fixed prefix warns.
- New hook `hooks/guard_push.py` denies any `git push` whose destination is under `tempo/` (named, `HEAD`, a bare push from a `tempo/` branch, `--all`). Deleting a remote branch is allowed.
- A task started before 0.14.0 with a `tempo/` task branch is renamed before its first push (orchestrator 3.12); if already pushed it keeps the name and Jorge is told.
- `tempo_branches.py prune` and `sweep` match the new `tempo/...` names and the pre-0.14 ones; new `pushed` lists `tempo/` branches already on a remote (report only). `/tempo:cleanup` shows them.

### Less waiting on tests (0.15.0)

On 2026-10-29, pod1um #64 ran 10.5 hours in 8 slices. Builders spent 4.5 of their 7 active hours inside tool calls, almost all of it running or waiting on tests; in xipp AV-6033, QA spent 1.8 of 1.9 hours the same way. The builder chain is the critical path, so that is where a task feels slow. Causes: every Work Order listed the whole client suite and the advisory Chrome target; Chrome was re-baselined for every slice (S-7's integrate spent 56 of 66 minutes on it); long commands passed the Bash tool's 2-minute default, went to the background and were polled in 3-minute `sleep` loops; agents waited on each other's suites with `pgrep`; and every fix round re-ran the full bars. Jorge also had to stop scope creep mid-spec, asked "Still going?" during a 97-minute QA, and #64 met a 210-file develop drift only at its last rebase. 0.15.0:
- Builders run scoped tests only. The architect never puts the full test command or an advisory target in an order (architect HANDOFF 7, 7.1), the orchestrator returns an order that has one (3.7), and builders do not get the full test command (5.2.1). The whole suite is the integrator's and QA's.
- New `tempo_run.py`: every test, build and lint command runs through it, in the foreground, with the Bash `timeout` at 10 minutes. It prints exit, time, failure lines and the tail, and keeps the output in a private log. `--heavy` (whole suites, targets, app builds) waits for one of `TEMPO_HEAVY_SLOTS` (default 1) machine-wide slots itself. Agents never background a run and poll it, never wait on `pgrep`, and never write fixed `/tmp` paths.
- Advisory targets run once per task, at the FULL integrate after the last wave or the parent integrate of a split task, against one baseline on the task's base commit (orchestrator 3.9, 9.6). Not in slices, earlier waves, orders, fix rounds or QA.
- Fix rounds integrate with NARROW bars: the fixed packages' tests, build and lint (integrator 5.0.1). A task whose last integrate was NARROW and that has no QA gets one FULL integrate before SHIP.
- Ticket scope by default: a criterion cites the request, ticket or named source it comes from, or what it is needed for; what the code merely suggests goes to Spec §7 as a follow-up (architect 5.1). The spec pre-check raises MEDIUM for anything untraceable (reviewer 4.0.4).
- Before an agent likely to run 20 minutes or more, the orchestrator tells Jorge what it does and roughly how long (2.6.1). QA writes `qa/progress.md` per criterion, which answers status questions (2.6.2).
- Base drift: before the last-wave integrate and each slice's integrate, the orchestrator fetches the base; when it changed files the task changed, the new integrator mode REBASE moves the unpushed task branch onto it then, not at the end (3.9, 9.4.1).
- State: a split parent sits in stage SLICES while the slices run, so HANDOFF no longer absorbs their time; each child line in §9 shows its time; BUILD is logged per wave and per slice; `log` closes every scout at EXPLORE and the round's reviewers at REVIEW, and warns when the logged stage is not the current one; `agent start` refuses a label or output with an unfilled part (`scout-`, `explore/.md`).
- Smaller: reviewers read with `git show`/`diff`/`grep` and run at most one test file, never a suite or a new worktree; QA makes worktrees only under `git.worktree_root`; the integrator reuses its `-int` worktree and skips the bootstrap unless a lockfile changed; work-order and repro branches default to `tempo/{name}-wo-{nn}` (`{name}` = the task branch without its type word), and prune matches both the new and old names. `/tempo:init` offers to raise `BASH_MAX_TIMEOUT_MS` when one command needs more than 10 minutes.

### Unit tests per change, full runs when chosen (0.16.0)

On 2026-10-29, after 0.15.0, five tasks ran at once and Integrate took 45 to 96 minutes against 6 to 70 of Build. Integrate had logged 67 rounds with no failure across both projects, and the Chrome target no real catch in its kept reports, while review failed 28 of 86 rounds. Subagent commands were still moved to the background at 3 minutes, a harness cap that no `timeout` lifts, so agents kept polling. AV-6004 showed the other cost: review rounds, not tests. Report: https://claude.ai/artifact/XEVu3g95UqrL9CwpZGbJCB. 0.16.0:

- Full bars at a chosen point. `gates.full_bars: on_demand` (the default): Integrate runs NARROW bars, the touched packages' tests, build and lint. The full suite runs for a critical change, for a change to `gates.full_paths` (lockfiles, toolchain pins), and on the new `/tempo:verify`. The PR body says when it did not run. `<cfg> bars` decides. `full_bars: integrate` restores the old behaviour. `full_bars: verify` (0.23.0) never runs it inside a task: see 0.23.0 below.
- Targets take `run: routine|critical`; an advisory target defaults to critical, so a routine task starts no Chrome and no base comparison.
- `tempo_run.py` runs the command in a detached worker. Each call blocks up to 110 seconds; a longer run returns `RUNNING` with an ID for `tempo_run.py wait`.
- QA no longer runs the full suite: it cites the head Integrate proved.
- Heavy slots default to CPUs / 4. `worktree.setup` and the new `worktree.teardown` take `{worktree}`, for a per-task test database.
- Split tasks: each slice gets the order check and the correctness lens; the other lenses run once on the parent.
- Pattern tasks (triage-rubric §3.9): an M feature that copies a sibling skips the order check, reviews at QUICK depth, and QA skips what tests assert.
- State: workspace tasks log the children's time as REPOS, so JOINT-QA holds only QA.

### Teardown (0.17.0)

On 2026-10-30 Jorge's Mac reached 11.4 of 12.3 GB swap and a load of 48. The memory sat in orphans of coding sessions: a headless Android emulator a TEMPO QA agent started with nohup (8.3 GB, 17 h), five Java services (3 GB), two `nest --watch` (1.9 GB, 42 h), and `tail -f /dev/null` keep-alives whose worktree was gone. `qa.md` already said to stop what it started, and nothing enforced it. 0.17.0 adds the teardown described above: marks on every process TEMPO starts, a `procs.json` ledger with stop commands, teardown run by `tempo_state.py` at every wait and every end (DONE, FAILED, the new ABORTED), a SessionEnd hook, per-run leftover cleanup in `tempo_run.py`, the `guard_spawn.py` hook, and `/tempo:sweep`. Orchestrator section 10.

### Parallel task ids (0.17.1)

On 2026-11-02 Jorge started two tasks at once in one project and both took `T-001`: the orchestrator picked "the next free number" by looking at `.tempo/` and made the folder itself, so both runs saw the same number free. `tempo_state.py claim .tempo` now reserves the folder with an atomic mkdir and prints the id, moving on to the next number when another session got there first; numbering continues after the highest `T-NNN` prefix, so slices and worktree folders keep their ids reserved. `claim --id <ticket>` reserves a ticket folder and exits 3 when it exists. Workspace children claim their repo folder the same way. Existing `.tempo/` folders need no change. `tempo_procs.register` writes its files atomically, which kept 30 parallel claims from crashing it.

### Question lines (0.17.2)

On 2026-11-02 a card in the TEMPO app blocked on a decision, and Jorge had to type his choice out by hand even though TEMPO had offered options. Every question for Jorge is now one line in a fixed form (document-standard §2.4): `- <id>: <question> Options: (a) ... (b) .... Recommended: <letter>, because <reason>.`, or `NEEDS-JORGE` instead of a recommendation. The Task Card §6, spec and plan decisions, and the builder's report §6 and PREFLIGHT questions all use it, so the app can show each option as a button. "(c) other" is no longer listed; Jorge can always answer in his own words.

### The TEMPO app over MCP (0.18.0; removed in 0.21.0)

The plugin now brings the TEMPO platform app's MCP server, `tempo-app`, so a Claude Code session can read boards and cards, see what needs Jorge, create cards and answer a blocked card's questions (app 0.7.0 or later). Set two environment variables where Claude Code starts, then restart it:

- `TEMPO_APP_TOKEN`: a token from the app's **Settings, API tokens**.
- `TEMPO_APP_URL` (optional): the app's address without `/mcp`, default `http://127.0.0.1:4310`; use the Tailscale `https://<mac>.<tailnet>.ts.net` address from another machine.

The server is a small bridge (`mcp/tempo_app_bridge.py`, python3) that passes messages to the app. Without a token, or when the app does not answer when Claude Code starts, it starts with no tools, so nothing shows as an error and the rest of the plugin works as before (0.18.1; 0.18.0 errored when the token was missing).

### Report a TEMPO problem from a run (0.19.0)

When TEMPO does something it should not mid-run, `/tempo:report <what went wrong>` files an issue on this repo (the `repository` in `plugin.json`, or `$TEMPO_REPORT_REPO`) labelled `tempo` and `bug`. With no words it takes the latest misstep in the session. The issue holds what happened with quoted lines, what was expected, the command, agent or skill section that governs it, the impact, a guessed fix, and the context `tempo_report.py context` collects: plugin version, machine, repo and branch, the task's state and `state.md`, its artifact list, other recent tasks and the session transcript path. The task folder's documents are copied to `~/.cache/tempo/reports/<stamp>/` so the evidence outlives `/tempo:cleanup`. It files with `gh issue create`; when gh is missing, signed out or fails, it saves the body and prints a prefilled new-issue link. `--dry-run` shows the body without filing. Reporting is not a gate: the task carries on.

### Fresh base before every run (0.20.0)

On 2026-11-03 a `/tempo:plan --auto` in xipp (AV-5703) scouted and planned on the local `develop`, which sat at a commit from 2026-10-29, 51 commits behind `origin/develop`; 18 of the files the plan relied on had changed. Nothing fetched before Explore (the only fetch was the base-drift check at Integrate), so the plan was thrown away. 0.20.0:
- New `skills/orchestrator/scripts/tempo_base.py sync --repo R --branch B`: fetches the base from its remote and fast-forwards the local branch (moves the ref, or `merge --ff-only` in the worktree that has it checked out). It never resets, rebases, stashes, merges or pushes. It stops with the reason when the fetch fails, the local base has unpushed commits (ahead or diverged), or the checkout cannot fast-forward. A repo with no remote uses its local branch.
- Orchestrator 1.3.0: every run syncs the base before triage and before claiming a task folder; a STOP ends the run there, on autopilot too, and Jorge is told what to do. The recorded base commit is the synced head. Workspace tasks sync every repo first (6.1.1), report every STOP at once, and write `bases.txt` for the scouts; each child syncs again when it starts (6.6.4).
- When the repo's checkout is not the base head (another branch checked out), scouts, the investigator and the architect read a detached base worktree instead of the checkout (1.3.0.3). Jorge's checkout is never switched.
- `/tempo:resume` syncs before continuing and records a new base for a task that has not reached BUILD; resume-to-build (3.14) and `/tempo:verify` on the base branch sync too.
- `--offline` on `/tempo:plan`, `/tempo:feature` and `/tempo:bug` skips the fetch on purpose.

### No app MCP, no rm guard (0.21.0)

- The `tempo-app` MCP server (`.mcp.json`, `mcp/tempo_app_bridge.py`) is gone: the TEMPO app's board no longer exists, and TEMPO runs from the plugin's commands and skills only. `TEMPO_APP_TOKEN` and `TEMPO_APP_URL` are no longer read.
- The `guard_rm.py` hook is gone. It refused deletes runs needed far more often than it caught a delete that mattered, and no stray delete was ever unrecoverable. Builders still delete only what they made (`agents/builder.md`). The push and spawn guards stay.

### Dashboard, cancelling a run, no kill by name (0.22.0)

- New `/tempo:dash` and `tempo_dash.py`: the local page described under Dashboard. `tempo_state.py` and `tempo_run.py` append to `<task>/events.jsonl`, which gives the page finished agents and runs with times to the second. `state.json` and `state.md` are written through a temp file and a rename.
- New `tempo_run.py stop <ID>`: ends one run, its worker and the command's process group, and nothing else. Until now a run could not be cancelled.
- `guard_spawn.py` refuses `pkill` and `killall` in a TEMPO session and names `stop` instead. On 2026-11-11, with four tasks running on one Mac, a builder ran `pkill -f flutter_tester` to cancel its own test run; two seconds later the commands of three other tasks' agents ended with exit 137 and their sessions stopped. The link is not proven, but a kill by name on a shared machine is wrong either way. `kill <pid>` stays allowed, and `TEMPO_ALLOW_KILL=1` in the command lets one through when Jorge asks for it.
- Tests for all of it: `python3 -m unittest discover -s tests -v`.

### Test load and safety (0.23.0)

A read of two story runs (POD-11 and POD-12, many subtasks at once on one Mac) showed test time lost with no stage at fault. The main session had written `--heavy` as the generic run line in 151 of 619 prompts, so one-minute runs queued behind whole suites: 175 to 414 minutes on POD-12. The QA counter was 0 in 62 of 65 tasks that had a QA report, because nothing bumped it. 0.23.0 changes no default and no stage:

- The script decides the heavy slot. With `--task` and a config it can read, `tempo_run.py` gives a slot to the whole test command and to a target's whole command (also when it is one `&&` part of a longer line, or behind `fvm`), and never to test-one with test files, typecheck or lint, whatever the flag says. For anything else (a target's scoped line, an app build, an unknown command) the caller's `--heavy` decides, as before. A whole suite spelled differently from the config is not recognised.
- `gates.full_bars: verify`, opt-in: the whole suite never runs inside a task, critical or not. `<cfg> bars` prints `BARS: NARROW` and, when the suite was owed, a second line `DEFERRED: critical change` or `DEFERRED: gates.full_paths matches ...`. The orchestrator then calls `<cfg> targets --scoped-only`, which prints scoped runs only, and `name<TAB># DEFERRED whole suite` for a target that has none. The PR body says the full suite was not run. It is meant for a story checkout, where the suite runs once on the story branch; a regression of a critical subtask is then found there, not in the task. The default stays `on_demand`: a lone critical task keeps its one full run at its final integrate. A config that names `verify` fails `check` on an older plugin, so keep it out of a tracked config until every machine is updated.
- A killed run says so. Exit 137 or 143, or a worker that died, puts `KILLED: signal <n>. Stopped from outside, not a test failure. Run it again once.` first in the summary. Builder, integrator and QA run the command again once and report BLOCKED when it is killed again. Every run that ends appends a `run-end` line to `events.jsonl`: exit, seconds, slot wait, load, killed, leftovers.
- Owner. `tempo_procs.py` takes the nearest Claude ancestor as the owning session and reads `TEMPO_OWNER` only when there is none (a detached worker), so a session started under a marked process owns what it starts. A session's end marks as stopped only the ledger rows that session owns.
- State. `tempo_state.py` holds a lock on `<task>/.state.lock` from its read to its write and releases it before a teardown. `log` of `qa-rN.md` raises the QA counter to N, and on a FAIL at or past the limit prints `LIMIT: qa rounds N of L; raise LOOP-LIMIT` (exit 0). `set --pr` logs SHIP when the last log entry is not SHIP. DONE clears the next action unless `--next` comes with it. `state.json` keeps its shape: a task folder from 0.21.0 works as it is.
- Tests: `tests/test_state.py`, `test_config.py`, `test_procs.py`, and more cases in `test_run.py`.

### Native Windows (0.24.0)

The state, run and process scripts imported `fcntl` and called `killpg`, `/proc` and `ps`, so on native Windows a task stopped before Triage. The platform calls now sit in `tempo_os.py`; macOS and Linux keep the same calls as before.

- Locks: `msvcrt` byte locks on Windows, placed past the text so a slot file still says who holds it.
- Processes: commands start in their own process group with no console window, and leave Claude Code's job object where the job allows that. Bash commands go through Git Bash (`CLAUDE_CODE_GIT_BASH_PATH`, or the `bash.exe` next to `git`), not the WSL launcher. The process table comes from PowerShell (`Get-CimInstance Win32_Process`). Each process TEMPO starts gets its own named job object, which its descendants join, so stopping one runs `taskkill /T /F` on its tree and then ends its job: Git Bash's fork and exec leave children whose parent PID is gone, which the tree walk alone misses.
- Limits on Windows: no process exposes its environment, so nothing carries the task mark. Teardown, `stop` and the session's end find a service by its ledger PID and a run by its worker PID, and stop the whole tree and its job. A program started through an app execution alias (a Store or install-manager `python.exe`) leaves the job; it is still stopped while its parent lives, but not once its parent has exited. `/tempo:sweep` lists no LEFTOVER there, only SUSPECT orphans.
- Every text file the scripts read or write is UTF-8, whatever the code page, and so is every script's and hook's stdin and stdout.
- Paths the scripts print for an agent to paste back (run `ID:`, `LOG:`, `DIR:`, `STATE:`, the hook's suggested lines) use forward slashes, which Git Bash keeps.
- Checked on a Windows machine with the handoff in PR #11, and the unit suite runs there (FIFO and `pgrep` tests skip). `tests/test_os.py` checks the lock, the liveness probe, the Git Bash lookup and the Windows table parser on any machine, and the job kill on Windows.

### Update check (0.24.1)

- A SessionStart hook, `hooks/check_update.py`, compares the installed version with `plugin.json` on GitHub main. When main is newer it shows `claude plugin marketplace update jorgelrj-skills && claude plugin update tempo@jorgelrj-skills`. It gives up silently after 2 seconds, offline, or on any error.

### Several trackers and ticket sync (0.25.0)

- `task.trackers` lists every tracker a project takes tickets from (GitHub issues and Jira in one repo, for example), each with its own `ticket_pattern`. The ticket the request names first picks the tracker and becomes the task ID. The older `task.tracker` and `task.ticket_pattern` still work as a list of one; `check` fails a file that sets both forms.
- Opt-in `sync:` per tracker. `assign: true` and `start: <status>` assign the ticket to you and move it when the task starts building (after setup in a full run, or when a planned task is approved for build); `pr: <status>` moves it when the PR opens. Jira goes through atlassian-multi's `atl.py`; GitHub uses `gh issue edit` and the Status field of the Projects board in `project: <owner>/<number>` (gh needs the `project` scope). A tracker that refuses prints a `WARN:` and the task goes on. Child and slice tasks never sync; their parent does. Config skill 2.5.2 and 2.5.3, orchestrator 1.6 and 1.10.
- `tempo_config.py ticket` and `sync` do the work. `tests/test_config.py` covers the pick, the lint and the opt-out paths.

### Faster test step (0.26.0)

From the 2026-11-17 audit of pod1um runs (Mac and two Windows machines). Each touched package's whole test folder still runs once at the last integrate; a test-only fix round after it re-runs only the files it touched.

- **Scoped platform target once per task.** A target with `run: final` prints only with `targets --final`, which the orchestrator passes at the integrate after the last wave. Builders and QA never run target lines.
- **`tests.always` and `tests.slow`.**
  - `bars` prints `ALWAYS:` lines: guard tests that every narrow integrate runs, whatever packages the diff touches.
  - `bars` also prints `SLOW:` lines for slow test files the diff hits. Builders, WAVE integrates and QA run those files by `--plain-name` group. They run whole once, in the last integrate's package run.
- **Narrower integrates.**
  - WAVE integrates run the work orders' §5 tests, the mirror tests and the ALWAYS files, never a whole folder.
  - LAST (and a FIX that touches production code) runs each touched package's whole folder and `build`.
  - A test-only FIX runs those files and the package's typecheck.
- **Check roles.** Builders and WAVE integrates run `commands.typecheck` (one package, plus the packages that depend on a touched shared module). LAST, FULL and `/tempo:verify` run `build`.
- **QA reuses clean runs.** `tempo_run.py` prints `TREE: <sha> clean|dirty` and records `head` and `clean` in `run-end`. QA cites an integrator run only on the same clean head, and only one that passed. FULL, critical, verify, screenshot, docker-backed and golden runs are always re-run.
- **Critical belongs to the Task Card.** Under `gates.full_bars: verify`, `targets` prints no whole suite except with `--verify`, which only `/tempo:verify` passes. `tempo_state.py set --critical on` once the task has left TRIAGE needs `--gate '<Jorge's answer>'`. The architect replies `CRITICAL?:` instead of handing the call on.
- **Stalls and duplicates.**
  - `tempo_state.py watch --file F --agent ID` runs in the background beside each agent. It prints `STALL:` when nothing moves and no test runs, and `DONE:` when the agent finishes. `guard_spawn.py` allows it.
  - `tempo_config.py dupes` lists open PRs and live branches of the same ticket at claim time, before each integrate and before the first push. On a hit it stops and asks.
- **Run safety.**
  - `tempo_run.py` gives every run a default `--timeout` of 3 h.
  - The FAILURES hint prints only on a non-zero exit.
  - `tempo_run.py --task DIR status` lists the task's runs.
  - `check` warns when the repo path has a space, since melos splits it on Windows.
- **Sizing.** Locale and generated files don't count toward size. A lane-M task gets 1 or 2 work orders by default.
- **Not in this version:** the HIGH-only `fix_severity` (it needs the final read), a cache of passed runs, and a cap on concurrent runs (measure first).
- **Upgrade order.** A config that uses `tests:` or `run: final` fails `check` on 0.25 and older, so update every machine before such a config lands.
### Sweep before each run (0.26.1)

From PD-47 in pod1um: Flutter runs in a task worktree leave plugin sources under `build/ios/SourcePackages/` and an untracked `ios/Podfile`. The next run's pub resolution and `dart format` pick them up and fail, and every prompt had to tell agents to clear them by hand.

- **`worktree.before_run`.** `tempo_run.py` runs these commands at the root of a linked worktree before each command it runs, and before it records `TREE`. They never run in the main checkout or outside git.
- A step that fails prints `BEFORE RUN: exit <n>: <step>` in the summary. The command runs anyway.
- **Upgrade order.** A config that sets `worktree.before_run` fails `check` on 0.26.0 and older, so update every machine first.

### CI tier and CI-WAIT (0.27.0)

For a repo whose PR checks run the suites and an AI review, so a weak laptop runs only what proves the change. Every key is opt-in; a config without them runs as 0.26.0 did.

- **Light local tier, `gates.full_bars: ci`.** `bars` prints `BARS: LOCAL` and `DEFERRED: ci`. Every integrate runs the touched tests and their mirrors, the ALWAYS files, one typecheck of the touched packages and lint: no whole package, no build, no platform target, no baseline compare. The architect writes tests only CI can run as `CI` lines that nobody runs locally, and QA records their criteria as `CI`.
- **`commands.test_local`.** The test-one command for that tier, with the same placeholders, pointed at a runner that skips what only CI runs. Under `ci`, `cmd test_one` prints it.
- **`targets[].run: ci`.** A target only CI runs. Under `full_bars: ci` every other target prints `# DEFERRED to CI`; `/tempo:verify` still runs them all.
- **The machine file, `.tempo/config.local.yaml`.** Merged last, kept out of git, and read from the main checkout by a linked worktree that has none. A slow laptop sets `limits.max_parallel_builders: 1` and a `-j 2` in its own `commands.test_one`.
- **CI-WAIT, `limits.ci_rounds` above 0.** After SHIP the task does not end. `tempo_ci.py watch` (a background command the spawn guard allows by name) waits on `gh pr checks` and the PR state, up to an hour per call. On a red check, `tempo_ci.py collect` writes the failed jobs' log tails and the CRITICAL and HIGH findings of the `ai-review` artifact. These become `findings-ci-N.md`, which goes through the usual fix routing as plain commits, one CI round each, up to `ci_rounds`. A red check with no evidence is re-run once. A conflict with the base is merged in (integrator UPDATE), never rebased. Worktrees stay until `gh` reports the PR merged; then teardown, prune and DONE. Past the limit, or when the PR cannot move without a person, TEMPO raises CI-STUCK. TEMPO still never merges.
- **Tracker sync `merged`.** Moves the ticket when CI-WAIT sees the merge. Leave it unset when the repo's CI moves the ticket.
- **State and dashboard.** `tempo_state.py` knows the stage CI-WAIT, `init`/`set --ci-limit` and `bump ci`; the dashboard shows CI-WAIT under Ship. `/tempo:resume` on a CI-WAIT task starts the watcher again, and `ci-limit <N>` raises the limit.
- **Upgrade order.** A config that uses any of these keys fails `check` on 0.26 and older, so update every machine before such a config lands.

## How it runs inside Claude Code

- The main session is the orchestrator. Subagents cannot start other subagents, so the orchestrator starts every agent, including the parallel scouts, builders and reviewers.
- Each builder gets its own git worktree at `.tempo/worktrees/<task-id>-wo-NN` on the work-order branch (default `tempo/{name}-wo-{nn}`, `tempo/AV-1-wo-01` for `feat/AV-1`, local only), prepared by the config's `worktree:` steps. The integrator merges them into the task branch (`git.branch`, default `{type}/{ticket}` or the repo's own convention), which becomes the PR branch and is the only branch pushed.
- Models are set per agent in the frontmatter (`opus` for architect, investigator, reproducer, reviewer, verifier; `sonnet` for the rest). That is the L-lane default; the orchestrator passes `sonnet` for S and M stages (orchestrator §5.8).

## How review converges

- Explore reads how called services behave on repeats, timeouts and failures (scout lens CONSUMED-BEHAVIOUR), not just their DTOs.
- For retries, callbacks, scheduled jobs and idempotency keys, the spec has a §8 State model: every state and event pair with its result. The spec pre-check fails a missing pair.
- Every fix starts with an interaction check in the spec: each criterion that reads the same state is re-checked and gets a regression test.
- The verifier tags findings INTRODUCED BY the last fix. Two such rounds in a row in one area raise FIX-CHAIN, which recommends re-specifying that area, not another patch.
- A small fix (`limits.narrow_fix_lines`) gets a NARROW round: correctness plus the lenses that raised findings, on the fix diff only.
- Past `limits.review_rounds` Jorge may grant `limits.review_extensions` more rounds. After that, open findings ship as known risks, at every gate. Only `/tempo:resume <task-id> review-limit <N>` reopens review.

## Things to tune after the first test runs

- Size thresholds in `skills/triage-rubric/SKILL.md` §3.
- Loop limits, review extensions, the narrow-round size and parallel builder count in `limits:` of the repo or workspace config.
- Whether S-lane features need QA (currently skipped).
- Dropping the readback pass (0.6.0): T-007 had no misreadings; its stops were scope-list gaps, which 0.7.0 addresses at Handoff.
- The split thresholds (`limits.split_orders`, `limits.split_criteria`) and `limits.spec_slice_kb`, after the first split runs.
- Whether the order check (0.8.0) pays for its time; turn it off with `limits.order_check: false`.
- Whether scoped targets (0.10.0) miss failures a whole-suite run would catch; compare once a base is green and `advisory` is dropped.
- The fix-of-fix threshold (2 introduced findings in one round) and how often verifiers tag STATE.
- How often FOLD is skipped for a conflict; fixups that touch the same lines as a later commit cannot squash cleanly.
- Stage log minutes for parallel builders: each log starts the next stage clock, so read per-order minutes in state §5 for build time. An order issued for PREFLIGHT starts its clock early.
- PLAN-ONLY together with a split (plan.md slices per group of orders) has not run yet.
- Whether MISSING-SOURCE (0.13.0) stops for things Jorge would rather TEMPO stand in for, and whether the `decide` text check refuses real decisions; both show in the run's esc files and stderr.
- Whether slugs (0.11.0) read well as branch names, and whether outward text still names a local id; `git log --all | grep -E 'T-[0-9]+'` finds leftovers.
