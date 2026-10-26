---
name: config
description: TEMPO's structured configuration. The YAML files (.tempo/config.yaml in a repo, .tempo/workspace.yaml in a multi-repo workspace), their JSON Schema, and tempo_config.py, which checks them, merges them and renders branch names and commands. Use when a TEMPO run starts, when /tempo:init writes a config, or when asked to change TEMPO settings for a repo or workspace.
---

# TEMPO config

## 1 Files

1.1 TEMPO reads up to three files. A later file wins, key by key.

| Order | File | Scope |
|---|---|---|
| 1 | `defaults.yaml` next to this file | built in, never edited per project |
| 2 | `<workspace>/.tempo/workspace.yaml` | every repo below that folder; found by walking up from the repo |
| 3 | `<repo>/.tempo/config.yaml` | one repo |

1.2 Both project files live in `.tempo/`. TEMPO lists `.tempo/` in `.git/info/exclude`, so config never lands in a team's repo.
1.3 A workspace file holds `defaults:` (shared settings), `toolchains:` (named sets of env, commands and worktree setup) and `repos:` (path, `depends_on`, toolchain, per-repo overrides).
1.4 Inside the workspace file the merge order is: `defaults:`, then the toolchain the repo names, then the repo's own entry. The repo's `config.yaml` comes last.
1.5 Mappings merge key by key. Lists and scalars replace. An explicit `null` command means "not available". `docs:` is the exception (2.6).
1.6 The schema is `schema/tempo-config.schema.json`. Unknown keys are errors. Add this first line to a config file for editor completion: `# yaml-language-server: $schema=<absolute path to the schema>`.

## 2 Values

2.1 `${env:NAME}` is replaced with the environment variable when the config is resolved. Inside an `env:` map it stays `${NAME}` and the shell expands it, so `PATH: "/x/bin:${env:PATH}"` works.
2.2 `${workspace}` and `${repo}` are the workspace root and the repo root.
2.3 Single-brace placeholders are filled at run time, not in the file: `{ticket}` `{task}` `{slug}` `{branch}` `{nn}` `{type}` `{summary}` `{pattern}` `{module}`.
2.4 Branches:
  - 2.4.1 `git.branch` is the task branch. It is also the integration branch and the PR branch. It SHALL contain `{task}` or `{ticket}`.
  - 2.4.2 `git.work_order_branch` and `git.repro_branch` SHALL NOT start with `{branch}/`. Git cannot hold `feat/X` and `feat/X/wo-01` at once. Default: `{branch}-wo-{nn}` and `{branch}-repro`.
2.5 Task IDs: with `task.id: ticket`, a ticket key matching `task.ticket_pattern` in the request becomes the task ID (`AV-5696`). Without a match, or with `task.id: sequence`, the ID is `T-NNN`.
2.6 Docs. `docs:` says where the project's own documentation lives. It MAY appear at the top of a workspace file (shared docs, relative to the workspace root), in a repo entry and in a repo's `config.yaml` (relative to the repo root). The paths of every block add up; `index` and `rules` come from the last block that sets them.
  - 2.6.1 `paths`: each entry is a folder (every `.md`, `.mdx`, `.markdown`, `.rst`, `.txt`, `.adoc` file under it), a file, a glob (`docs/**/*.md`) or a regex over the root-relative path written `re:<regex>`.
  - 2.6.2 `exclude`: globs or `re:` regexes removed from the matches.
  - 2.6.3 `index`: file names listed first (default `index.md`, `README.md`).
  - 2.6.4 `rules`: true (default) makes rule-stating docs count for review (review-rules §1.6).
  - 2.6.5 Build output, dependency and VCS folders (`node_modules`, `build`, `.git`, `.tempo` ...) are never walked.

## 3 The script

3.1 Call it as `<cfg>`, defined as:
  - `uv run --quiet <this skill>/scripts/tempo_config.py` when `uv` is on PATH. uv installs PyYAML and jsonschema by itself.
  - Otherwise `python3 <this skill>/scripts/tempo_config.py`. It needs `pyyaml` and `jsonschema` 4.18 or later; on exit code 2 it says what is missing.
3.2 Every subcommand takes `--repo <path>` (default: current directory).

| Command | Output |
|---|---|
| `<cfg> check` | validates every file that applies to the repo; `PASS` or one `file: key: message` per line, exit 1 |
| `<cfg> check <file> ...` | validates the named files |
| `<cfg> resolve` | merged config and its sources as JSON (`--format yaml` to read it) |
| `<cfg> names --task <ID> [--ticket <KEY>] [--wo 1 2 ...]` | task, work-order and repro branch names, commit and PR title templates, PR base and draft |
| `<cfg> cmd <name> [--var pattern=X --var module=Y]` | one command as a shell line, with `export ...;` for the env first |
| `<cfg> setup --worktree <path>` | shell steps that make a new worktree usable: copy, link, setup commands |
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
