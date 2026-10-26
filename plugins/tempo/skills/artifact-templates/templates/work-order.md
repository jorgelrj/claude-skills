# Work Order: {{task-id}} / WO-{{nn}}
Lane: {{S|M|L}} · Depends on: {{NIL | WO-nn}} · Worktree: {{absolute path or TBD}} · Branch: {{work-order branch or TBD}}
Spec: {{absolute path of spec.md, repro.md or the plan slice}}. Read its Terms section and every section this order cites.

## 1 Objective
{{One sentence.}}

## 2 Acceptance criteria
- [AC-n] WHEN {{trigger}}, the system shall {{response}}. Test: {{test name or command}}.

## 3 Scope
- IN: {{every file this order may change, test files included}}
- OUT: {{files owned by other orders, with the owner}}

## 4 Steps
1. {{One instruction per step. Cite the spec (for example "spec §4, bullet 3") instead of copying it.}}

## 5 Verification
- `{{exact command}}` passes.

## 6 Stop conditions
Stop before the first edit, or as soon as one of these holds, and write the report with Result BLOCKED:
- Anything in this order is unclear, or two parts of it disagree.
- A criterion conflicts with current behaviour.
- A file outside §3 IN needs a change.
- A decision is not covered by this order or the spec.

## 7 Known risks
- {{Risk and mitigation, or NIL}}
