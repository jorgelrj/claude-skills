---
description: Plan a feature or bug fix with TEMPO without building it. Runs Triage, Explore, Spec and Work Orders (or, across several repos, the cross-repo plan) and stops for review. Build it later with /tempo:resume <task-id> build.
argument-hint: [--auto] [--offline] <what you want planned, e.g. a ticket key and goal>
---

Plan this with TEMPO, without building it:

<request>
$ARGUMENTS
</request>

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it exactly, in PLAN-ONLY mode (orchestrator 1.0).
1.1 IF the request carries `--auto` (or `--autopilot`), THEN autopilot is ON (orchestrator 1.0.2): GATE-CLARIFY and GATE-SPEC take their recommendations on the way, and are logged in `decisions.md`. The run still stops at GATE-PLAN, and the state remembers autopilot so the build runs on it too (orchestrator 4.5.5).
1.2 Before anything reads code, the orchestrator fetches each repo's base branch and fast-forwards it (orchestrator 1.3.0, 6.1.1). IF it cannot (fetch fails, local commits not pushed, a checkout that cannot fast-forward), THEN stop and tell me why; plan nothing. `--offline` plans on the local base as it is.
2. IF the request above is empty, THEN ask me what to plan and stop.
3. Triage decides feature or bug. Run the route up to and including HANDOFF (orchestrator 3.13). In a workspace root, run the workspace route up to the plan (orchestrator 6.5).
4. Build nothing: no work-order worktrees, no code, no reviews of code, no PR. A bug plan MAY commit its reproduction test on the repro branch.
5. Stop at GATE-PLAN with `plan.md`: slices, typed dependencies (blocks-start, blocks-merge, blocks-validation), external blockers and open decisions, each with a recommendation.
6. Tell me how to continue: `/tempo:resume <task-id> build`, or `/tempo:resume <task-id> <answers>` to amend the plan first.
