RAW FINDINGS                                      {{task-id}} / {{lens}} / R{{round}}   AMDT 0
LANE: {{S|M|L}}          DEPENDS ON: integration.md, {{spec.md | repro.md}}          ISSUED BY: reviewer

1   SCOPE
1.1   Lens: {{CORRECTNESS | SECURITY | SPEC}}.
1.2   Diff: {{base hash}}..{{head hash}}.
1.3   Depth: {{QUICK | STANDARD | DEEP}}.

2   DEFINITIONS
2.1   Severity HIGH: wrong result, data loss, security exposure or a failed criterion.
2.2   Severity MEDIUM: wrong result in an edge case named in the finding.
2.3   Severity LOW: convention or maintainability issue named in REVIEW.md or CLAUDE.md.

3   CANDIDATE FINDINGS
3.1   C-1: {{HIGH | MEDIUM | LOW}}. {{path:line}}.
3.1.1   Problem: {{one line}}.
3.1.2   Failure scenario: {{concrete input or state, and the wrong output}}.
3.1.3   Fix direction: {{one line}}.

4   CHECKED AND CLEAN
4.1   {{What this lens checked and found no issue in}}.

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
