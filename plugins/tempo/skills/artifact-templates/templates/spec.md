# Spec: {{task-id}}
Lane: {{M|L}} · Inputs: task.md, context.md · Issued by: architect

## 1 Assumptions and open decisions
- Assumption: {{copied from the Task Card, plus any the architect added}}
- D-1: {{question}} Options: (a) {{option}} (b) {{option}}. Recommended: {{a}}, because {{reason}}.

## 2 Terms
The task's only glossary. Work Orders and reviewers cite it by term name.
- {{Term}}: {{bound to a file, symbol, field, screen or value}}

## 3 Acceptance criteria
- [AC-1] WHEN {{trigger}}, the system shall {{response}}. Test: {{test name or command}}.

## 4 Design
- {{One design decision per bullet, with the file it lands in}}

## 5 Tasks
- TASK-1: {{what}}. Files: {{paths}}. Criteria: {{AC tags}}. Depends on: {{NIL | TASK-n}}.

## 6 Rules check
- Rules files read: {{CLAUDE.md, REVIEW.md, other paths, or NIL}}
- Result: {{PASS | FAIL}}
- {{Each conflict between the spec and a rule, with the rule's file and line}}

## 7 Out of scope
- {{What this task does not change}}

## 8 State model
NIL when no criterion covers retries, repeated requests, callbacks, scheduled jobs or idempotency keys. Otherwise:
- Entity: {{entity}} in `{{path}}`. States: {{list}}. Events: {{list, from Context Map §8}}.
- {{state}} + {{event}} -> {{resulting state and reply}}. {{AC-n | OUT OF SCOPE: reason}}
