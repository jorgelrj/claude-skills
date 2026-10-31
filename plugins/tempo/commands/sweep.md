---
description: Find processes TEMPO or a coding session left running (emulators, servers, watchers, Java stacks, Chrome test targets) and stop the ones you choose. Use when the Mac is slow or swapping.
argument-hint: [--yes] [task-id]
---

Sweep for leftover processes: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) for its paths (section 0). `<procs>` is its process script (0.12).
2. IF a task ID is given, THEN run `<procs> teardown --task <repo>/.tempo/<task-id> --dry-run`, show me the lines, and go to step 5 for that task only.
3. Run `<procs> sweep`. It looks at the whole machine and changes nothing. It prints three kinds of line:
   - LEFTOVER: marked by TEMPO, and its session ended, or its task is DONE, FAILED or ABORTED (services also while the task waits on me). Safe to stop.
   - IN USE: marked by TEMPO, and its task is still running in a live session. Never stop these.
   - SUSPECT: not marked (started before 0.17.0, or by a session outside TEMPO), an orphan whose parent is gone, that looks like dev tooling or runs in a deleted folder or a `.tempo` worktree, and is older than 30 minutes.
4. Show me one short table: kind, what it is (emulator, Java service, watcher, dev server...), memory, age, folder, and the PID. Put the totals first. Say which SUSPECT lines match a project folder of mine.
5. IF the words above include `--yes`, THEN run `<procs> sweep --kill` (LEFTOVER only). Otherwise ask me once which to stop: all LEFTOVER, plus any SUSPECT PIDs I name.
6. Stop what I chose with `<procs> sweep --kill` and, for SUSPECT PIDs I named, `--kill-pid <pid> ...`. The script refuses a PID that is not in its own LEFTOVER or SUSPECT list. Never use `kill`, `pkill` or `killall` yourself, and never stop an IN USE process or something I did not name.
7. Tell me in one line what stopped and how much memory it freed. Name any FAILED line.
