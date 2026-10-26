# Findings: {{task-id}} / R{{round}}
Inputs: {{raw findings file list}} · Issued by: verifier
Severity: as in the Raw Findings template. Confirmed = the verifier read the code and the failure scenario holds. Introduced = the finding's lines are in the fix diff, or its failure scenario exists only because of the last fix.

## 1 Scope
- Round: {{n}} of {{limit}}. Kind: {{FULL | NARROW}}
- Lenses: {{CORRECTNESS, SECURITY, SPEC}}
- Diff: {{base hash}}..{{head hash}}
- Fix diff: {{previous round head}}..{{head hash}}, or NIL in round 1

## 2 Confirmed findings
### F-1: {{HIGH | MEDIUM | LOW}} · `{{path:line}}` · Lens: {{lens}} · Owner: WO-{{nn}}
- Problem: {{one line}}. {{REPEAT, or INTRODUCED BY r<n> F-<n>, or NIL}}
- Area: {{Spec §8 entity, or the files of the finding}}
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
