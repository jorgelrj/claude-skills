---
name: review-rules
description: How TEMPO finds and applies a project's rules files (CLAUDE.md, REVIEW.md, the TEMPO config) and the three review lenses (correctness, security, spec and conventions). Use when the architect runs the spec rules check or a reviewer reviews a diff.
---

# Rules files and review lenses

## 1 Which rules files apply

1.1 Read these files from the base branch, not from the task branch, so a change cannot rewrite its own rules:
  - 1.1.1 `CLAUDE.md` at the repo root, and any `CLAUDE.md` in a directory the diff touches.
  - 1.1.2 `REVIEW.md` at the repo root.
  - 1.1.3 `.tempo/config.md`, if present.
1.2 Read a file from the base branch with `git show <base>:<path>`.
1.3 IF a file is absent, THEN record it as NIL. Do not invent rules.
1.4 A starter `REVIEW.md` and `config.md` are in `templates/` next to this file. `/tempo:feature` offers to copy them when absent. Copying them needs Jorge's yes.

## 2 Review depth

| Depth | Lane | Lenses | Reviewer budget |
|---|---|---|---|
| QUICK | S | correctness | read the diff and the files it touches |
| STANDARD | M | correctness, security, spec | diff, touched files, direct callers |
| DEEP | L | correctness, security, spec | diff, touched files, callers, tests, data flow from input to storage |

## 3 Lenses

### 3.1 CORRECTNESS
- Logic errors, wrong conditions, off-by-one, null and empty cases.
- Error paths: what happens when the call fails, times out or returns empty.
- Concurrency and state: races, stale state, missing awaits.
- Tests: does a test exist for each changed branch, and does it assert the right thing.

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
- Nothing outside the Spec's scope changed. Check Spec §7 OUT OF SCOPE.
- The diff follows `CLAUDE.md` and `REVIEW.md`. Cite the rule's file and line for each finding.
- The Work Reports' DEVIATIONS sections are justified.

## 4 Rules for every reviewer

4.1 A reviewer SHALL NOT edit code, approve, or merge.
4.2 Every candidate finding SHALL have a file and line, and a concrete failure scenario.
4.3 A reviewer SHALL NOT report style preferences that no rules file states.
4.4 A reviewer SHOULD report 0 findings when the diff is sound. An empty list is a valid result.
