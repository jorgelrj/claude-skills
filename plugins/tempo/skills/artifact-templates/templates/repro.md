REPRO AND ROOT CAUSE REPORT                       {{task-id}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: {{task.md | hypotheses.md}}          ISSUED BY: reproducer

1   SYMPTOM
1.1   {{Observed behaviour, one line}}.
1.2   {{Expected behaviour, one line}}.

2   DEFINITIONS
2.1   {{Term}}: {{bound meaning}}.

3   REPRODUCTION
3.1   Result: {{REPRODUCED | NOT REPRODUCED}}.
3.2   Test file: {{path}}.
3.3   Test name: {{name}}.
3.4   Command: {{exact command}}.
3.5   Failure output: {{the assertion message, quoted}}.
3.6   Fails for the stated reason: {{YES | NO, with explanation}}.

4   HYPOTHESES TRIED
4.1   H-{{n}}: {{REPRODUCED | NOT REPRODUCED}}. Evidence: {{evidence}}.

5   ROOT CAUSE
5.1   Why: {{mechanism, one line}}.
5.2   Where: {{path:line}}.
5.3   Since when: {{commit hash and subject, from git log or git blame}}.

6   ACCEPTANCE CRITERIA
6.1   WHEN {{reproduction steps}}, THE SYSTEM SHALL {{expected behaviour}}.  [AC-1]
6.2   The test in 3.2 SHALL pass without edits to the test.  [AC-2]

7   BEHAVIOUR CHANGE
7.1   {{NIL, or: old behaviour, new behaviour, and who it affects. This triggers a gate.}}

8   SIBLING CANDIDATES
8.1   {{path:line}}: {{same faulty pattern, one line}}.

9   FIX DIRECTION
9.1   {{The smallest change that makes 3.2 pass, as one line per step}}.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
