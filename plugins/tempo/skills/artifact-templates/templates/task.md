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

## 4 Clarity
- Target: {{the thing that changes}}. Status: {{PRESENT | ASKED | ANSWERED}}
- Outcome: {{what is true afterwards}}. Status: {{PRESENT | ASKED | ANSWERED}}
- Anchor: {{screen, error, file or NIL}}. Status: {{PRESENT | EXPLORE WILL FIND}}
- Check: {{how we know it worked, or NIL}}. Status: {{PRESENT | ARCHITECT WILL DRAFT}}
- Sources: {{each source of truth the request or ticket names: FOUND <path> or MISSING; NIL when none}}

## 5 Assumptions
- {{Each assumption triage made. The Spec and PR repeat these at the top.}}

## 6 Questions for Jorge
- {{Question}} Options: (a) {{option found in code}} (b) {{option}} (c) other. Recommended: {{a}}. {{NEEDS-JORGE, only when no option can be recommended; NEEDS-JORGE MISSING-SOURCE when the only options are stand-ins for a missing source}}

## 7 Route
- Next stages: {{for example Explore, Spec, Handoff, Build, Integrate, Review, QA, PR}}
- Spec gate: {{REQUIRED | ONLY IF OPEN DECISIONS | NOT REQUIRED}}
