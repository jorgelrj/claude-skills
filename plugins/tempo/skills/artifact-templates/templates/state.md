TASK STATE                                        {{task-id}}
FLOW: {{FEATURE | BUG | WORKSPACE}}          LANE: {{S|M|L|TBD}}          OWNER: orchestrator
MODE: {{FULL | PLAN-ONLY}}

1   TASK
1.1   {{One-line title}}.
1.2   Started: {{YYYY-MM-DD HH:MM}}.
1.3   Base branch: {{branch}} at {{commit hash}}.
1.4   Task branch: {{branch name from config}}.
1.5   Parent: {{workspace task folder, or NIL}}.

2   DEFINITIONS
2.1   NIL

3   STAGE
3.1   Current: {{TRIAGE | EXPLORE | INVESTIGATE | REPRODUCE | ROOT-CAUSE | SPEC | HANDOFF | PLAN | PLANNED | BUILD | INTEGRATE | REVIEW | QA | SHIP | REPOS | JOINT-QA | DONE}}.
3.2   Status: {{RUNNING | WAITING-ON-JORGE | FAILED | DONE}}.

4   STAGE LOG
4.1   {{YYYY-MM-DD HH:MM}} | {{stage}} | {{artifact}} | {{PASS | FAIL | BLOCKED}}

5   LOOP COUNTERS
5.1   Review rounds: {{0}} of {{3}}.
5.2   QA rounds: {{0}} of {{3}}.
5.3   Document re-issues: {{0}}.

6   WORK ORDERS
6.1   WO-{{nn}} | {{worktree path}} | {{branch}} | {{ISSUED | READBACK OK | BUILDING | DONE | BLOCKED}}

7   WAITING ON JORGE
7.1   {{ESC-n file, or NIL}}

8   NEXT ACTION
8.1   {{The exact next step the orchestrator takes on resume}}.

9   AGENTS IN FLIGHT
9.1   {{agent id}} | {{label}} | {{output path}} | {{prompt file}} | {{started YYYY-MM-DD HH:MM}}

10  CHILD TASKS
10.1  {{repo}} | {{task folder}} | {{stage}} | {{status}} | {{PR link or NIL}}
