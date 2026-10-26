PLAN                                              {{task-id}}   AMDT 0
SCOPE: {{REPO | WORKSPACE}}          DEPENDS ON: {{task.md, spec.md or NIL}}          ISSUED BY: {{orchestrator | architect}}

1   OBJECTIVE
1.1   {{One sentence: what is true when every slice has shipped.}}

2   DEFINITIONS
2.1   {{Term}}: {{bound meaning}}.
2.2   blocks-start: the target slice SHALL NOT start before the source slice is built.
2.3   blocks-merge: the target slice MAY be built now; its PR SHALL NOT merge before the source PR merges.
2.4   blocks-validation: both slices MAY be built and merged; the joint check SHALL wait for both.

3   SLICES
3.1   {{S-1}} | {{repo or WO-nn}} | {{objective, one line}} | size {{S|M|L}} | criteria {{AC tags}}
3.1.1   [{{AC-1}}] {{criterion in EARS form}}
3.1.2   Files: {{production files the slice changes}}
3.1.3   Test files: {{test files the slice adds or changes}}
3.1.4   Pattern: {{closest existing file or commit to follow}}
3.1.5   Test command: {{exact command or config command name}}

4   DEPENDENCIES
4.1   {{S-1}} blocks-start {{S-2}} | {{reason: the contract, file or migration that links them}}

5   EXTERNAL BLOCKERS
5.1   {{Work outside this task's scope, its owner, and which slices or criteria it holds back, or NIL}}

6   ORDER
6.1   Wave 1: {{slices with no blocks-start dependency}}.

7   OPEN DECISIONS
7.1   D-{{n}}: {{question}} Options: (a) {{option}} (b) {{option}}. Recommended: {{a}}.

8   ASSUMPTIONS
8.1   {{Each assumption the slices rely on.}}

9   JOINT VALIDATION
9.1   {{How the slices are checked together, or NIL for a single repo}}

AMENDMENT LOG
AMDT 0   {{YYYY-MM-DD}}   Issued.
