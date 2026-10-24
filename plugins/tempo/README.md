# TEMPO

Task Execution & Multi-agent Pipeline Orchestrator. A Claude Code plugin that takes a feature request or a bug report to an open pull request through a fixed set of stages, each run by an agent with a fresh context. Agents hand work to each other only through documents written in an aviation-style (ICAO) standard.

Architecture (draft 2): https://claude.ai/artifact/AuXx9nGXWqDxLeG72K1abT

## Install for testing

From inside the project you want to test on:

```bash
# Option A: load straight from this folder for one session
claude --plugin-dir /Volumes/MySSD/Projects/tempo

# Option B: install through the local marketplace (persists)
/plugin marketplace add /Volumes/MySSD/Projects/tempo
/plugin install tempo@tempo-local
```

After editing files here, restart Claude Code (Option A) or run `/plugin marketplace update tempo-local` and reinstall (Option B).

## Use

| Command | What it does |
|---|---|
| `/tempo:feature <request>` | Feature flow: Triage → Explore → Spec → Work Orders → parallel Build → Integrate → Review → QA → PR |
| `/tempo:bug <report>` | Bug flow: [Investigate] → Reproduce (failing test) → Root cause → Fix → Integrate → Review + sibling sweep → QA → PR |
| `/tempo:resume <task-id> [answer]` | Continue a task from its last artifact, or answer the question it is waiting on |
| `/tempo:init [repo\|workspace] [notes]` | Write or update the TEMPO config for a repo or a multi-repo workspace, detected from the code |

Everything for a task lives in `.tempo/<task-id>/` in the target repo. The task ID is the ticket key when the request names one (`AV-5696`), else `T-NNN`. TEMPO adds `.tempo/` to `.git/info/exclude`, so artifacts and config never show up in the diff.

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
Five escalations: bug won't reproduce, fix changes intended behaviour, a builder decision that changes the goal, a review or QA loop past 3 rounds, anything hard to undo.
Every stop comes with a recommended answer, so "yes" is always enough.

## Layout

```
.claude-plugin/
  plugin.json                 plugin manifest
  marketplace.json            local marketplace so /plugin install works
commands/
  feature.md  bug.md  resume.md  init.md
agents/
  triage.md        classify, clarity check, size, route → task.md
  scout.md         read-only explorer, one lens per instance → merged into context.md
  investigator.md  user feedback → hypotheses.md
  reproducer.md    failing test + root cause → repro.md
  architect.md     spec.md, then wo-NN.md Work Orders, and amendments
  builder.md       one Work Order: readback, then test-first build → report-NN.md
  integrator.md    merge WO branches, full suite → integration.md
  reviewer.md      one lens: correctness | security | spec | spec-precheck → review/<lens>-rN.md
  verifier.md      drop, dedupe, rank, assign → findings-rN.md
  qa.md            per acceptance criterion, with evidence → qa-rN.md
skills/
  orchestrator/              the stage machine the commands run (gates, loops, worktrees, PR)
  icao-document-standard/    the writing rules + scripts/check_doc.py
  artifact-templates/        one template per artifact in templates/
  triage-rubric/             clarity questions, task types, S/M/L lanes, routes
  review-rules/              rules files, review depth, the three lenses
  config/                    config schema, defaults, starters, scripts/tempo_config.py
    templates/REVIEW.md      starter REVIEW.md for a target repo
```

## Document checker

```bash
python3 skills/icao-document-standard/scripts/check_doc.py .tempo/T-001/*.md
```

It reads each document type's required sections from its template, so editing a template changes the check. Exit 0 is PASS, exit 1 lists findings as `file:line: RULE: message`.

## How it runs inside Claude Code

- The main session is the orchestrator. Subagents cannot start other subagents, so the orchestrator starts every agent, including the parallel scouts, builders and reviewers.
- Each builder gets its own git worktree at `.tempo/worktrees/<task-id>-wo-NN` on the work-order branch (default `{branch}-wo-{nn}`), prepared by the config's `worktree:` steps. The integrator merges them into the task branch (`git.branch`, e.g. `feat/{ticket}`), which becomes the PR branch.
- Models are set per agent in the frontmatter (`opus` for architect, investigator, reproducer, reviewer, verifier; `sonnet` for the rest). Change them freely.

## Things to tune after the first test runs

- Size thresholds in `skills/triage-rubric/SKILL.md` §3.
- The vague-word list in `scripts/check_doc.py` if it rejects too much or too little.
- Loop limits and parallel builder count in `limits:` of the repo or workspace config.
- Whether S-lane features need QA (currently skipped).
