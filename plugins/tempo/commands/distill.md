---
description: Save the rules from finished TEMPO sessions into .tempo/rules.md, which every later run loads, then archive or delete those session folders. Never touches running or unshipped tasks, or tasks whose PR is still open.
argument-hint: [--yes] [--delete]
---

Distill TEMPO sessions: $ARGUMENTS

1. Load the TEMPO `distill` skill (listed as `tempo:distill` when installed as a plugin). `<distill>` is its script (0.1). The repo is the git repository of the working directory; in a workspace root that is not a repo, the workspace root.
2. Run `<distill> list --repo <repo>`. IF it prints no ELIGIBLE line, THEN tell me the TOTAL line and the KEPT reasons in a short table, and stop.
3. For each ELIGIBLE session, read the files on its SOURCES line, and nothing else: `decisions.md` (what autopilot decided), the `esc-*.md` answers (§6 Answer: what I said at a gate or escalation), `task.md` (§5 Assumptions, my clarify answers) and `pr.md` (the PR body). Pick out what I asked for that should hold in every later task (skill §1.1, §1.6). A session with nothing of that kind gives no rule; say so.
4. Run `<distill> rules show --repo <repo>`. Fold the new rules into it as skill §1.4 says: no rule twice, merged rules replace the ones they merge, the newer of two contradicting rules wins.
5. Show me, in one message:
   - the rules to add, each with the session it came from, and the saved rules to drop with the reason;
   - the sessions to archive (or delete, when the words above include `--delete`), one line each with its reason from `list`;
   - the KEPT sessions in one short table, with their reasons.
6. IF the words above include `--yes`, THEN go on. Otherwise ask me once and wait. I MAY drop a rule, reword one, or leave a session out; apply only what I approve.
7. Write the rules first: one `<distill> rules drop --repo <repo> <n> ...` with every number to drop, then `<distill> rules add --repo <repo> --text "<rule>" --from <ticket or task id>` per rule. DUPLICATE means it is already saved: skip it. TOO-LONG: shorten it and add it again.
8. Then run `<distill> apply --repo <repo> --task <id> ... --archive` (or `--delete` when the words above include it) for the approved sessions. Archived folders go to `.tempo/archive/`. IF it prints REFUSED, THEN a task changed since step 2: tell me which and why, and run it again without that task.
9. Tell me in one line how many rules were added and dropped, how many rules are saved now, and how many sessions were archived or deleted.
10. Never delete or move a session folder any other way, never edit `.tempo/rules.md` by hand, and never write these rules into `CLAUDE.md`, `REVIEW.md` or any other project file.
