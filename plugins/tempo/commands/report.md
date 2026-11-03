---
description: File a GitHub issue on the TEMPO repo about something TEMPO just did wrong in this session, with the run's context attached, so it can be analysed and fixed later. The task keeps going.
argument-hint: [--task <task-id>] [--dry-run] <what TEMPO did wrong, and what it should have done>
---

Report a TEMPO problem: $ARGUMENTS

This files an issue about TEMPO itself (the plugin), not about the project's code. It does not fix TEMPO, and it does not change, pause or restart the task: when the issue is filed, carry on exactly where the run was.

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) for its paths (section 0). `<report>` is `python3 <orch>/scripts/tempo_report.py`. Its docstring has the flags.
2. What went wrong. My words above are the report. Remove `--task <id>` and `--dry-run` from them first. IF they are empty, THEN take the most recent thing in this session that looks like TEMPO misbehaving (a stage skipped, a gate it should have stopped at, an agent that ignored its instructions, a script error, a wrong branch or file). IF nothing in the session points to one, THEN ask me once, in one line, what TEMPO did wrong.
3. Context. Run `<report> context` from the repo (or workspace folder), with `--task <id>` when I named one or the session is clearly working on one task. It reads only: plugin version, machine, repo and branch, the task's state and `state.md`, its artifacts, other recent tasks, the session transcript path.
4. Find where TEMPO decides this. Look in the plugin (`<orch>/../..`) for the command, agent, skill section, template, hook or script that governs the behaviour: `grep` for the stage, gate or rule. Name it with the file and section number (`skills/orchestrator/SKILL.md §4.5.1`, `agents/qa.md`). IF you cannot find one, THEN say so: a missing rule is a finding too.
5. Write the body with the Write tool (never a heredoc) to `.tempo/<task-id>/reports/report-<n>.md`, or to a file in the system temp folder when there is no task. Sections, in this order, in plain markdown:
   - `## What happened`: what TEMPO did, with the stage, the agent and the command. Quote the exact lines that show it (a log line, an error, a few lines of an artifact), each at most 15 lines.
   - `## Expected`: what it should have done, in my words where I gave them.
   - `## Where in TEMPO`: the file and section from step 4, and the rule text it says or lacks.
   - `## Impact`: what it cost (time, a wrong change, a stop I had to answer) and whether the run recovered.
   - `## Possible fix`: one or two lines, marked as a guess. Write NIL when you have none.
   - then the whole output of step 3 as is.
   Keep secrets out: no tokens, keys, passwords or `.env` contents, and no more of the project's code than the quote needs.
6. Title: `<area>: <what went wrong>`, under 80 characters, where area is the stage, agent, script or command (`QA: left emulator running after DONE`, `orchestrator: skipped GATE-SPEC on lane M`).
7. File it: `<report> file --title "<title>" --body-file <file> --snapshot <abs task dir>` (leave out `--snapshot` when there is no task; add `--dry-run` when I passed it, then show me the body and stop). The snapshot copies the task's documents to `~/.cache/tempo/reports/`, so the evidence survives `/tempo:cleanup`.
   - `ISSUE: <url>`: filed.
   - `NOT FILED` with `FALLBACK: <url>` and `BODY: <file>` (exit 2): gh is missing, signed out, or failed. Give me the link to open and the file path; the link is prefilled, and says where the full body is when it did not fit.
8. Tell me in one line: the issue link (or the fallback link and file). Then go back to the task: IF an agent or a stage was running or waiting, THEN pick up exactly where the run was. Reporting is not a gate.

The local task id (`T-NNN`) may appear in this issue, next to the machine name the context prints: the issue is about the run on this machine, and the id is how I find its folder. This is the one exception to orchestrator 1.6.1.
