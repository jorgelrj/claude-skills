# Findings: {{task-id}} / R{{round}}
Inputs: {{raw findings file list}} · Issued by: verifier
Severity: as in the Raw Findings template. Confirmed = the verifier read the code and the failure scenario holds. Introduced = the finding's lines are in the fix diff, or its failure scenario exists only because of the last fix. Blocking = the finding must be fixed before the task ships: HIGH is always yes, LOW always no, and a MEDIUM is yes only when it breaks an acceptance criterion or Done-when line, or is a correctness or security defect in a line this diff changes, and it cannot wait for a follow-up.

## 1 Scope
- Round: {{n}} of {{limit}}. Kind: {{FULL | NARROW}}
- Lenses: {{CORRECTNESS, SECURITY, SPEC}}
- Diff: {{base hash}}..{{head hash}}
- Fix diff: {{previous round head}}..{{head hash}}, or NIL in round 1

## 2 Confirmed findings
### F-1: {{HIGH | MEDIUM | LOW}} · `{{path:line}}` · Lens: {{lens}} · Owner: WO-{{nn}}
- Problem: {{one line}}. {{REPEAT, or INTRODUCED BY r<n> F-<n>, or NIL}}
- Area: {{Spec §8 entity, or the files of the finding}}
- Fix kind: {{LOCAL | STATE}}
- Failure scenario: {{concrete input or state, and the wrong output}}
- Blocking: {{yes | no}}. Breaks: {{AC-n or the Done-when line, CODE for a correctness or security defect in a changed line, or NIL}}. Can't wait: {{why it cannot be a follow-up, or NIL}}
- Evidence: {{code quote or command output}}
- Fix direction: {{one line}}

## 3 Dropped findings
- {{lens}} C-{{n}}: {{FALSE POSITIVE | DUPLICATE OF F-n | OUT OF SCOPE}}. Reason: {{one line}}

## 4 Sibling sweep
- `{{path:line}}`: {{same pattern; IN SCOPE or LISTED ONLY}}. NIL outside the bug lane.

## 5 Left open
- F-{{n}}: {{reason it is not fixed in this PR}}

## 6 Result
- {{PASS | FAIL}}. PASS means no confirmed HIGH or MEDIUM finding remains.
- Introduced findings: {{count}}. Areas: {{list or NIL}}
