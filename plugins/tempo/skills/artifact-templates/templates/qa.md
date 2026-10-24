QA REPORT                                         {{task-id}} / R{{round}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: {{spec.md | repro.md}}, integration.md          ISSUED BY: qa

1   SCOPE
1.1   Branch: {{branch}} at {{commit hash}}.
1.2   Criteria source: {{spec.md §3 | repro.md §6}}.

2   DEFINITIONS
2.1   NIL

3   CRITERIA RESULTS
3.1   {{AC tag}}: {{PASS | FAIL | BLOCKED}}.
3.1.1   Method: {{TEST | COMMAND | RUN APP}}.
3.1.2   Evidence: {{test name, command and exit code, or screenshot path}}.

4   REGRESSION CHECK
4.1   {{full test command}}: exit {{code}}. {{pass and fail counts}}.

5   FAILURES RETURNED TO BUILD
5.1   {{AC tag}} to WO-{{nn}}: {{evidence}}. NIL if none.

6   RESULT
6.1   {{PASS | FAIL}}.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
