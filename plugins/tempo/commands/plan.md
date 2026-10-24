---
description: Plan a feature or bug fix with TEMPO without building it. Runs Triage, Explore, Spec and Work Orders (or, across several repos, the cross-repo plan) and stops for review. Build it later with /tempo:resume <task-id> build.
argument-hint: <what you want planned, e.g. a ticket key and goal>
---

Plan this with TEMPO, without building it:

<request>
$ARGUMENTS
</request>

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it exactly, in PLAN-ONLY mode (orchestrator 1.0).
2. IF the request above is empty, THEN ask me what to plan and stop.
3. Triage decides feature or bug. Run the route up to and including HANDOFF (orchestrator 3.13). In a workspace root, run the workspace route up to the plan (orchestrator 6.5).
4. Build nothing: no work-order worktrees, no code, no reviews of code, no PR. A bug plan MAY commit its reproduction test on the repro branch.
5. Stop at GATE-PLAN with `plan.md`: slices, typed dependencies (blocks-start, blocks-merge, blocks-validation), external blockers and open decisions, each with a recommendation.
6. Tell me how to continue: `/tempo:resume <task-id> build`, or `/tempo:resume <task-id> <answers>` to amend the plan first.
