---
description: Save the rules from finished TEMPO sessions into .tempo/rules.md, which every later run loads, then archive or delete those session folders. Offers long-abandoned sessions and old archive folders only with your explicit yes. Never touches running tasks or tasks whose PR is still open.
argument-hint: [--yes] [--delete]
---

Distill TEMPO sessions: $ARGUMENTS

1. Load the TEMPO `distill` skill (listed as `tempo:distill` when installed as a plugin). `<distill>` is its script (0.1). The repo is the git repository of the working directory; in a workspace root that is not a repo, the workspace root.
2. Load the TEMPO `orchestrator` skill for its paths (section 0), run `<cfg> resolve --repo <repo>`, and read `distill.abandoned_after_days` (`<days>`) and `distill.archive_days` (`<keep>`).
3. Run `<distill> list --repo <repo> --abandoned-after <days>` and `<distill> archive --repo <repo> --days <keep>`. IF `list` prints no ELIGIBLE or ABANDONED line and `archive` prints no OLD line, THEN tell me the TOTAL lines and the KEPT reasons in a short table, and stop.
4. For each ELIGIBLE and each ABANDONED session, read the files on its SOURCES line, and nothing else: `decisions.md` (what autopilot decided), the `esc-*.md` answers (§6 Answer: what I said at a gate or escalation), `task.md` (§5 Assumptions, my clarify answers) and `pr.md` (the PR body). Pick out what I asked for that should hold in every later task (skill §1.1, §1.6). A session with nothing of that kind gives no rule; say so.
5. Run `<distill> rules show --repo <repo>`. Fold the new rules into it as skill §1.4 says: no rule twice, merged rules replace the ones they merge, the newer of two contradicting rules wins.
6. Show me, in one message:
   - the rules to add, each with the session it came from, and the saved rules to drop with the reason;
   - the sessions to archive (or delete, when the words above include `--delete`), one line each with its reason from `list`;
   - under its own heading, the ABANDONED sessions (they never shipped; idle `<days>` days or more), one line each with its reason, and that they are cleared only if I say so for this list;
   - under its own heading, the OLD archive folders (archived `<keep>` days ago or more) with their age, and that they are deleted for good only if I say so for this list;
   - the KEPT sessions in one short table, with their reasons.
7. IF the words above include `--yes`, THEN go on with the rules and the ELIGIBLE sessions without asking. Always ask me about the ABANDONED list and the OLD list, and wait: `--yes` never covers them. Otherwise ask me once about everything and wait. I MAY drop a rule, reword one, or leave a session or folder out; apply only what I approve.
8. Write the rules first: one `<distill> rules drop --repo <repo> <n> ...` with every number to drop, then `<distill> rules add --repo <repo> --text "<rule>" --from <ticket or task id>` per rule. DUPLICATE means it is already saved: skip it. TOO-LONG: shorten it and add it again. Rules from an ABANDONED session I left out are still added if I approved them.
9. Then run `<distill> apply --repo <repo> --task <id> ... --abandoned <id> ... --abandoned-after <days> --archive` (or `--delete` when the words above include it) for the approved sessions: ELIGIBLE ones as `--task`, ABANDONED ones as `--abandoned`. ABANDONED ones are always archived, never deleted: run them in their own `apply ... --archive` call when the words above include `--delete`. Archived folders go to `.tempo/archive/`. IF it prints REFUSED, THEN a task changed since step 3: tell me which and why, and run it again without that task.
10. IF I approved OLD archive folders, THEN run `<distill> archive --repo <repo> --days <keep> --delete <name> ...`. IF it prints REFUSED, THEN tell me why, and run it again without that folder.
11. Tell me in one line how many rules were added and dropped, how many rules are saved now, how many sessions were archived or deleted (abandoned ones counted apart), and how many archive folders were deleted.
12. Never delete or move a session folder or an archive folder any other way, never edit `.tempo/rules.md` by hand, and never write these rules into `CLAUDE.md`, `REVIEW.md` or any other project file.
