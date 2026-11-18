---
name: config
description: TEMPO's structured configuration. The YAML files (.tempo/config.yaml in a repo, .tempo/workspace.yaml in a multi-repo workspace), their JSON Schema, and tempo_config.py, which checks them, merges them and renders branch names and commands. Use when a TEMPO run starts, when /tempo:init writes a config, or when asked to change TEMPO settings for a repo or workspace.
---

# TEMPO config

## 1 Files

1.1 TEMPO reads these files. A later file wins, key by key.

| Order | File | Scope |
|---|---|---|
| 1 | `defaults.yaml` next to this file | built in, never edited per project |
| 2 | `<workspace>/.tempo/workspace.yaml` | every repo below that folder; found by walking up from the repo |
| 3 | `<repo>/.tempo/config.yaml` | one repo |
| 4 | `<repo>/.tempo/config.local.yaml` | this machine only; never committed |

1.2 Both project files live in `.tempo/`. TEMPO lists `.tempo/` in `.git/info/exclude`, so config never lands in a team's repo.
1.3 A workspace file holds `defaults:` (shared settings), `toolchains:` (named sets of env, commands and worktree setup) and `repos:` (path, `depends_on`, toolchain, per-repo overrides).
1.4 Inside the workspace file the merge order is: `defaults:`, then the toolchain the repo names, then the repo's own entry. The repo's `config.yaml` comes last.
1.5 Mappings merge key by key. Lists and scalars replace. An explicit `null` command means "not available". `docs:` is the exception (2.6).
1.5.1 The machine file. `config.local.yaml` takes the same keys as `config.yaml`, `version` optional, and holds what one machine needs: a slow laptop sets `limits.max_parallel_builders: 1` and caps its test runs with its own `commands.test_one` (`cd {package} && flutter test -j 2 {tests}`), or its own `commands.test_local` under `gates.full_bars: ci`, since that is the one `cmd test_one` prints there. Keep it out of git; `check` warns when it is committed. A linked worktree with no file of its own uses the main checkout's.
1.6 The schema is `schema/tempo-config.schema.json`. Unknown keys are errors. Add this first line to a config file for editor completion: `# yaml-language-server: $schema=<absolute path to the schema>`.

## 2 Values

2.1 `${env:NAME}` is replaced with the environment variable when the config is resolved. Inside an `env:` map it stays `${NAME}` and the shell expands it, so `PATH: "/x/bin:${env:PATH}"` works.
2.2 `${workspace}` and `${repo}` are the workspace root and the repo root.
2.3 Single-brace placeholders are filled at run time, not in the file: `{ticket}` `{slug}` `{branch}` `{nn}` `{type}` `{scope}` `{summary}` `{pattern}` `{module}`. `{type}` is the Conventional Commits type (2.4.1.1).
  - 2.3.1 `{ticket}` is the tracker key (`AV-5696`, a GitHub issue number). In a branch name, a task with no ticket gets its slug instead. In a commit message or PR title, an empty `{ticket}` is dropped with the brackets around it: `{type}({ticket}): {summary}` becomes `{type}: {summary}`.
  - 2.3.2 `{slug}` is a few kebab-case words on the change (`fix-safari-export`), chosen by the orchestrator from the request.
  - 2.3.3 `{scope}` is the area of code a commit touches (a module or package name), chosen per commit. It is never a task id.
  - 2.3.4 `{task}` is accepted from older configs and means the same as `{ticket}`. It is never the local `T-NNN` id.
2.4 Branches:
  - 2.4.1 `git.branch` is the task branch. It is also the integration branch and the PR branch, and the only branch TEMPO pushes, so it follows the repo's convention. It SHALL contain `{ticket}` or `{slug}` and SHALL NOT start with `tempo/`. A slug-named branch that already exists locally or on a remote gets `-2`, `-3` ... Default: `{type}/{ticket}`.
  - 2.4.1.1 `{type}` in a branch is the change's Conventional Commits type (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `style`, `revert`), passed to `names --type`. `git.branch_types` maps a type to the word the repo uses instead (`{feat: feature, fix: bugfix}`); types it does not list keep their own name.
  - 2.4.1.2 When no file sets `git.branch` or `git.branch_types`, `names` reads the type words from the 200 most recent remote branches (`story/`, `bugfix/` ...; `tempo/` and unknown words are ignored) and prints the source as `branch_convention`. A `git.branch` with a fixed type word (`feat/{ticket}`) warns: bug fixes would get `feat/` too.
  - 2.4.2 `git.work_order_branch` and `git.repro_branch` are local work branches. They are never pushed. Default: `tempo/{name}-wo-{nn}` and `tempo/{name}-repro`, where `{name}` is the task branch without its type word (`feat/AV-1` gives `tempo/AV-1-wo-01`); `{branch}` is the whole task branch, as before 0.15.0. They SHALL NOT start with `{branch}/`: git cannot hold `feat/X` and `feat/X/wo-01` at once.
  - 2.4.3 `tempo/` marks a branch that never leaves the machine. The plugin's push hook (`hooks/guard_push.py`) denies a push to any `tempo/` name.
2.5 Task IDs: with `task.id: ticket`, a ticket key matching `task.ticket_pattern` in the request becomes the task ID (`AV-5696`). When the pattern has a capture group, the group is the key (`(?:#|/issues/)(\d+)` turns `#215` into `215`). Without a match, or with `task.id: sequence`, the ID is `T-NNN`.
2.5.1 Local IDs stay local. A `T-NNN` id is numbered per checkout: another machine running TEMPO on the same project has its own `T-004`. It names the `.tempo/` folder and nothing else. `names` never puts it in a branch, commit message or PR title, and `check` fails a config whose templates hold one.
2.5.2 Trackers. `task.trackers` lists every tracker a project takes tickets from, each with its own `type` and `ticket_pattern`; it replaces `task.tracker` and `task.ticket_pattern`, which still work as a list of one. `ticket --text <request>` prints the ticket the request names first and its tracker (a tie goes to the tracker listed first).
2.5.3 Sync, opt-in per tracker. A tracker's `sync:` lets TEMPO write to it: `assign: true` assigns the ticket to you and `start: <status>` moves it when the task starts building; `pr: <status>` moves it when the PR opens; `merged: <status>` moves it when CI-WAIT sees the PR merged (2.7). Leave `merged` out when the repo's CI moves the ticket on merge. Jira goes through atlassian-multi's `atl.py` (a transition name or the status it leads to). GitHub assigns with `gh issue edit` and moves the issue on the Projects board `project: <owner>/<number>` by its Status field (gh needs the `project` scope: `gh auth refresh -s project`). `sync start|pr|merged --text <request>` does it and always exits 0; what failed prints `WARN:`.

```yaml
task:
  trackers:
    - type: github
      ticket_pattern: "(?:#|/issues/)(\\d+)"
      sync: {assign: true, start: In progress, pr: In review, project: my-org/4}
    - type: jira
      ticket_pattern: "\\b(POD-\\d+)\\b"
      sync: {assign: true, start: In Progress}
```
2.6 Docs. `docs:` says where the project's own documentation lives. It MAY appear at the top of a workspace file (shared docs, relative to the workspace root), in a repo entry and in a repo's `config.yaml` (relative to the repo root). The paths of every block add up; `index` and `rules` come from the last block that sets them.
  - 2.6.1 `paths`: each entry is a folder (every `.md`, `.mdx`, `.markdown`, `.rst`, `.txt`, `.adoc` file under it), a file, a glob (`docs/**/*.md`) or a regex over the root-relative path written `re:<regex>`.
  - 2.6.2 `exclude`: globs or `re:` regexes removed from the matches.
  - 2.6.3 `index`: file names listed first (default `index.md`, `README.md`).
  - 2.6.4 `rules`: true (default) makes rule-stating docs count for review (review-rules §1.6).
  - 2.6.5 Build output, dependency and VCS folders (`node_modules`, `build`, `.git`, `.tempo` ...) are never walked.

2.7 The CI tier. For a repo whose PR checks run the suites and a review:
  - `gates.full_bars: ci` makes every integrate LOCAL: the touched tests and their mirrors, one typecheck of the touched packages, lint. No whole package, no build, no platform target, critical or not.
  - `commands.test_local` is the test-one command for that tier, with the same placeholders, pointed at a runner that skips what only CI runs (widget or browser tests). Under `ci`, `cmd test_one` prints it.
  - `targets[].run: ci` marks a target only CI runs; it never prints here, `/tempo:verify` included.
  - `limits.ci_rounds` above 0 adds the CI-WAIT stage after SHIP (orchestrator 3.12.1): TEMPO watches the PR's checks, fixes red checks and blocking review findings in plain commits, at most that many rounds, and ends the task once the PR is merged. TEMPO never merges. List the checks that report late, such as a commit status posted when its run ends, in `pr.required_checks`, so a round waits for them. Set `pr.draft: false`; `check` warns about a draft, about `ci` without `ci_rounds`, and about `pr.tool: none`.
  - None of these set, a repo runs as before.

## 3 The script

3.1 Call it as `<cfg>`, defined as:
  - `uv run --quiet <this skill>/scripts/tempo_config.py` when `uv` is on PATH. uv installs PyYAML and jsonschema by itself.
  - Otherwise `python3 <this skill>/scripts/tempo_config.py`. It needs `pyyaml` and `jsonschema` 4.18 or later; on exit code 2 it says what is missing.
3.2 Every subcommand takes `--repo <path>` (default: current directory).

| Command | Output |
|---|---|
| `<cfg> check [<file> ...]` | validates every file that applies to the repo, or the named files; `PASS` or one `file: key: message` per line, exit 1. Warns when the repo path holds a space (melos splits it on Windows) |
| `<cfg> resolve` | merged config and its sources as JSON (`--format yaml` to read it) |
| `<cfg> names [--type <feat\|fix\|chore ...>] [--ticket <KEY>] [--slug <words>] [--wo 1 2 ...]` | task, work-order and repro branch names, the branch convention used, commit and PR title templates, PR base and draft. Needs a ticket or a slug; a `T-NNN` given as `--ticket` is ignored. `--suffix s2` names a split task's slice branch; `--branch <task branch>` derives work-order and repro names from an existing task branch |
| `<cfg> cmd <name> [--var pattern=X --var module=Y]` | one command as a shell line, with `export ...;` for the env first. Under `gates.full_bars: ci`, `test_one` prints `commands.test_local` when it is set |
| `<cfg> bars [--paths <changed files> ...] [--critical]` | the bars an integrate runs: `BARS: FULL` or `BARS: NARROW`, and why. FULL when `gates.full_bars` is `integrate`, the change is critical, or a path matches `gates.full_paths`. With `gates.full_bars: ci` (0.27.0) it is always `BARS: LOCAL` plus `DEFERRED: ci`. With `gates.full_bars: verify` (0.23.0) it is always NARROW, and a second line, `DEFERRED: critical change` or `DEFERRED: gates.full_paths matches ...`, says the whole suite was owed and is left to the branch the task merges into or to `/tempo:verify`. Then `ALWAYS: <file>` per `tests.always` entry (run at every NARROW integrate, whatever packages it touches) and `SLOW: <file>` per `tests.slow` entry that `--paths` changes or mirrors (run filtered while building, whole once at the integrate after the last wave) |
| `<cfg> dupes --ticket <KEY> --branch <task branch> ...` | `DUPE: pr\|branch <ref> <url>` per open PR or remote branch that names the ticket, other than the task's own branches (repeat `--branch` for slices) and branches whose PRs all merged or closed; exit 3 when any. `WARN:` and exit 0 when gh or the remote cannot answer |
| `<cfg> targets [--paths <changed files> ...] [--ref <commit>] [--full] [--critical] [--final] [--scoped-only]` | the platform test runs for the changed files, as `name<TAB>command` with the env exported, plus `<TAB>advisory` for a target marked so. A target with `run: critical` (an advisory target's default) prints only with `--critical` or `--full`; `run: final` also with `--final` (the integrate after the last wave). A target with `scoped_command` prints one run per package, limited to the changed test files and the tests whose names mirror changed files (`foo.dart` → `foo_test.dart`), found in `--ref` (default: the checkout); changed files no test maps to print as `name<TAB># NO-TESTS ...`. `--full`, or no `--paths`, prints the full commands. `--scoped-only` (the orchestrator adds it under `gates.full_bars: verify`) never prints one: a target that would prints `name<TAB># DEFERRED whole suite`. Under `gates.full_bars: ci` a target prints `name<TAB># DEFERRED to CI` (its command with `--verify`), and a `run: ci` target prints nothing |
| `<cfg> setup --worktree <path>` | shell steps that make a new worktree usable: copy, link, setup commands. `check` warns about git-ignored setup files (`.fvm`, `.env`, `local.properties` ...) that `worktree.copy`/`link` do not cover |
| `<cfg> teardown --worktree <path>` | shell steps from `worktree.teardown`, run before SHIP removes a worktree. In `setup` and `teardown` commands, `{worktree}` is the worktree's name as a safe identifier, so `createdb app_{worktree}` gives each task its own database |
| `worktree.before_run` (no subcommand) | commands `tempo_run.py` runs at the root of a linked worktree before each command, never in the main checkout: clears what one run leaves that breaks the next. A failed step prints `BEFORE RUN: exit <n>: <step>` and the command still runs |
| `<cfg> repos` | workspace repos in dependency order, with paths |
| `<cfg> docs [--format json]` | the doc files `docs:` matches, one absolute path per line, index files first; warns on a path that does not exist |
| `<cfg> migrate <.tempo/config.md>` | the legacy markdown config as YAML on stdout; unmapped lines as comments |

## 4 Legacy config.md

4.1 A repo with `.tempo/config.md` and no `.tempo/config.yaml` still works. The script converts it on the fly and warns.
4.2 To convert: `<cfg> migrate .tempo/config.md > .tempo/config.yaml`, review the `UNMAPPED` comments, then delete `config.md`.

## 5 Starters

5.1 `templates/config.yaml`: a commented repo config.
5.2 `templates/workspace.yaml`: a commented workspace config.
5.3 `/tempo:init` fills one of them from what it detects in the repo or workspace.
