---
name: distill
description: Carries the rules Jorge gave in past TEMPO sessions into .tempo/rules.md, which every later run loads, and deletes or archives the finished session folders under .tempo/. Use when /tempo:distill runs, when the orchestrator saves a rule Jorge gives for every later task, or when asked which TEMPO rules are saved.
---

# TEMPO distill

## 0 Paths

0.1 This skill's directory is `<distill-skill>`. `<distill>` is `python3 <distill-skill>/scripts/tempo_distill.py`. Standard library only, plus `gh` to read a PR's state. Its docstring lists every subcommand and line it prints.
0.2 Every subcommand takes `--repo <path>`: the repo, or the workspace root for a workspace's own `.tempo/`.

## 1 Saved rules: `.tempo/rules.md`

1.1 `.tempo/rules.md` holds the rules Jorge gave for every later task: a way to test, a tool to use or avoid, a scoping habit, a wording rule. It is TEMPO's file, kept out of git with the rest of `.tempo/`. TEMPO never writes these rules into `CLAUDE.md`, `REVIEW.md` or any other project file.
1.2 Only `<distill> rules add`, `rules drop` and `rules show` touch it. Never edit it by hand or with `sed`.
1.3 One rule is one line of at most 200 characters, in plain words, said as an instruction ("Run the API tests with `make test-api`, never `npm test`."). `add` refuses a rule past 200 characters (TOO-LONG), a rule that says the same words as a saved one (DUPLICATE), and a 41st rule (FULL).
1.4 Keep the list short. Before `add`, read `rules show`. IF a saved rule already covers the new one, THEN do not add it. IF the new one sharpens or widens a saved rule, THEN `add` the merged rule and `drop` the old one. IF two saved rules contradict, THEN the newer wins: drop the older.
1.5 `--from <ticket or task id>` records where a rule came from. It stays local, like the file.
1.6 What is not a rule: a choice that only fit one task (this screen's copy, this ticket's scope), a TEMPO setting (commands, branches, limits belong in `.tempo/config.yaml`), a fact the code or docs already state, and `task.standing_decisions` already in config.

## 2 Which sessions it may clear

2.1 A session is a folder under `.tempo/` with a `state.json`. `worktrees/`, `baselines/`, `archive/` and `rules.md` are not sessions.
2.2 `<distill> list` prints ELIGIBLE or KEPT for each, with the reason. Only an ELIGIBLE session may be deleted or archived:
  - 2.2.1 its stage or status is DONE;
  - 2.2.2 its PR is merged (`gh pr view`), or it has no PR and is a delivered plan, a slice of a split task (it ships in its parent's PR), or a workspace task whose every repo task is ELIGIBLE;
  - 2.2.3 git lists no worktree of it;
  - 2.2.4 a parent and its slices go together: one KEPT keeps them all.
2.3 Never touched: a running task, a FAILED or ABORTED task (it never shipped and can be resumed), a task with an open PR or a PR closed without merge, a DONE task with no PR, and any task whose PR state gh cannot tell.
2.4 `<distill> apply` checks every task again and refuses the whole call when one is KEPT. Never delete or move a session folder any other way.

## 3 The suggestion

3.1 `<distill> due --repo <repo> --threshold <distill.suggest_after>` prints `DISTILL: DUE <n> finished sessions` once the ELIGIBLE sessions reach the threshold, else `DISTILL: NOT-DUE`. A threshold of 0 never prints DUE.
3.2 `due --mark` records that Jorge was told. DUE does not print again until `apply` clears the mark, so the suggestion comes once per pile.
3.3 Distill never runs by itself. Only `/tempo:distill` runs `apply`.
