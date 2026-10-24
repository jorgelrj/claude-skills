---
description: Resume a TEMPO task from its last written artifact, optionally answering the question it is waiting on.
argument-hint: <task-id> [your answer]
---

Resume TEMPO task: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it.
2. The first word above is the task ID, for example `AV-5696` or `T-042`. Everything after it is my answer to the open escalation, if any.
3. IF no task ID is given, THEN list the tasks in `.tempo/` with their stage and status from each `state.md`, and ask which one to resume. Stop.
4. Read `.tempo/<task-id>/state.md`. Trust the files over the state: confirm that the artifacts named in the stage log exist and pass the document checker.
5. IF the state is WAITING-ON-JORGE:
   - IF an answer is given above, THEN record it in the open `esc-N.md` as AMDT 1 and continue.
   - IF no answer is given, THEN show me the open escalation's question, options and recommendation again, and stop.
6. IF a worktree listed in `state.md` §6 is missing, THEN recreate it from its branch with `git worktree add`.
7. Continue from §8 NEXT ACTION. Stop only at the gates and escalations in orchestrator §4.
