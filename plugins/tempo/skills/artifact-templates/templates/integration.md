INTEGRATION REPORT                                {{task-id}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: {{report-nn.md list}}          ISSUED BY: integrator

1   BRANCH
1.1   Integration branch: {{task branch}}.
1.2   Base: {{base branch and commit hash}}.

2   DEFINITIONS
2.1   NIL

3   MERGED ORDERS
3.1   WO-{{nn}}: {{branch}} merged at {{commit hash}}.

4   CONFLICTS
4.1   {{path}}: {{how it was resolved, or RETURNED TO BUILD}}. NIL if none.

5   VERIFICATION
5.1   {{full test command}}: exit {{code}}.
5.2   {{build or typecheck command}}: exit {{code}}.

6   RESULT
6.1   {{PASS | FAIL}}.

7   RETURNED TO BUILD
7.1   WO-{{nn}}: {{failing test or conflict, with evidence}}. NIL if none.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
