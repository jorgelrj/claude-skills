# REVIEW.md

Rules TEMPO reviewers apply to every pull request in this repository.
Reviewers read this file from the base branch. Edit it on the base branch to change the rules.

## 1 Always flag

1.1 A changed code path with no test that exercises it.
1.2 A public function, endpoint or screen whose behaviour changed without a matching acceptance criterion.
1.3 Secrets, tokens or personal data in code, logs or fixtures.
1.4 A new dependency.
1.5 A database migration that is not reversible.

## 2 Never flag

2.1 Formatting that the formatter fixes.
2.2 Naming preferences not stated in this file or CLAUDE.md.

## 3 Project conventions

3.1 NIL
