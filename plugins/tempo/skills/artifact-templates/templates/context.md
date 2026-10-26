# Context Map: {{task-id}}
Lane: {{S|M|L}} · Issued by: orchestrator, from the scout reports

## 1 Objective
{{One sentence, copied from the Task Card Clarity Outcome.}}

## 2 Files
- `{{path}}` | {{CHANGE | READ | TEST}} | {{why it matters}}

## 3 Data model
- {{entity / table / type}} in `{{path}}`: {{fields that matter}}

## 4 Patterns to follow
- {{Existing pattern}} in `{{path:line}}`. Use it for {{what}}.

## 5 Tests
- Test command: `{{exact command}}`
- Existing tests for this area: {{paths}}
- Build or typecheck command: `{{exact command}}` or NIL

## 6 Risks
- {{Risk, with the file it lives in}}

## 7 Open questions
- {{Question the scouts could not answer from the code}}

## 8 Consumed behaviour
NIL when the task calls nothing and ports nothing. Otherwise:
- {{service, library or ported code}} | {{event: repeat, replay, timeout, decline, failure code, callback order}} | {{what it does}} | `{{path:line}}`
- Why {{non-obvious line in ported code}}: {{reason from code, commit or test}} | `{{path:line}}`
