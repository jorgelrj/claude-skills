---
name: icao-document-standard
description: The TEMPO document standard (ICAO style) for every handoff artifact: fixed numbered sections, NIL for empty, SHALL/SHOULD/MAY only, definitions first, one instruction per line, no vague words, readback, amendment log. Use when writing or checking any .tempo/ artifact, or when asked to write an "ICAO document".
---

# TEMPO Document Standard (ICAO style)

Every artifact in `.tempo/<task-id>/` SHALL follow this standard.
A document that breaks a rule is sent back to its author before the next agent reads it.
The rules come from ICAO Annexes, Simplified Technical English (ASD-STE100) and ATC readback.

## 1 Header

1.1 Line 1 SHALL be the document type in capitals, then the task ID, document ID and amendment number.
1.2 Line 2 SHALL list the lane, dependencies and the issuing agent.

```
WORK ORDER                                        T-042 / WO-02   AMDT 0
LANE: L          DEPENDS ON: WO-01          ISSUED BY: architect
```

## 2 Fixed sections

2.1 Each artifact type has a fixed list of sections, defined by its template in the `artifact-templates` skill.
2.2 Every section SHALL be present, in template order, with the template's number.
2.3 An empty section SHALL contain exactly `NIL`. A missing section is always an error.
2.4 Paragraphs SHALL be numbered `<section>.<n>` so any line can be cited, for example "WO-02 §7.1".
2.5 Sub-paragraphs MAY use a third level, for example `5.3.1`.

## 3 Normative words

3.1 Only four words carry obligation. Use them in capitals.

| Word       | Meaning                          |
|------------|----------------------------------|
| SHALL      | Mandatory.                       |
| SHALL NOT  | Forbidden.                       |
| SHOULD     | Recommended. Deviation is reported. |
| MAY        | Optional.                        |

3.2 The words "must", "need to", "have to", "required to", "ought to", "will" (as an obligation) and "can" (as permission) SHALL NOT be used for obligation.
3.3 Acceptance criteria SHALL use EARS form: `WHEN <trigger>, THE SYSTEM SHALL <response>.` Other EARS forms MAY be used:
  - `WHILE <state>, THE SYSTEM SHALL <response>.`
  - `IF <unwanted condition>, THEN THE SYSTEM SHALL <response>.`
  - `THE SYSTEM SHALL <response>.` (always true)
3.4 Each acceptance criterion SHALL carry a stable tag, for example `[AC-3]`. Tags are never renumbered.

## 4 Definitions

4.1 Section 2 of every artifact is DEFINITIONS.
4.2 Every term the task depends on SHALL be defined there, bound to a concrete thing: a file, symbol, field, screen or value.
4.3 One term has one meaning. After a term is defined, no synonym SHALL be used for it.
4.4 If no terms are needed, the section is `NIL`.

## 5 Sentences

5.1 One instruction per line.
5.2 Procedures SHALL use the imperative and active voice: "Add the badge", not "The badge should be added".
5.3 A procedure line SHALL be 20 words or fewer. A descriptive line SHOULD be 25 words or fewer.
5.4 Conditions SHALL use `IF ..., THEN ...`.
5.5 Lists SHALL NOT end with "etc." or "and so on". List every item, or state the rule that selects them.

## 6 Bound words

6.1 Every noun phrase SHALL point to one thing. Name the file, the symbol, the value and the unit.
6.2 The following are rejected unless bound by a definition or a value in the same line:
  - Vague quality: fast, slow, quickly, properly, correctly, appropriate, appropriately, reasonable, robust, clean, nice, good, better, simple, easy, intuitive, user-friendly, seamless.
  - Vague quantity: some, several, many, few, a lot, various, a bit, minor, large, small (as a size of change).
  - Vague scope: as needed, if needed, where necessary, as appropriate, and so on, etc., similar, related, relevant, other stuff.
  - Hedges: should probably, maybe, perhaps, might want to, try to, ideally, hopefully.
  - Unbound references: "the button", "the API", "the component", "this", "that", "it" at the start of a line.
6.3 Replace a vague word with a value: "responds in under 200 ms at p95", not "responds fast".

## 7 Readback

7.1 A receiver of a Work Order SHALL write a readback before any edit.
7.2 The readback SHALL restate:
  - 7.2.1 The objective, in one sentence.
  - 7.2.2 Every file it will change.
  - 7.2.3 Every acceptance criterion tag it owns.
7.3 The orchestrator SHALL compare the readback with the document.
7.4 IF the readback does not match, THEN the document is fixed and re-issued as a new amendment. The receiver is not corrected in conversation.

## 8 Amendments

8.1 A document SHALL NOT be edited silently after another agent has read it.
8.2 A change SHALL increment the AMDT number in the header.
8.3 A change SHALL add one line to the AMENDMENT LOG: `AMDT <n>   <YYYY-MM-DD>   <what changed and why>`.
8.4 The first issue is `AMDT 0   <date>   Issued.`

## 9 Status lines

9.1 Results SHALL use the words PASS, FAIL, BLOCKED or NIL. No other result words are used.
9.2 Evidence SHALL be quotable: a command and its exit code, a test name, a file and line, or a screenshot path.

## 10 Checking a document

10.1 Run the checker from this skill's directory before handing a document on:

```
python3 <this skill dir>/scripts/check_doc.py <file.md> [<file.md> ...]
```

10.2 Exit code 0 means PASS. Exit code 1 means FAIL, with one finding per line as `file:line: RULE: message`.
10.3 The checker covers rules 2, 3.1 (capitals), 3.2, 5.3, 5.5, 6.2 (word lists) and 8 mechanically. It also rejects leftover `{{placeholders}}`.
10.4 Rules 4.3, 5.2, 6.1, 6.2 (unbound references) and 7 need a reader. The orchestrator SHALL read for them.
10.5 The checker reads each type's section list from the `artifact-templates` skill. Editing a template changes what is checked.
10.6 Text inside backticks, double quotes and `<!-- -->` comments is not word-checked. Quote user text; do not rewrite it.
10.7 A finding that is a false positive MAY be waived by adding `<!-- icao-waive: <RULE> <reason> -->` on the same line.
