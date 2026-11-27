# QA Report: {{task-id}} / R{{round}}
Inputs: {{spec.md | repro.md}}, integration.md · Issued by: qa

## 1 Scope
- Branch: {{branch}} at {{commit hash}} (tree {{tree hash}})
- Criteria source: {{spec.md §3 | repro.md §5 | plan slice | wo-01.md §2}}

## 2 Environment
- Stack started: {{each `<procs>` label, its command and its ready line}}
- Devices and browsers: {{emulator or simulator id and OS, browser and version, viewport}}
- Data: {{seed and accounts used}}
- Design reference: {{design/ files and prototype commit, or NIL}}

## 3 Criteria results
- {{AC tag}}: {{PASS | FAIL | BLOCKED}}. Method: {{LIVE-API | LIVE-WEB | LIVE-MOBILE | LIVE-CLI | TEST (<class>)}}{{ + DESIGN | + DESIGN-FLOW}}. Steps: {{exact curl or UI steps}}. Observed: {{status and body excerpt, or what the screen showed}}. Evidence: {{qa/... paths}}. Supporting: {{test name, or NIL}}
- DW-{{n}}: {{PASS | FAIL | BLOCKED | STAGE}}. By: {{AC tags that prove it | the later stage that does it}}. Observed: {{what shows the step was done, or what is missing}}

## 4 Regression check
- Integrate at {{head}}, bars {{FULL | NARROW | LOCAL}}: {{result}}. {{Commands run for commits after that head, or NIL}}

## 5 Failures returned to build
- {{AC tag}} to WO-{{nn}}: {{evidence}}. NIL if none.

## 6 Result
{{PASS | FAIL}}. PASS only when every criterion is PASS with its saved evidence file and every Done-when step is PASS or STAGE.
