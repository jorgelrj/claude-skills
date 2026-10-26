---
description: Resume a TEMPO task from its last written artifact, optionally answering the question it is waiting on.
argument-hint: <task-id> [build | your answer]
---

Resume TEMPO task: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it.
2. The first word above is the task ID, for example `AV-5696` or `T-042`. IF the next word is `build`, THEN I approve a PLANNED task for building (orchestrator 3.14 or 6.6). Otherwise everything after the ID is my answer to the open escalation or gate, if any.
3. IF no task ID is given, THEN list the tasks in `.tempo/` (and the workspace's `.tempo/`, if any) with their stage and status from each `state.md`, and ask which one to resume. Stop.
4. Read `.tempo/<task-id>/state.md`. IF there is no `state.json` next to it (a task started before TEMPO 0.3.0), THEN run `<state> adopt` on the folder first. Trust the files over the state: confirm that the artifacts named in the stage log exist and pass the document checker. A section a newer template added (Context Map §9, Spec §8 since 0.4.0) is not a failure for an artifact written before it; the architect adds it at the next amendment.
4.1 IF §9 AGENTS IN FLIGHT is not NIL, THEN restart them as orchestrator section 7 says, without asking me.
5. IF the state is WAITING-ON-JORGE:
   - IF an answer is given above, THEN record it in the open `esc-N.md` as AMDT 1 and continue.
5.1 IF the words after the ID are `review-limit <N>`, THEN I raise the review round limit: run `<state> set <dir> --review-limit <N>` and continue. This is the only way past the review hard stop (orchestrator 3.10.6).
   - IF no answer is given, THEN show me the open escalation's question, options and recommendation again, and stop.
6. IF a worktree listed in `state.md` §6 is missing, THEN recreate it from its branch with `git worktree add`.
7. Continue from §8 NEXT ACTION. Stop only at the gates and escalations in orchestrator §4.
