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
4. IF this repository has no `REVIEW.md` and no `.tempo/config.md`, THEN offer once to copy the starters from the `review-rules` skill's `templates/` folder. Continue without them if I do not answer.
5. Start with §1 of the orchestrator skill, then TRIAGE.
6. Stop only at the gates and escalations in orchestrator §4. Everything else runs without asking me.
