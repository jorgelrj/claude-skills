---
description: Run the full test suite, build, lint and every platform target on a branch, once, in this session. Use before a release or a deploy, when you want the expensive checks TEMPO skips on routine tasks.
argument-hint: [branch, default the base branch]
---

Run the full bars on: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) for its paths (section 0). `<cfg>` and `<run>` are its scripts.
2. The branch is the argument, else `git.base_branch`. Make a worktree for it at `<git.worktree_root>/verify-<short hash>`, detached, and run the lines `<cfg> setup --worktree <path>` prints. Do not touch my checkout.
3. Run these from the worktree, one after another, each with `<run> --heavy --max 0` and the Bash tool's `timeout` at 600000. This session is not capped at 3 minutes the way an agent is. IF a run outlives the timeout, THEN call `<run> wait <id> --max 0` with its ID.
   - `<cfg> cmd test`
   - `<cfg> cmd build`, or `typecheck`
   - `<cfg> cmd lint`
   - each line of `<cfg> targets --full`
4. A failing advisory target: compare with the baseline as integrator 5.1 says. Only failures the base lacks count.
5. Run the `<cfg> teardown` lines, and remove the worktree.
6. Tell me in one line per command: exit, time, failure count. Name each failing test. Fix nothing. A failure goes to me: I decide whether it becomes a `/tempo:bug` task.
