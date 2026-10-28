# Task State: {{task-id}}
Flow: {{FEATURE | BUG | WORKSPACE}} · Lane: {{S|M|L|TBD}} · Mode: {{FULL | PLAN-ONLY}} · Owner: orchestrator
Rendered by tempo_state.py from state.json. Do not edit.

## 1 Task
- {{One-line title}}
- Started: {{YYYY-MM-DD HH:MM}}
- Base branch: {{branch}} at {{commit hash}}
- Task branch: {{branch name from config}}
- Parent: {{workspace task folder, or NIL}}

## 2 Stage
- Current: {{TRIAGE | EXPLORE | INVESTIGATE | REPRODUCE | ROOT-CAUSE | SPEC | HANDOFF | PLAN | PLANNED | BUILD | INTEGRATE | REVIEW | QA | SHIP | REPOS | JOINT-QA | DONE}}
- Status: {{RUNNING | WAITING-ON-JORGE | FAILED | DONE}}

## 3 Stage log
- {{start YYYY-MM-DD HH:MM}} → {{end HH:MM}} ({{minutes}} min) | {{stage}} | {{artifact}} | {{PASS | FAIL | BLOCKED}}

## 4 Loop counters
- Review rounds: {{0}} of {{3}}
- QA rounds: {{0}} of {{3}}
- Document re-issues: {{0}}

## 5 Work orders
- WO-{{nn}} | {{worktree path}} | {{branch}} | {{ISSUED | BUILDING | DONE | BLOCKED}} | {{started HH:MM, minutes}}

## 6 Waiting on Jorge
- {{ESC-n file, or NIL}}

## 7 Next action
- {{The exact next step the orchestrator takes on resume}}

## 8 Agents in flight
- {{agent id}} | {{label}} | {{output path}} | {{prompt file}} | {{started YYYY-MM-DD HH:MM}}

## 9 Child tasks
- {{repo}} | {{task folder}} | {{stage}} | {{status}} | {{PR link or NIL}}
