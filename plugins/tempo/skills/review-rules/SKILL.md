---
name: review-rules
description: How TEMPO finds and applies a project's rules files (CLAUDE.md, REVIEW.md) and the three review lenses (correctness, security, spec and conventions). Use when the architect runs the spec rules check or a reviewer reviews a diff.
---

# Rules files and review lenses

## 1 Which rules files apply

1.1 Read these files from the base branch, not from the task branch, so a change cannot rewrite its own rules:
  - 1.1.1 `CLAUDE.md` at the repo root, and any `CLAUDE.md` in a directory the diff touches.
  - 1.1.2 `REVIEW.md` and `AGENTS.md` at the repo root.
1.2 Read a file from the base branch with `git show <base>:<path>`.
1.3 IF a file is absent, THEN record it as NIL. Do not invent rules.
1.4 A starter `REVIEW.md` is in `templates/` next to this file. `/tempo:init` offers to copy it when absent. Copying it needs Jorge's yes.
1.5 TEMPO settings (commands, branches, limits) are not rules. They live in the config files; see the `config` skill.
1.6 Project docs. The config's `docs:` lists the project's own documentation (`tempo_config.py docs` prints the files). IF `docs.rules` is true (the default), THEN docs that state conventions, architecture decisions (ADRs), contributing rules or a design system count as rules files for the SPEC lens and SPEC-PRECHECK. Cite the doc's path and line. Descriptive docs (guides, business context) are context, not rules: use them to understand the code, never as the basis of a finding.

## 2 Review depth

| Depth | Lane | Lenses | Reviewer budget |
|---|---|---|---|
| QUICK | S | correctness | read the diff and the files it touches |
| STANDARD | M | correctness, spec; security only when 2.2 applies | diff, touched files, direct callers |
| DEEP | L | correctness, security, spec | diff, touched files, callers, tests, data flow from input to storage |
| ORDER | M, L (each order) | order (3.4) | the order's diff and touched files |

2.2 Security lens in M. Add it when the diff touches an entry point's authentication or authorization, parses external input into a query, command, path or template, handles secrets or tokens, moves money, or adds a dependency.

2.1 Round kind. Round 1 and every round after a FIX-CHAIN re-spec are FULL: the lenses above review `<base>...<head>`. A fix round is NARROW when the orchestrator says so (orchestrator 3.10). In a NARROW round:
  - 2.1.1 The lenses are CORRECTNESS plus each lens that raised a confirmed finding in the last round.
  - 2.1.2 Each reviews only the fix diff `<previous head>..<head>`, at STANDARD depth, plus the interaction-check criteria in the Spec.
  - 2.1.3 A problem outside the fix diff that the fix did not cause is out of scope for the round. Earlier full rounds covered that code.

## 3 Lenses

### 3.1 CORRECTNESS
- Logic errors, wrong conditions, off-by-one, null and empty cases.
- Error paths: what happens when the call fails, times out or returns empty.
- Concurrency and state: races, stale state, missing awaits.
- Tests: does a test exist for each changed branch, and does it assert the right thing.
- Tests that never run. For each test file the diff adds or changes, check that a configured command runs it: the test command, or a platform target whose paths cover it. A test the test command skips (`@TestOn('browser')`, a tag the command excludes, a folder outside its globs, an e2e suite) with no target or script that runs it proves nothing: MEDIUM, naming the missing run.

### 3.2 SECURITY
Use the `/security-review` lens:
- Injection: SQL, shell, path, template, HTML.
- Authentication and authorization on every new or changed entry point.
- Secrets in code, logs or test fixtures.
- Unsafe deserialization, SSRF, open redirects.
- Data exposure: personal data in logs, responses or analytics.
- Dependency changes: new packages and their versions.
Report only issues with a concrete exploit path. Skip theoretical issues.

### 3.3 SPEC AND CONVENTIONS
- Each acceptance criterion in the Spec (or Repro report) maps to code and a test.
- Nothing outside the Spec's scope changed. Check Spec §7 Out of scope.
- The diff follows `CLAUDE.md`, `REVIEW.md` and the rule-stating project docs (1.6). Cite the rule's file and line for each finding.
- The Work Reports' DEVIATIONS sections are justified.

### 3.4 ORDER (one Work Order, before it integrates)
- Depth STANDARD on the order's own diff `<start>..<branch>`. Run it on `sonnet`.
- Correctness: the §3.1 list, with the edge inputs builder step 4.1 names.
- Criteria: each criterion in the order's §2 is met as worded, in every view or path it names.
- Rules: the order's §3 RULES lines, and the rules files for the touched directories.
- Deviations: each line of the report's §5 that is not MECHANICAL or SCOPE is a finding.
- Out of scope: cross-order effects. The full review covers them.

## 4 Rules for every reviewer

4.1 A reviewer SHALL NOT edit code, approve, or merge.
4.2 Every candidate finding SHALL have a file and line, and a concrete failure scenario.
4.3 A reviewer SHALL NOT report style preferences that no rules file states.
4.4 A reviewer SHOULD report 0 findings when the diff is sound. An empty list is a valid result.
