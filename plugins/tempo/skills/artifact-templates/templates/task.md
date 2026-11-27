# Task Card: {{task-id}}
Lane: {{S|M|L}} · Issued by: triage

## 1 Request
> {{Jorge's message, verbatim}}

## 2 Terms
- {{Term}}: {{the file, symbol, screen or value it means}}

## 3 Classification
- Type: {{FEATURE | BUG-KNOWN | BUG-FEEDBACK}}
- Size: {{S | M | L}}
- Reason for size: {{files in scope, new design yes/no, data change yes/no}}
- Critical: {{NO | YES, with the rubric §3.10 reason}}

## 4 Clarity
- Target: {{the thing that changes}}. Status: {{PRESENT | ASKED | ANSWERED}}
- Outcome: {{what is true afterwards}}. Status: {{PRESENT | ASKED | ANSWERED}}
- DW-{{n}}: {{one step of the request's Done-when, or of the Outcome when it has none, in the request's words: a result or an action, outside ones too (a comment posted on #92, an issue closed). No assumption drops, shrinks or reassigns one (rubric 2.10).}}
- Anchor: {{screen, error, file or NIL}}. Status: {{PRESENT | EXPLORE WILL FIND}}
- Check: {{how we know it worked, or NIL}}. Status: {{PRESENT | ARCHITECT WILL DRAFT}}
- Sources: {{each source of truth the request or ticket names: FOUND <path> or MISSING; NIL when none}}
- Design: {{NIL | one line per frame: F-n | <screen/route> | <state> | <viewport WxH or device> | <theme> | <file in design/ or prototype route>}}

## 5 Assumptions
- {{Each assumption triage made. The Spec and PR repeat these at the top.}}

## 6 Questions for Jorge
- Q-{{n}}: {{Question}} Options: (a) {{option found in code}} (b) {{option}}. Recommended: {{a}}, because {{reason}}. {{NEEDS-JORGE, only when no option can be recommended; NEEDS-JORGE MISSING-SOURCE when the only options are stand-ins for a missing source}}

## 7 Route
- Next stages: {{for example Explore, Spec, Handoff, Build, Integrate, Review, QA, PR}}
- Spec gate: {{REQUIRED | ONLY IF OPEN DECISIONS | NOT REQUIRED}}
