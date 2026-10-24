---
description: Run the TEMPO feature flow (Triage → Explore → Spec → Work Orders → parallel Build → Integrate → Review → QA → PR) for a request.
argument-hint: <what you want built>
---

Run the TEMPO feature flow for this request:

<request>
$ARGUMENTS
</request>

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it exactly. It is the stage machine for this command.
2. Flow hint: `feature`. Triage MAY reclassify the task as a bug. IF it does, THEN follow the bug route the Task Card names.
3. IF the request above is empty, THEN ask me what to build and stop.
4. IF neither `.tempo/config.yaml` nor a workspace file applies, THEN tell me once that `/tempo:init` can write one, and continue with the defaults.
5. Start with §1 of the orchestrator skill, then TRIAGE.
6. Stop only at the gates and escalations in orchestrator §4. Everything else runs without asking me.
