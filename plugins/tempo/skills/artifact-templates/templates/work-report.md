# Work Report: {{task-id}} / WO-{{nn}}
Issued by: builder

## 1 Summary
- Result: {{PASS | FAIL | BLOCKED}}
- {{What changed, one line}}

## 2 Files changed
- `{{path}}`: {{what changed}}

## 3 Verification
- `{{command from WO §5}}`: exit {{code}}. {{last relevant output line, quoted}}
- LIVE AC-{{n}}: {{PASS | FAIL | REACHABLE}}. {{status and body excerpt or output, and the qa/build-AC-n.* path; for WEB, ANDROID, IOS how the screen is reached; NIL when no LIVE line}}
- TREE: {{sha}} {{clean | dirty}}

## 4 Criteria status
- {{AC tag}}: {{PASS | FAIL}}. Evidence: {{test name or output, and the qa/build-AC-n.* path of its LIVE line}}

## 5 Deviations
- {{MECHANICAL | SCOPE | CRITERION | CONTENT | CUT}} §{{n}}: {{each departure from the Work Order, or NIL}}

## 6 Questions
- Q-{{n}}: {{Question that blocked the work, citing the order's §}} Options: (a) {{option}} (b) {{option}}. Recommended: {{a}}, because {{reason}}. Or NIL

## 7 Commits
- {{hash}} {{subject}}
