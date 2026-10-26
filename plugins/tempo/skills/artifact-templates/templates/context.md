CONTEXT MAP                                       {{task-id}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: task.md          ISSUED BY: orchestrator (from scouts)

1   OBJECTIVE
1.1   {{One sentence copied from Task Card 4.2.}}

2   DEFINITIONS
2.1   {{Term}}: {{bound meaning}}.

3   FILES
3.1   {{path}} | {{CHANGE | READ | TEST}} | {{why it matters, one line}}

4   DATA MODEL
4.1   {{entity / table / type}} in {{path}}: {{fields that matter}}.

5   PATTERNS TO FOLLOW
5.1   {{Existing pattern}} in {{path:line}}. Use it for {{what}}.

6   TESTS
6.1   Test command: {{exact command}}.
6.2   Existing tests for this area: {{paths}}.
6.3   Build or typecheck command: {{exact command or NIL}}.

7   RISKS
7.1   {{Risk, with the file it lives in}}.

8   OPEN QUESTIONS
8.1   {{Question the scouts could not answer from the code}}.

9   CONSUMED BEHAVIOUR
9.1   {{service, library or ported code}} | {{event: repeat, replay, timeout, decline, failure code, callback order}} | {{what it does}} | {{path:line}}.
9.2   Why {{non-obvious line in ported code}}: {{reason from code, commit or test}} | {{path:line}}. NIL when the task calls nothing and ports nothing.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
