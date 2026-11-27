# Work Order: {{task-id}} / WO-{{nn}}
Lane: {{S|M|L}} · Depends on: {{NIL | WO-nn (start) | WO-nn (order)}} · Worktree: {{absolute path or TBD}} · Branch: {{work-order branch or TBD}}
Spec: {{absolute path of spec.md, repro.md or the plan slice}}. Read its Terms section and every section this order cites.

## 1 Objective
{{One sentence.}}
{{Only when the Spec is larger than limits.spec_slice_kb: a Terms: list and a Design: list copying the Spec lines this order uses, each citing its section.}}

## 2 Acceptance criteria
- Done-when map: {{S lane: each Task Card DW-n and the criteria or later stage that do it, as the spec's; otherwise the DW-n this order's criteria carry, or NIL}}
- [AC-n] WHEN {{trigger}}, the system shall {{response}}. Test: {{test name or command}}. {{Live: and Design: copied unchanged from the spec}}

## 3 Scope
- IN: {{every file this order may change, test files included}}
- OUT: {{files owned by other orders, with the owner}}
- RULES: {{each repo rule that applies to these files, with its file and line, or NIL}}

## 4 Steps
1. {{One instruction per step. Cite the spec (for example "spec §4, bullet 3") instead of copying it.}}

## 5 Verification
- `{{exact command, scoped to this order's test files or packages; never the full suite}}` passes.
- `{{typecheck with the package filled: this order's packages, plus the dependents of a shared module it touches}}` passes.
- SLOW `{{test-one on a SLOW file with --plain-name '<group>' per group the criteria touch, or the whole file with the reason}}` passes.
- LIVE AC-{{n}}: {{the Live line}}. The builder runs API and CLI lines before the report and saves the output under the task's `qa/build-AC-n.*`; WEB, ANDROID and IOS lines stay reachable (route, seed, flag) for QA.

## 6 Stop conditions
Stop before the first edit, or as soon as one of these holds, and write the report with Result BLOCKED:
- Anything in this order is unclear, or two parts of it disagree.
- A criterion conflicts with current behaviour.
- A file outside §3 IN needs a change. Exception: a test file, test double or fixture in a package that already holds an IN file, when it only follows this order's change; change it and list it in the report's §5 Deviations.
- A decision is not covered by this order or the spec.

## 7 Known risks
- {{Risk and mitigation, or NIL}}
