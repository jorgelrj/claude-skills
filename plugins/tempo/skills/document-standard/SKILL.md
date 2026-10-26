---
name: document-standard
description: The TEMPO document standard for every handoff artifact in .tempo/<task-id>/: structured markdown with the template's numbered headings, tagged criteria and findings, concrete paths and commands, and a structure-only checker. Use when writing or checking any .tempo/ artifact.
---

# TEMPO document standard

Handoff documents are plain markdown with a fixed shape. The shape is what lets the next agent, the orchestrator and Jorge find things fast. Wording style is not policed.

## 1 Shape

1. Line 1 is `# <Type>: <task-id>[ / <doc id>]`, copied from the template. Line 2 is the short metadata line from the template.
2. Every `## <n> <Title>` heading of the template is present, in template order, with the template's number. Do not add other `##` sections, except `## Changes` (rule 5).
3. A section with nothing to say contains `NIL`. Do not delete it.
4. Inside a section, use bullets, numbered steps or `###` items as the template shows. Do not number paragraphs.

## 2 Tags and citations

1. Acceptance criteria carry a stable tag `[AC-n]` and name the test or command that proves them. Tags are never renumbered or reused.
2. Other stable tags: `D-n` decisions, `TASK-n`, `S-n` slices, `H-n` hypotheses, `C-n` candidate findings, `F-n` confirmed findings.
3. Cite by section number and tag: "spec §3 AC-4", "WO-02 §3 IN", "findings-r1 F-2". Section numbers come from the headings.
4. Criteria MAY use the forms `WHEN <trigger>, the system shall <response>.` or `IF <condition>, THEN the system shall <response>.` What matters is that each one is testable by one test or one command.

## 3 Be concrete

This is the one writing rule that pays for itself in review rounds.

1. Name the thing: a file path, a symbol, a field, a command, a value with its unit. "Responds in under 200 ms at p95", not "responds fast". `src/api/client.ts:42`, not "the API client".
2. Commands are exact and copy-pasteable, in backticks.
3. One term, one meaning. The Spec §2 Terms is the task's only glossary. Other documents cite a term by name; they do not copy the glossary.
4. Do not copy whole sections from one document into another. Cite them. A Work Order carries its own criteria, scope and steps, and cites the spec for terms, design and background.
5. Results use PASS, FAIL, BLOCKED or NIL, so the orchestrator can read them.
6. Evidence is quotable: a command and its exit code, a test name, a file and line, or a screenshot path.

## 4 Size

1. Write what the reader needs to act, not everything that is true. A Work Order is shorter than the Spec it comes from.
2. Prefer one bullet per fact. Long prose paragraphs hide the fact the next agent needs.

## 5 Changes after hand-off

1. Edit the document in place. Git and `state.json` record when.
2. A Spec, Work Order, Plan or Task Card that another agent already read gets a `## Changes` section at the end, one bullet per change: `- r<round or step>: <what changed>, from <source>`. Example: `- r1: added AC-12 and step 7, from findings-r1 F-2.`
3. Other documents (reports, findings, QA, integration) are rewritten for each round under a new file name (`-rN`) or simply updated. They need no Changes section.

## 6 Checker

1. Run it before handing a document on:

```
python3 <this skill dir>/scripts/check_doc.py <file.md> [<file.md> ...]
```

2. Exit 0 is PASS. Exit 1 is FAIL, one finding per line as `file:line: RULE: message`.
3. It checks shape only: the title line names a known type, every template section is present in order, no section is empty, no `{{placeholder}}` is left, and no `[AC-n]` tag is defined twice.
4. It reads each type's sections from the `artifact-templates` skill. Editing a template changes what is checked.
5. A document in the old ICAO layout (a first line in capitals with `AMDT`) is reported as LEGACY and passes, so tasks started before v0.6.0 can finish.
