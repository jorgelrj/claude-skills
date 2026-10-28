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
| `/tempo:resume <task-id> [build \| answer]` | Continue a task from its last artifact, answer the question it is waiting on, or `build` a planned task |
| `/tempo:init [repo\|workspace] [notes]` | Write or update the TEMPO config for a repo or a multi-repo workspace, detected from the code |

Everything for a task lives in `.tempo/<task-id>/` in the target repo. The task ID is the ticket key when the request names one (`AV-5696`), else `T-NNN`. TEMPO adds `.tempo/` to `.git/info/exclude`, so artifacts and config never show up in the diff.

## Several repos (workspace tasks)

Run a command from a folder that holds several repos and has `.tempo/workspace.yaml`. TEMPO then:

1. Triages the request against the workspace's repo list.
2. Sends one CROSS-REPO scout per candidate repo, then the architect writes `plan.md`: one slice per repo, typed dependencies (blocks-start, blocks-merge, blocks-validation) and external blockers.
3. Stops at GATE-PLAN.
4. Runs one child task per repo (`<repo>/.tempo/<task-id>/`), each ending in its own PR, and keeps `tracker.md` in the workspace task folder up to date. Children start together unless a blocks-start edge orders them. An S or M slice goes straight to Work Orders from the plan slice; only an L slice, or one with an open decision, runs its own triage, explore and spec.
5. Runs a joint QA across the task branches with the workspace's `validation.steps`, then hands over every PR link.

Only blocks-start orders the work; see `skills/triage-rubric/SKILL.md` §5.

## Task state

`skills/orchestrator/scripts/tempo_state.py` is the only writer of `.tempo/<task-id>/state.json` and the `state.md` rendered from it. It stamps the stage log with this machine's clock, keeps loop counters and work orders, and records agents in flight with their saved prompts, so `/tempo:resume` can restart them after a session restart. Tasks started before 0.3.0 are converted with `tempo_state.py adopt <task-dir>`.

## Lanes

| Lane | Production files | Stages | Rough time |
|---|---|---|---|
| S | 1–3 | Work Order from the Task Card → Build → correctness review → PR | ~10 min |
| M | 4–8, one area | 2 scouts → spec (+ Work Orders in one architect call) → Build → correctness + spec review → QA → PR | ~25 min |
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
Six escalations: bug won't reproduce, fix changes intended behaviour, a builder decision that changes the goal, a review or QA loop past 3 rounds, a fix chain (two review rounds in a row whose findings were caused by the last fix), anything hard to undo.
Every stop comes with a recommended answer, so "yes" is always enough.

### Autopilot (`--auto`, 0.9.0)

With `--auto` on a command (or `task.autopilot: true` in config), TEMPO says "yes" for Jorge wherever its recommendation is grounded, and keeps going. It still stops for:

- a clarify question triage marks NEEDS-JORGE (the outcome is missing, or nothing in the code gives an option to recommend);
- a bug that won't reproduce, a fix that changes intended behaviour, a builder decision that changes the goal;
- anything hard to undo (new dependency, data migration, secrets, deploys, force-push, deleting branches);
- a second fix chain in the same task, and any open decision with no recommended option;
- the PR, which Jorge reviews and merges as always.

Spec approval, the workspace plan, clarify questions with a recommendation, loop limits and the first fix chain are accepted on their recommendation. Each one is logged with `tempo_state.py decide` into `.tempo/<task-id>/decisions.md`, and SHIP copies the list into the PR body under the assumptions, so Jorge reviews them at the PR. `/tempo:plan --auto` still stops at the plan (the plan is the deliverable) and remembers autopilot for `/tempo:resume <task-id> build`.

## Layout

```
.claude-plugin/
  plugin.json                 plugin manifest (listed in the repo root's marketplace.json)
commands/
  feature.md  bug.md  plan.md  resume.md  init.md
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
  guard_rm.py      asks before rm outside the working directory
skills/
  orchestrator/              the stage machine the commands run (gates, loops, worktrees, PR, workspaces)
    scripts/tempo_state.py   the only writer of state.json / state.md; tracker for workspace tasks
  document-standard/         the document shape + scripts/check_doc.py (structure check)
  artifact-templates/        one template per artifact in templates/
  triage-rubric/             clarity questions, task types, S/M/L lanes, routes
  review-rules/              rules files, review depth, the three lenses
  config/                    config schema, defaults, starters, scripts/tempo_config.py
    templates/REVIEW.md      starter REVIEW.md for a target repo
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
- **Safety.** A plugin hook (`hooks/guard_rm.py`) asks before any `rm` outside the working directory, except mktemp and `tempo-*` scratch folders. Builders delete only what they made, and the orchestrator writes prompts with the Write tool, never a heredoc.

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

## How it runs inside Claude Code

- The main session is the orchestrator. Subagents cannot start other subagents, so the orchestrator starts every agent, including the parallel scouts, builders and reviewers.
- Each builder gets its own git worktree at `.tempo/worktrees/<task-id>-wo-NN` on the work-order branch (default `{branch}-wo-{nn}`), prepared by the config's `worktree:` steps. The integrator merges them into the task branch (`git.branch`, e.g. `feat/{ticket}`), which becomes the PR branch.
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
- Whether the rm guard prompts too often outside TEMPO runs.
- Whether the order check (0.8.0) pays for its time; turn it off with `limits.order_check: false`.
- How often FOLD is skipped for a conflict; fixups that touch the same lines as a later commit cannot squash cleanly.
- Stage log minutes for parallel builders: each log starts the next stage clock, so read per-order minutes in state §5 for build time. An order issued for PREFLIGHT starts its clock early.
- PLAN-ONLY together with a split (plan.md slices per group of orders) has not run yet.
