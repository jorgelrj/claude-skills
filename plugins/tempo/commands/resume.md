---
description: Resume a TEMPO task from its last written artifact, optionally answering the question it is waiting on.
argument-hint: <task-id> [--auto | --no-auto] [build | review-limit N | ci-limit N | your answer]
---

Resume TEMPO task: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) and follow it.
2. The first word above is the task ID, for example `AV-5696` or `T-042`. IF the next word is `build`, THEN I approve a PLANNED task for building (orchestrator 3.14 or 6.6). Otherwise everything after the ID is my answer to the open escalation or gate, if any.
2.1 IF the words after the ID include `--auto` or `--no-auto`, THEN remove it and run `<state> set <dir> --autopilot on` or `off` before anything else. Autopilot is otherwise what `state.json` says (orchestrator 4.5).
3. IF no task ID is given, THEN list the tasks in `.tempo/` (and the workspace's `.tempo/`, if any) with their stage and status from each `state.md`, and ask which one to resume. Stop.
4. Read `.tempo/<task-id>/state.md`. IF there is no `state.json` next to it (a task started before TEMPO 0.3.0), THEN run `<state> adopt` on the folder first. Trust the files over the state: confirm that the artifacts named in the stage log exist and pass the document checker. A section a newer template added (Context Map §9, Spec §8 since 0.4.0) is not a failure for an artifact written before it; the architect adds it at the next amendment.
4.0.1 Base. Run the orchestrator's base sync (1.3.0) for the task's repo, or for every repo in a workspace task (6.1.1), before you continue. On `BASE: STOP`, tell me why and stop. IF the task has not reached BUILD and the `HEAD:` differs from `state.md` §1 Base branch, THEN record it with `<state> set <dir> --base-commit <HEAD>` and tell me in one line how many commits landed; a PLANNED task going to build follows orchestrator 3.14 instead. A task already building keeps its base; the integrate's base-drift check (orchestrator 3.9) handles new commits.
4.1 IF §8 Agents in flight is not NIL, THEN restart them as orchestrator section 7 says, without asking me.
4.2 CI-WAIT. IF the stage is CI-WAIT (orchestrator 3.12.1), THEN the task waits on its PR, not on an answer. IF the words after the ID are `ci-limit <N>`, THEN run `<state> set <dir> --ci-limit <N>`. IF the state is WAITING-ON-JORGE, THEN record any answer in the open `esc-N.md` §6 Answer and run `<state> wait <dir> --clear`. Step 5.2 and step 6 still apply. Then, instead of step 7, start the watcher again (3.12.1 step 1); it reports a merge that happened while no session ran.
5. IF the state is WAITING-ON-JORGE:
   - IF an answer is given above, THEN record it in the open `esc-N.md` §6 Answer and continue.
5.1 IF the words after the ID are `review-limit <N>`, THEN I raise the review round limit: run `<state> set <dir> --review-limit <N>` and continue. This is the only way past the review hard stop (orchestrator 3.10.6).
   - IF no answer is given and autopilot is ON and orchestrator 4.5.2 lists the open stop, THEN accept its recommendation as 4.5.3 says and continue.
   - IF no answer is given otherwise, THEN show me the open escalation's question, options and recommendation again, and stop.
5.2 IF the status is ABORTED or FAILED, THEN run `<state> set <dir> --status RUNNING` first. Teardown (orchestrator section 10) stopped the task's services at the wait, abort or failure; the agents that need a server or emulator start it again with `<procs> start`.
6. IF a worktree listed in `state.md` §5 is missing, THEN recreate it from its branch with `git worktree add`.
7. Continue from §7 Next action. Stop only at the gates and escalations in orchestrator §4 (on autopilot, only those in 4.5.1).
