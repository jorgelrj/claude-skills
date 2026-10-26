# Repro and Root Cause: {{task-id}}
Inputs: {{task.md | hypotheses.md}} · Issued by: reproducer

## 1 Symptom
- Observed: {{observed behaviour}}
- Expected: {{expected behaviour}}

## 2 Reproduction
- Result: {{REPRODUCED | NOT REPRODUCED}}
- Test file: `{{path}}`
- Test name: {{name}}
- Command: `{{exact command}}`
- Failure output: {{the assertion message, quoted}}
- Fails for the stated reason: {{YES | NO, with explanation}}

## 3 Hypotheses tried
- H-{{n}}: {{REPRODUCED | NOT REPRODUCED}}. Evidence: {{evidence}}

## 4 Root cause
- Why: {{mechanism, one line}}
- Where: `{{path:line}}`
- Since when: {{commit hash and subject, from git log or git blame}}

## 5 Acceptance criteria
- [AC-1] WHEN {{reproduction steps}}, the system shall {{expected behaviour}}.
- [AC-2] The reproduction test in §2 passes without edits to the test.

## 6 Behaviour change
{{NIL, or: old behaviour, new behaviour, and who it affects. This triggers a gate.}}

## 7 Sibling candidates
- `{{path:line}}`: {{same faulty pattern, one line}}

## 8 Fix direction
1. {{The smallest change that makes the §2 test pass, one step per item}}
