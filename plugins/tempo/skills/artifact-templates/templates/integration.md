# Integration Report: {{task-id}}
Inputs: {{report-nn.md list}} · Issued by: integrator

## 1 Branch
- Integration branch: {{task branch}}
- Base: {{base branch}} at {{commit hash}}

## 2 Merged orders
- WO-{{nn}}: {{branch}} merged at {{commit hash}}

## 3 Conflicts
- `{{path}}`: {{how it was resolved, or RETURNED TO BUILD}}. NIL if none.

## 4 Verification
- Bars: {{FULL | NARROW | LOCAL | NONE}}: {{the packages, or the WHY of NONE}}
- `{{test command}}`: exit {{code}}, run {{id}}, TREE {{sha}} {{clean | dirty}}
- `{{typecheck or build command}}`: exit {{code}}, run {{id}}

## 5 Result
{{PASS | FAIL}}

## 6 Returned to build
- WO-{{nn}}: {{failing test or conflict, with evidence}}. NIL if none.
