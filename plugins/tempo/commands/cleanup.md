---
description: Delete local TEMPO work-order and repro branches that finished tasks left behind, once their work is in the task branch.
argument-hint: [--yes]
---

Clean up TEMPO work branches: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) for its paths (section 0). `<br>` is its branch script (0.10).
2. Run `<cfg> resolve --repo <repo>` and read `git.work_order_branch` and `git.repro_branch`. Turn them into patterns: `{nn}` becomes `*`, `{branch}` stays.
3. Run `<br> sweep --repo <repo> --wo-pattern "<pattern>" --repro-pattern "<pattern>" --dry-run`. It looks only at tasks whose stage is DONE.
4. Show me the WOULD-DELETE and KEPT lines grouped by task, in a short table. A KEPT line that says commits are missing is work that never shipped: name it plainly.
5. IF the words above include `--yes`, THEN run the same command without `--dry-run`. Otherwise ask me once whether to delete them, and run it without `--dry-run` only after I say yes.
6. Never delete a branch by hand, never pass a branch the script kept to `git branch -D`, and never touch a remote branch.
