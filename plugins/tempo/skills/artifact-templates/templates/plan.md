# Plan: {{task-id}}
Scope: {{REPO | WORKSPACE}} · Inputs: {{task.md, spec.md or NIL}} · Issued by: {{orchestrator | architect}}

## 1 Objective
{{One sentence: what is true when every slice has shipped.}}

## 2 Terms
- {{Term}}: {{bound meaning}}
- blocks-start: the target slice does not start before the source slice is built.
- blocks-merge: the target slice may be built now; its PR does not merge before the source PR merges.
- blocks-validation: both slices may be built and merged; the joint check waits for both.

## 3 Slices
### S-1 · {{repo or WO-nn}} · size {{S|M|L}}
- Objective: {{one line}}
- [AC-1] {{criterion in the spec format: WHEN ..., the system shall .... Test: .... Live: ... (or Live: NONE (...)). Design: F-n when it changes a screen}}
- Files: {{production files the slice changes}}
- Test files: {{test files the slice adds or changes}}
- Pattern: {{closest existing file or commit to follow}}
- Test command: {{exact command or config command name}}

## 4 Dependencies
- {{S-1}} blocks-start {{S-2}} | {{reason: the contract, file or migration that links them}}

## 5 External blockers
- {{Work outside this task's scope, its owner, and which slices or criteria it holds back, or NIL}}

## 6 Order
- Wave 1: {{slices with no blocks-start dependency}}

## 7 Open decisions
- D-{{n}}: {{question}} Options: (a) {{option}} (b) {{option}}. Recommended: {{a}}.

## 8 Assumptions
- {{Each assumption the slices rely on}}

## 9 Joint validation
- [AC-{{n}}] {{end-to-end criterion in the spec format, numbered after the slice tags. Live: WEB | ANDROID | IOS <screen> ... · Evidence: qa/AC-n.png plus qa/AC-n.http.txt, or Live: NONE (<class>: <why>) for a TEST-depth line}}, or NIL for a single repo
