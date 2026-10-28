---
description: Run the TEMPO bug-fix flow. Works from a known issue (error, stack trace, steps, file) or from user feedback only. Reproduces with a failing test before any fix.
argument-hint: [--auto] [--quick | --lane S|M|L] [--plan-only] <error, steps, or what the user reported>
---

Run the TEMPO bug-fix flow for this report:

<report>
$ARGUMENTS
</report>

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it exactly.
2. Flow hint: `bug`. Triage decides between BUG-KNOWN and BUG-FEEDBACK using the triage rubric.
3. IF the request starts with `--plan-only`, THEN run in PLAN-ONLY mode (orchestrator 1.0): stop after the plan, build nothing.
3.0 IF the report carries `--quick` or `--lane S|M|L`, THEN that lane wins over triage's sizing (orchestrator 1.0.1). Reproduce still runs in every lane.
3.0.1 IF the report carries `--auto` (or `--autopilot`), THEN run on autopilot (orchestrator 1.0.2 and 4.5): take your own recommendation at every gate and escalation, log each one in `decisions.md`, and stop only for the stops orchestrator 4.5.1 keeps. `--no-auto` turns off `task.autopilot` from config for this task. NO-REPRO and BEHAVIOUR-CHANGE always stop.
3.1 IF the report above is empty, THEN ask me what is broken and stop.
4. The route is: [Investigate, only for user feedback] → Reproduce → Root cause → Handoff (one Work Order) → Build → Integrate → Review with sibling sweep → QA → PR.
5. No fix starts before a test fails for the stated reason. This rule has no exceptions. IF reproduction fails within the budget, THEN raise NO-REPRO.
6. IF the fix changes intended behaviour, THEN raise BEHAVIOUR-CHANGE before Handoff.
7. Stop only at the gates and escalations in orchestrator §4 (on autopilot, only those in 4.5.1).
