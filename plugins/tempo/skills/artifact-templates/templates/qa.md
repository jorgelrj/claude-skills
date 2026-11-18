# QA Report: {{task-id}} / R{{round}}
Inputs: {{spec.md | repro.md}}, integration.md · Issued by: qa

## 1 Scope
- Branch: {{branch}} at {{commit hash}}
- Criteria source: {{spec.md §3 | repro.md §5 | plan slice}}

## 2 Criteria results
- {{AC tag}}: {{PASS | FAIL | BLOCKED | CI}}. Method: {{TEST | COMMAND | RUN APP}}. Evidence: {{test name, command and exit code, cited run ID and TREE, or screenshot path}}

## 3 Regression check
- Integrate at {{head}}, bars {{FULL | NARROW | LOCAL}}: {{result}}. {{Commands run for commits after that head, or NIL}}

## 4 Failures returned to build
- {{AC tag}} to WO-{{nn}}: {{evidence}}. NIL if none.

## 5 Result
{{PASS | FAIL}}
