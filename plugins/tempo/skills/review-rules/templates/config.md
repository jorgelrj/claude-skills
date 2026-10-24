# .tempo/config.md

Settings TEMPO reads for this repository. Every line is optional. Delete a line to use the default.

## Commands

- test: npm test
- test-one: npm test -- {{pattern}}
- build: npm run build
- typecheck: npm run typecheck
- lint: npm run lint
- run-app: NIL

## Git

- base-branch: main
- branch-prefix: tempo/
- worktree-root: .tempo/worktrees

## Limits

- max-parallel-builders: 3
- review-rounds: 3
- qa-rounds: 3
- repro-hypotheses: 3
- repro-minutes: 30

## Pull request

- open-as-draft: yes
- pr-tool: gh
