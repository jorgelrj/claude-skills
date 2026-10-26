FINDINGS                                          {{task-id}} / R{{round}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: {{raw findings file list}}          ISSUED BY: verifier

1   SCOPE
1.1   Round: {{n}} of {{limit}}. Kind: {{FULL | NARROW}}.
1.2   Lenses: {{CORRECTNESS, SECURITY, SPEC}}.
1.3   Diff: {{base hash}}..{{head hash}}.
1.4   Fix diff: {{previous round head}}..{{head hash}}, or NIL in round 1.

2   DEFINITIONS
2.1   Severity HIGH: wrong result, data loss, security exposure or a failed criterion.
2.2   Severity MEDIUM: wrong result in an edge case named in the finding.
2.3   Severity LOW: convention or maintainability issue named in REVIEW.md or CLAUDE.md.
2.4   Confirmed: the verifier read the code and the failure scenario holds.
2.5   Introduced: the finding's lines are in the fix diff, or its failure scenario exists only because of the last fix.

3   CONFIRMED FINDINGS
3.1   F-1: {{HIGH | MEDIUM | LOW}}. {{path:line}}. Lens: {{lens}}. Owner: WO-{{nn}}.
3.1.1   Problem: {{one line}}. {{REPEAT, or INTRODUCED BY r<n> F-<n>, or NIL}}.
3.1.1.1   Area: {{Spec 8 entity, or the files of the finding}}.
3.1.2   Evidence: {{code quote or command output}}.
3.1.3   Fix direction: {{one line}}.

4   DROPPED FINDINGS
4.1   {{lens}} C-{{n}}: {{FALSE POSITIVE | DUPLICATE OF F-n | OUT OF SCOPE}}. Reason: {{one line}}.

5   SIBLING SWEEP
5.1   {{path:line}}: {{same pattern; IN SCOPE or LISTED ONLY}}. NIL outside the bug lane.

6   LEFT OPEN
6.1   F-{{n}}: {{reason it is not fixed in this PR}}.

7   RESULT
7.1   {{PASS | FAIL}}. PASS means no confirmed HIGH or MEDIUM finding remains.
7.2   Introduced findings: {{count}}. Areas: {{list or NIL}}.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
