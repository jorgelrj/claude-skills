# Raw Findings: {{task-id}} / {{lens}} / R{{round}}
Inputs: integration.md, {{spec.md | repro.md}} · Issued by: reviewer
Severity: HIGH = wrong result, data loss, security exposure or a failed criterion. MEDIUM = wrong result in an edge case named in the finding. LOW = convention or maintainability issue named in REVIEW.md or CLAUDE.md.

## 1 Scope
- Lens: {{CORRECTNESS | SECURITY | SPEC | SPEC-PRECHECK}}
- Diff: {{base hash}}..{{head hash}}
- Depth: {{QUICK | STANDARD | DEEP}}. Kind: {{FULL | NARROW}}

## 2 Candidate findings
### C-1: {{HIGH | MEDIUM | LOW}} · `{{path:line}}`
- Problem: {{one line}}
- Failure scenario: {{concrete input or state, and the wrong output}}
- Fix direction: {{one line}}

## 3 Checked and clean
- {{What this lens checked and found no issue in}}
