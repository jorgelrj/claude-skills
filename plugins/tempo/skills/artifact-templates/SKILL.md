---
name: artifact-templates
description: Templates for every TEMPO handoff artifact (Task Card, Context Map, Hypotheses, Repro and Root Cause Report, Spec, Work Order, Work Report, Integration Report, Raw Findings, Findings, QA Report, PR Summary, Escalation, Task State). Use when an agent writes or reads a file in .tempo/<task-id>/.
---

# TEMPO artifact templates

All templates live in `templates/` next to this file.
Every artifact follows the `document-standard` skill: structured markdown in the template's shape.

## How to use a template

1. Read the template file.
2. Copy it to the target path in `.tempo/<task-id>/`.
3. Replace every `{{placeholder}}`. Repeat a bullet or `###` item for each entry.
4. Write `NIL` in any section with nothing to say. Do not delete sections.
5. Run the checker from the `document-standard` skill. It checks structure only. Fix every finding before handing on.

## Index

| Artifact file in `.tempo/<task-id>/` | Template | Written by | Read by |
|---|---|---|---|
| `state.md` + `state.json` | `state.md` | `tempo_state.py` only | orchestrator, `/tempo:resume` |
| `plan.md` | `plan.md` | orchestrator (single repo), architect (workspace) | Jorge (gate), child tasks |
| `tracker.md` | none, generated | `tempo_state.py tracker` | Jorge (workspace tasks) |
| `prompts/<label>.md` | none | orchestrator | orchestrator after a restart |
| `task.md` | `task.md` | triage | everyone downstream |
| `context.md` | `context.md` | orchestrator, merged from scout reports | architect |
| `hypotheses.md` | `hypotheses.md` | investigator | reproducer |
| `repro.md` | `repro.md` | reproducer (sections 1–4), then reproducer in root-cause mode (5–9) | architect, builder via Work Order, reviewers, qa |
| `spec.md` | `spec.md` | architect | Jorge (gate), reviewers, qa |
| `wo-NN.md` | `work-order.md` | architect | one builder |
| `report-NN.md` | `work-report.md` | builder | integrator |
| `integration.md` | `integration.md` | integrator | reviewers, qa |
| `review/<lens>-rN.md` | `raw-findings.md` | reviewer | verifier |
| `findings-rN.md` | `findings.md` | verifier | orchestrator, builders |
| `qa-rN.md` | `qa.md` | qa | orchestrator |
| `pr.md` | `pr-summary.md` | orchestrator | Jorge, becomes the PR body |
| `esc-N.md` | `escalation.md` | any agent, sent by orchestrator | Jorge |

`state.md` is a live ledger. `tempo_state.py` (orchestrator skill, `scripts/`) renders it from `state.json` after every change; nobody edits either by hand.

## Folder layout for one task

```
.tempo/
  T-042/
    state.md
    task.md
    context.md          (feature flow)
    hypotheses.md       (bug flow, user feedback only)
    repro.md            (bug flow)
    spec.md             (feature flow, M and L lanes)
    wo-01.md  report-01.md
    wo-02.md  report-02.md
    integration.md
    review/correctness-r1.md  review/security-r1.md  review/spec-r1.md
    findings-r1.md
    qa-r1.md
    pr.md
    esc-1.md
  worktrees/
    T-042-wo-01/        (git worktree, removed after integration)
```
