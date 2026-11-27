---
description: Write or update TEMPO's config for this repo (.tempo/config.yaml) or for a multi-repo workspace (.tempo/workspace.yaml), and this machine's (.tempo/config.local.yaml). Infers every key it can from the code and the machine, asks only about the rest, records where each value came from, then checks it.
argument-hint: [repo | workspace] [commands | git | pr | ci | task | style | machine | worktree | docs | qa] [notes, e.g. "Java 21, branches {type}/AV-XXXX, PRs in Portuguese"]
---

Set up TEMPO config here: $ARGUMENTS

0. Rules for this command.
   - 0.1 Every key covered. Every key in the schema has a row in the table in §11: init infers it, asks about it, or keeps its default on purpose. Nothing is left at a default by accident. The plugin's tests fail when a schema key has no row.
   - 0.2 Infer first, then ask. Ask only about what the code, the git history, the CI files and the machine cannot answer. Every question carries the inferred value as its first option, marked `(Recommended)`, and says what it rests on.
   - 0.3 Machine values go to `.tempo/config.local.yaml`, never `config.yaml`: the rows with area `machine`, and a test-worker flag in `commands.test_one` or `commands.test_local`.
   - 0.4 Recorded. Each key's source (`detected`, `answered`, `guess`, `default`, `machine`) goes to `.tempo/init-answers.yaml` through `<cfg> record`, so a rerun asks only about what is new, a guess, or changed. Never edit that file by hand.
   - 0.5 `config.yaml` stays lean: a key equal to its default is not written (except `commands` and `git`), but it is still recorded, with source `default` or the source of the answer that kept it.
1. Load the TEMPO `config` skill (listed as `tempo:config` when installed as a plugin). Resolve `<cfg>` as its §3.1 says.
2. Decide the scope and the areas:
   - IF the first word above is `repo` or `workspace`, THEN use it.
   - ELSE IF the working directory is inside a git repository, THEN scope is `repo`.
   - ELSE IF it holds two or more git repositories within 3 levels, THEN scope is `workspace`.
   - ELSE stop and tell me there is nothing to configure here.
   - 2.1 IF a word above names an area from §11 (`commands`, `git`, `pr`, `ci`, `task`, `style`, `machine`, `worktree`, `docs`, `qa`), THEN run only those areas: detect, ask, write and record only their keys, and leave every other key and its record as it is. `/tempo:init machine` runs §5.13, §6.5 and §7.2 alone. No area word: every area.
3. Rerun. IF the target file exists, THEN read it and run `<cfg> keys` (with the areas' key prefixes when 2.1 narrowed the run). Each line is `key  value  file  source  flag`. Then:
   - 3.1 Ask again only about a key that §11 marks `ask` and whose flag is `UNRECORDED` or `GUESS`, or whose detected value from §5 now differs from its recorded one (the code changed). Show the recorded value next to the new one.
   - 3.2 Keep every `answered` value unless I change it. A `CHANGED` key whose file is `config` or `local` was edited by hand: keep the file's value and record it as `answered`, without asking.
   - 3.3 A `detected` key whose detection now gives another value: update it and list the change. One whose detection gives the same value: leave it.
   - 3.4 List each change before writing. IF nothing changed, THEN write nothing, record nothing new, and say `No change`.
4. IF a legacy `.tempo/config.md` exists, THEN start from `<cfg> migrate .tempo/config.md` and carry over its UNMAPPED lines where a key fits.
5. Detect, for each repo in scope:
   - 5.1 Build tool and commands: package.json scripts, pom.xml or mvnw, build.gradle, pubspec.yaml, Makefile, pyproject.toml, go.mod, Cargo.toml. In a monorepo with a per-package build or lint (melos, pnpm `--filter`, Gradle subprojects), write `commands.build_scoped` and `commands.lint_scoped` with `{package}`.
   - 5.2 Toolchain: required JDK, Node or Python version (pom.xml `java.version`, `.nvmrc`, `.tool-versions`, `.python-version`) and where it is installed on this machine. Put machine paths in `env:` with `${env:HOME}`, never a literal home path.
   - 5.3 Base branch: the remote default branch, or `develop` if the team branches from it (`git branch -r`).
   - 5.4 Branch pattern: the 30 most recent remote branches (`git for-each-ref --sort=-committerdate refs/remotes`) and any branch rule in CONTRIBUTING or the docs. Turn the common shape into a template with `{type}` for the type word, e.g. `feat/AV-1234` and `fix/AV-99` → `{type}/{ticket}`. IF the words differ from the Conventional Commits types (`feature/`, `bugfix/`, `story/`), THEN map them in `git.branch_types`. Ignore `tempo/` branches: they are leftovers from older TEMPO runs, never a convention. Never write a fixed `feat/` when other types appear.
   - 5.5 Commit and PR conventions: the last 30 commit subjects, `.github/pull_request_template.md`, and title rules in `.github/workflows/*`, commitlint or danger config. Record the language they are written in.
   - 5.6 Hooks that block commits on this machine (a pre-commit hook that fails) → `git.commit.extra_args: [--no-verify]` only with my yes.
   - 5.7 Worktree needs: gitignored files the build or tests read (`.env*`, local config, keys) → `worktree.copy`; large dependency folders → `worktree.link` or a `worktree.setup` install step.
   - 5.7.0 Symlink-safe ignores. A linked folder is a symlink in each worktree, and a `.gitignore` line with a trailing slash (`node_modules/`) matches only a folder, so `git add -A` there would stage the link. For each `worktree.link` entry, make sure `.gitignore` ignores it without the slash (`node_modules`, `.fvm`); IF the line has the slash, THEN propose the change to me with the reason (it is a tracked file). `<cfg> check` warns about any link that is still not ignored as a symlink.
   - 5.7.0.1 Test runners. Worktrees live under `.tempo/worktrees/` by default, inside the repo, so a runner that walks the repo (vitest, jest, pytest) also collects their test files. IF `git.worktree_root` is inside the repo and the runner's config does not already exclude it, THEN tell me in one line to exclude `.tempo/**` from it (vitest `test.exclude`, jest `testPathIgnorePatterns`, pytest `norecursedirs`), naming the file; do not change the runner config without my yes.
   - 5.7.1 Docs: folders and files holding the project's documentation (`docs/`, `master-docs/`, `doc/`, `adr/`, `AGENTS.md`, `CONTRIBUTING.md`, folders with an `index.md`). Write them as `docs.paths`; exclude old plans and generated output. In a workspace, docs at the workspace root go in the top-level `docs:`, each repo's own docs in its entry. Check with `<cfg> docs --repo <path>`.
   - 5.8 Workspace only: one `repos:` entry per repo with its path; shared settings in `defaults:`; repeated env and commands in `toolchains:`; `depends_on` from build dependencies between the repos (shared libraries, migrations).
   - 5.9 QA surfaces. For each thing a user touches, find how it runs locally and write a `qa.surfaces` entry (config skill 2.8), in start order:
     - stack: `docker-compose.yml` / `compose.yaml` and package scripts like `docker:up`, `db:push`, `db:migrate` → a `service` surface with its `stop`.
     - API: the dev script (`start:dev`, `dev`, `bootRun`, `manage.py runserver`), `PORT` in `.env.example`, a `/health` route → `api` with `url`, `health`, `ready`.
     - web: the dev server (`vite`, `next dev`, `flutter run -d web-server --web-port N`) and how it points at the API (`--dart-define=API_BASE_URL`, `VITE_API_URL`) → `web` with `url`.
     - mobile: `android/` and `ios/` folders, `emulator -list-avds`, `xcrun simctl list devices available` → an emulator or simulator `service`, then `android` / `ios` surfaces with `screenshot` (`adb exec-out screencap -p > {out}`, `xcrun simctl io booted screenshot {out}`). From an Android emulator the host API is `10.0.2.2`.
     - accounts and data: seed scripts and fixtures (`tools/seed`, `db/seed*`, `prisma/seed`) → `qa.seed`. Credentials go in `.tempo/config.local.yaml` as `qa.accounts` (or `${env:NAME}`), never in `config.yaml`.
     - Start each surface once with `<procs> start --task <repo>/.tempo/init --label <name> --ready <regex> -- '<start>'` (`<procs>` is the process script, orchestrator skill 0.12), stop it with `<procs> teardown --task <repo>/.tempo/init`, and run its `health` before writing it; mark what you could not start as a guess. IF the repo has no entry point a user runs (a library), THEN write `qa: {live: false}` and say so. A surface that failed to start is kept as a guess with the error, never turned into `live: false`.
   - 5.10 CI. Read `.github/workflows/*`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml`, `.circleci/config.yml`, `azure-pipelines.yml` and `Jenkinsfile`:
     - which jobs run on a pull request, and whether one of them runs the whole test command (compare with `commands.test`) → the recommended `gates.full_bars`: `ci` when it does, else `on_demand`;
     - jobs for a platform no local command covers (web, android, ios, e2e, a device farm) → candidate `targets` with `run: ci`;
     - a test job that skips a slow tier locally (`--exclude-tags`, `-m "not slow"`, a separate widget or browser job) → candidate `commands.test_local`;
     - the required checks of the base branch (`gh api repos/{owner}/{repo}/branches/<base>/protection/required_status_checks`, when gh can read it) and checks posted as commit statuses at the end of a run → `pr.required_checks`;
     - CI that runs the whole suite on a PR → recommend `limits.ci_rounds: 2` and `pr.draft: false`; none → `ci_rounds: 0`.
   - 5.11 Tracker. Ticket keys in the branch names, commit subjects and PR titles of 5.4 and 5.5 (`AV-123`, `#45`, `ENG-12`), links in the docs and the PR template (`atlassian.net/browse/`, `linear.app/`, `/issues/`), and whether `gh issue list --limit 1` answers → `task.tracker` (or `task.trackers` when two appear), `task.ticket_pattern` and `task.id` (`ticket` when a tracker appears, else `sequence`). Jira tickets are read through atlassian-multi's `atl.py`, GitHub issues through `gh`; say which one this machine has.
   - 5.12 PRs. `gh pr list --state merged --limit 20 --json title,isDraft,body` (when `pr.tool` can be `gh`): the title shape → `pr.title`, its language → `pr.language`, the draft habit → `pr.draft`. `pr.body_template` only when the template sits somewhere other than `.github/pull_request_template.md`. `pr.tool: gh` when the remote is GitHub and `gh auth status` passes, else `none`. `pr.base` only when PRs target another branch than `git.base_branch`.
   - 5.13 This machine. Run `<cfg> machine`. It prints the CPUs, memory, free memory and load, then `SUGGEST: limits.<key>: <value>` lines and `TEST_WORKERS: N`. A machine where the user also runs emulators, a local cluster or other heavy work wants a lower load cap (`limits.heavy_max_load: 1.0`). The test runner from 5.1 tells the worker flag: `-j N` (flutter, make), `--maxWorkers=N` (jest, vitest), `-n N` (pytest-xdist), `-Dsurefire.forkCount=N` (maven), `--max-workers=N` (gradle).
6. Ask about the keys §11 marks `ask` that §5 did not settle and §3 does not skip, in rounds by topic, in this order. Each round is one AskUserQuestion call of at most 4 questions. Skip a round with nothing to ask. Each question names its key, puts the inferred value first marked `(Recommended)`, and says in its description what the inference rests on (`3 of 3 PR workflows run melos test`, `no ticket key in 30 branches`). My notes from the arguments answer a question before it is asked.
   - 6.1 CI: does the PR's CI run the whole suite (`gates.full_bars`: `ci`, `on_demand`, `integrate`, `verify`)? Should a task wait for the PR's checks and fix them (`limits.ci_rounds`: 2, 0, 3)? Which platforms run only in CI (multiSelect, from 5.10 → `targets[].run: ci`)? Under `ci`, which command runs the local tier (`commands.test_local`)?
   - 6.2 Task management: which tracker (`task.tracker`: Jira, Linear, GitHub Issues, none; two of them → `task.trackers`)? Its ticket key format (`task.ticket_pattern`, the detected shape first)? For Jira or GitHub, should TEMPO assign the ticket and move it on start and on PR (`sync:`, config skill 2.5.3), and to which statuses?
   - 6.3 PRs: open as draft or ready (`pr.draft`; ready when `ci_rounds` is above 0)? The title format (`pr.title`)? The language (`pr.language`, and `git.commit.language` when commits differ)? The body layout (`pr.body_template`: the detected template, none)? TEMPO has no key for reviewers or labels: IF I name some, THEN say so and leave them out.
   - 6.4 Working style: run on autopilot (`task.autopilot`)? How many review and QA rounds (`limits.review_rounds` and `limits.qa_rounds` in one question: 3 and 3, 2 and 2 for speed, 5 and 5 for care)? A quick review of each Work Order before it integrates (`limits.order_check`)? When to suggest `/tempo:distill` (`distill.suggest_after`: 10, 5, 0 never)? Any standing answer TEMPO should apply instead of asking (`task.standing_decisions`: none first; my free text through Other, one decision per line)?
   - 6.5 This machine, from 5.13: how many builders and heavy runs at once (`limits.max_parallel_builders` and `limits.heavy_slots` in one question, the suggestion first, then one less and the defaults)? Add the worker flag with `TEST_WORKERS` to `commands.test_one` (and `commands.test_local` when set) in `config.local.yaml` (yes first when the runner takes one)? A free-memory floor for heavy runs (`limits.heavy_min_free_mb`, the suggestion first, then 0 off)? Does this machine run emulators or other heavy work beside TEMPO (`limits.heavy_max_load`: 1.5, 1.0)?
   - 6.6 An answer I give through Other is taken as written and recorded as `answered`. A question I dismiss keeps the recommended value, recorded as `guess` with the note `not answered`.
7. Write.
   - 7.1 The config file from the skill's template (`templates/config.yaml` or `templates/workspace.yaml`). Replace `{{schema-path}}` with the absolute path of the schema. Keep the comments. Leave out keys equal to the defaults, except `commands` and `git` (0.5). On a rerun, change only the lines §3 listed.
   - 7.2 The machine file `.tempo/config.local.yaml`: the `machine` keys that differ from the defaults, and `commands.test_one` / `commands.test_local` with the worker flag when 6.5 said yes. Start it with the schema comment line; `version` is optional there. Never write a machine key to `config.yaml`; IF `config.yaml` already holds one from an older init, THEN propose moving it and move it only with my yes. In a workspace, write one machine file per repo in scope.
8. Record every key in scope with `<cfg> record --source <source> <key> ...`, one call per source, plus one call per key that carries its own `--note` (the evidence for a detected value, what a guess rests on):
   - `detected` for what §5 found; `answered` for what I answered or wrote in the notes; `guess` for a value §5 could not confirm (a surface that did not start, a pattern from two branches); `default` for a key kept at its default on purpose (§11 `default`, and `ask` keys whose recommended value is the default and that I accepted); `machine` for the 6.5 keys I accepted as suggested.
   - Then `<cfg> keys` (with the areas' prefixes under 2.1) SHALL show no `UNRECORDED` and no `CHANGED` line. Fix what it shows.
9. Check.
   - 9.1 Make sure `.tempo/` is in `.git/info/exclude` of every repo in scope.
   - 9.2 Run `<cfg> check` (and `<cfg> check --repo <path>` for each workspace repo). Fix every finding before you finish.
   - 9.3 Full bars. IF `gates.full_bars` is not `ci` and the repo has no PR CI that runs the full suite, THEN tell me that a routine task will ship without it, and that `/tempo:verify` runs it. A target that is slow or red on the base gets `run: critical`.
   - 9.4 Run `<cfg> qa`. IF it prints NIL, THEN tell me QA will block every LIVE criterion until `qa.surfaces` is set; `Live: NONE` criteria still pass on their tests.
10. Report.
   - 10.1 The files written and each change made this run. On a rerun with nothing changed: `No change`, and no question was asked.
   - 10.2 Every key in scope, from `<cfg> keys`, grouped by the areas of §11: key, value, source. Guesses first, each with its note. Keys at their default may be listed per area in one line (`style: 7 keys at their defaults`).
   - 10.3 The qa surfaces you could not start. IF a `REVIEW.md` is absent, THEN offer once to copy the starter from the `review-rules` skill's `templates/` folder.

## 11 Keys

How: `infer` comes from §5 alone; `ask` is inferred first and asked in §6 when §5 cannot settle it; `default` keeps the built-in value on purpose, changed only by my notes. Area is the word `/tempo:init <area>` takes.

| Key | Area | How | From |
|---|---|---|---|
| `toolchain` | commands | infer | workspace only: the toolchain the repo's build matches (5.8) |
| `env` | commands | infer | toolchain paths (5.2) |
| `commands.test` | commands | infer | 5.1 |
| `commands.test_one` | commands | infer | 5.1; the worker flag goes in config.local.yaml (6.5) |
| `commands.test_local` | ci | ask | 5.10, 6.1; only under `gates.full_bars: ci` |
| `commands.build` | commands | infer | 5.1 |
| `commands.build_scoped` | commands | infer | 5.1, monorepos only |
| `commands.typecheck` | commands | infer | 5.1 |
| `commands.lint` | commands | infer | 5.1 |
| `commands.lint_scoped` | commands | infer | 5.1, monorepos only |
| `commands.run_app` | qa | default | older form of one surface; `qa.surfaces` replaces it |
| `targets` | ci | ask | local platform runs (5.1), CI-only platforms as `run: ci` (5.10, 6.1) |
| `git.base_branch` | git | infer | 5.3 |
| `git.branch` | git | infer | 5.4 |
| `git.branch_types` | git | infer | 5.4 |
| `git.work_order_branch` | git | default | local only, never pushed |
| `git.repro_branch` | git | default | local only, never pushed |
| `git.worktree_root` | git | default | 5.7.0.1 names the runner exclude it needs |
| `git.delete_merged_local_branches` | git | default | |
| `git.commit.message` | git | infer | 5.5 |
| `git.commit.language` | git | infer | 5.5; asked with `pr.language` when they differ (6.3) |
| `git.commit.extra_args` | git | ask | 5.6, only with my yes |
| `git.fold_fixes` | git | default | |
| `pr.draft` | pr | ask | 5.12, 6.3 |
| `pr.tool` | pr | infer | 5.12 |
| `pr.base` | pr | infer | 5.12; unset means `git.base_branch` |
| `pr.title` | pr | ask | 5.5, 5.12, 6.3 |
| `pr.language` | pr | ask | 5.5, 5.12, 6.3 |
| `pr.body_template` | pr | ask | 5.12, 6.3 |
| `pr.required_checks` | ci | infer | 5.10 |
| `worktree.copy` | worktree | infer | 5.7 |
| `worktree.link` | worktree | infer | 5.7, 5.7.0 |
| `worktree.setup` | worktree | infer | 5.7 |
| `worktree.teardown` | worktree | infer | per-task resources `worktree.setup` creates (a database named with `{worktree}`) |
| `worktree.before_run` | worktree | default | set after a run shows a leftover that breaks the next |
| `worktree.env` | worktree | infer | 5.7 |
| `gates.full_bars` | ci | ask | 5.10, 6.1 |
| `gates.full_paths` | ci | default | lockfiles and toolchain pins; add a lockfile the default lacks (5.1) |
| `gates.no_code_paths` | ci | default | |
| `tests.always` | ci | default | set when a run shows a test every change must run |
| `tests.slow` | ci | default | set when a run shows a slow test file |
| `limits.max_parallel_builders` | machine | ask | 5.13, 6.5 |
| `limits.review_rounds` | style | ask | 6.4 |
| `limits.review_extensions` | style | default | |
| `limits.narrow_fix_lines` | style | default | |
| `limits.qa_rounds` | style | ask | 6.4 |
| `limits.repro_hypotheses` | style | default | |
| `limits.repro_minutes` | style | default | |
| `limits.split_orders` | style | default | |
| `limits.split_criteria` | style | default | |
| `limits.spec_slice_kb` | style | default | |
| `limits.heavy_max_load` | machine | ask | 5.13, 6.5 |
| `limits.heavy_min_free_mb` | machine | ask | 5.13, 6.5 |
| `limits.heavy_load_wait_minutes` | machine | default | |
| `limits.heavy_slots` | machine | ask | 5.13, 6.5 |
| `limits.ci_rounds` | ci | ask | 5.10, 6.1 |
| `limits.order_check` | style | ask | 6.4 |
| `distill.suggest_after` | style | ask | 6.4 |
| `distill.abandoned_after_days` | style | default | |
| `distill.archive_days` | style | default | |
| `task.id` | task | infer | 5.11 |
| `task.ticket_pattern` | task | ask | 5.11, 6.2 |
| `task.trackers` | task | ask | 5.11, 6.2; when two trackers or a `sync:` is wanted |
| `task.tracker` | task | ask | 5.11, 6.2 |
| `task.standing_decisions` | style | ask | 6.4 |
| `task.autopilot` | style | ask | 6.4 |
| `qa.live` | qa | infer | 5.9 |
| `qa.surfaces` | qa | infer | 5.9 |
| `qa.accounts` | qa | infer | 5.9; real values in config.local.yaml |
| `qa.seed` | qa | infer | 5.9 |
| `docs.paths` | docs | infer | 5.7.1 |
| `docs.exclude` | docs | infer | 5.7.1 |
| `docs.index` | docs | default | |
| `docs.rules` | docs | default | |
