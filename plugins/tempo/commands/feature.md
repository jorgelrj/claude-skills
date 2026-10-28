---
description: Run the TEMPO feature flow (Triage → Explore → Spec → Work Orders → parallel Build → Integrate → Review → QA → PR) for a request.
argument-hint: [--auto] [--quick | --lane S|M|L] [--plan-only] <what you want built>
---

Run the TEMPO feature flow for this request:

<request>
$ARGUMENTS
</request>

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it exactly. It is the stage machine for this command.
2. Flow hint: `feature`. Triage MAY reclassify the task as a bug. IF it does, THEN follow the bug route the Task Card names.
3. IF the request starts with `--plan-only`, THEN run in PLAN-ONLY mode (orchestrator 1.0): stop after the plan, build nothing.
3.0 IF the request carries `--quick` or `--lane S|M|L`, THEN that lane wins over triage's sizing (orchestrator 1.0.1). `--quick` runs lane S: one Work Order from the Task Card, build, correctness review, draft PR.
3.0.1 IF the request carries `--auto` (or `--autopilot`), THEN run on autopilot (orchestrator 1.0.2 and 4.5): take your own recommendation at every gate and escalation, log each one in `decisions.md`, and stop only for the stops orchestrator 4.5.1 keeps. `--no-auto` turns off `task.autopilot` from config for this task.
3.1 IF the request above is empty, THEN ask me what to build and stop.
4. IF neither `.tempo/config.yaml` nor a workspace file applies, THEN tell me once that `/tempo:init` can write one, and continue with the defaults.
5. Start with §1 of the orchestrator skill, then TRIAGE.
6. Stop only at the gates and escalations in orchestrator §4 (on autopilot, only those in 4.5.1). Everything else runs without asking me.
