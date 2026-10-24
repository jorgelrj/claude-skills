WORK ORDER                                        {{task-id}} / WO-{{nn}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: {{NIL | WO-nn}}          ISSUED BY: architect
WORKTREE: {{absolute path}}          BRANCH: {{tempo/<task-id>/wo-nn}}

1   OBJECTIVE
1.1   {{One sentence.}}

2   DEFINITIONS
2.1   {{Term}}: {{bound meaning, copied from the Spec, not linked}}.

3   ACCEPTANCE CRITERIA
3.1   WHEN {{trigger}}, THE SYSTEM SHALL {{response}}.  [AC-n]

4   SCOPE
4.1   IN:   {{every file this order MAY change, including test files}}.
4.2   OUT:  {{files owned by other orders, with the owner}}.

5   PROCEDURE
5.1   {{One imperative instruction per line, 20 words or fewer}}.

6   VERIFICATION
6.1   {{exact command}}        SHALL pass.

7   STOP CONDITIONS
7.1   IF a criterion conflicts with current behaviour, THEN stop and report.
7.2   IF a file outside 4.1 needs a change, THEN stop and report.
7.3   IF a decision is not covered by this order, THEN stop and report.

8   KNOWN RISKS
8.1   {{Risk and mitigation, or NIL}}

9   READBACK
9.1   Write readback-{{nn}}.md before step 5.1, using the readback template.

10  REPORT
10.1  Write report-{{nn}}.md using the work report template.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
