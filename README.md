# claude-skills

A [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
of reusable skills, named `jorgelrj-skills`.

| Plugin | What it does |
|---|---|
| [atlassian-multi](plugins/atlassian-multi/skills/atlassian-multi) | Jira + Confluence Cloud across several Atlassian accounts, routed by project so nothing hits the wrong site |
| [tempo](plugins/tempo) | Task Execution & Multi-agent Pipeline Orchestrator: feature and bug-fix flows from request to pull request, with parallel builders and review/QA loops |

## Install

```sh
claude plugin marketplace add jorgelrj/claude-skills
claude plugin install atlassian-multi@jorgelrj-skills
claude plugin install tempo@jorgelrj-skills
```

Or, inside a session (Claude Code 2.1.275+), in one step:

```
/plugin install atlassian-multi --marketplace jorgelrj/claude-skills
```

The repo is private, so you need read access and git credentials that can
clone it (for example `gh auth login`). `claude plugin marketplace update
jorgelrj-skills` pulls new versions.

## Layout

```
.claude-plugin/marketplace.json                 # lists every plugin in the repo
plugins/<plugin>/.claude-plugin/plugin.json     # plugin manifest (name must match its marketplace entry)
plugins/<plugin>/skills/<skill>/SKILL.md        # the skill
plugins/<plugin>/skills/<skill>/scripts/        # code the skill runs
plugins/<plugin>/skills/<skill>/tests/          # tests for that code
plugins/<plugin>/commands/, agents/             # slash commands and subagents, when a plugin has them (see tempo)
```

## Adding a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` with at least `name`,
   `version` and `description`.
2. Add the skill(s) under `plugins/<name>/skills/<skill>/SKILL.md`.
3. Add an entry to `.claude-plugin/marketplace.json` with the same `name` and
   `"source": "./plugins/<name>"`.
4. Run `claude plugin validate .` and add a row to the table above.

Bump a plugin's `version` in `plugin.json` when you change it. Installed copies
only update when the version changes.

## Versions and tags

Each plugin release is an annotated git tag `<plugin>-v<version>`
(`tempo-v0.17.2`, `atlassian-multi-v0.1.0`), on the commit that set that
version. Tools that need a fixed copy of a plugin (the TEMPO app pins its skill
folder this way) clone the repo at one of these tags instead of following a
working tree.

The `Tag plugin versions` workflow tags new versions when a `plugin.json`
change lands on `main`. To tag by hand:

```sh
scripts/tag-plugin-versions.sh          # tag locally
scripts/tag-plugin-versions.sh --push   # tag and push the new tags
```

## Developing

Load a plugin straight from the working tree, with no install:

```sh
claude --plugin-dir plugins/atlassian-multi
claude --plugin-dir plugins/tempo
```

Or register this checkout as a local marketplace. Edits then show up at the
next session start or after `/reload-plugins`:

```sh
claude plugin marketplace add ./
claude plugin install atlassian-multi@jorgelrj-skills
```

Run a plugin's tests:

```sh
python3 -m unittest discover -s plugins/atlassian-multi/skills/atlassian-multi/tests -v
```
