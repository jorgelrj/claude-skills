---
description: Write or update TEMPO's config for this repo (.tempo/config.yaml) or for a multi-repo workspace (.tempo/workspace.yaml), detected from the code, then check it.
argument-hint: [repo | workspace] [notes, e.g. "Java 21, branches feat/AV-XXXX, PRs in Portuguese"]
---

Set up TEMPO config here: $ARGUMENTS

1. Load the TEMPO `config` skill (listed as `tempo:config` when installed as a plugin). Resolve `<cfg>` as its §3.1 says.
2. Decide the scope:
   - IF the first word above is `repo` or `workspace`, THEN use it.
   - ELSE IF the working directory is inside a git repository, THEN scope is `repo`.
   - ELSE IF it holds two or more git repositories within 3 levels, THEN scope is `workspace`.
   - ELSE stop and tell me there is nothing to configure here.
3. IF the target file exists, THEN read it and update it. Change only what the detection or my notes contradict. List each change before writing.
4. IF a legacy `.tempo/config.md` exists, THEN start from `<cfg> migrate .tempo/config.md` and carry over its UNMAPPED lines where a key fits.
5. Detect, for each repo in scope:
   - 5.1 Build tool and commands: package.json scripts, pom.xml or mvnw, build.gradle, pubspec.yaml, Makefile, pyproject.toml, go.mod, Cargo.toml.
   - 5.2 Toolchain: required JDK, Node or Python version (pom.xml `java.version`, `.nvmrc`, `.tool-versions`, `.python-version`) and where it is installed on this machine. Put machine paths in `env:` with `${env:HOME}`, never a literal home path.
   - 5.3 Base branch: the remote default branch, or `develop` if the team branches from it (`git branch -r`).
   - 5.4 Branch pattern: the 30 most recent remote branches (`git for-each-ref --sort=-committerdate refs/remotes`). Turn the common shape into a template, e.g. `feat/AV-1234` → `feat/{ticket}`.
   - 5.5 Commit and PR conventions: the last 30 commit subjects, `.github/pull_request_template.md`, and title rules in `.github/workflows/*`, commitlint or danger config. Record the language they are written in.
   - 5.6 Hooks that block commits on this machine (a pre-commit hook that fails) → `git.commit.extra_args: [--no-verify]` only with my yes.
   - 5.7 Worktree needs: gitignored files the build or tests read (`.env*`, local config, keys) → `worktree.copy`; large dependency folders → `worktree.link` or a `worktree.setup` install step.
   - 5.8 Workspace only: one `repos:` entry per repo with its path; shared settings in `defaults:`; repeated env and commands in `toolchains:`; `depends_on` from build dependencies between the repos (shared libraries, migrations).
6. Write the file from the skill's template (`templates/config.yaml` or `templates/workspace.yaml`). Replace `{{schema-path}}` with the absolute path of the schema. Keep the comments. Delete keys that equal the defaults, except `commands` and `git`.
7. Make sure `.tempo/` is in `.git/info/exclude` of every repo in scope.
8. Run `<cfg> check` (and `<cfg> check --repo <path>` for each workspace repo). Fix every finding before you finish.
9. Show me the file and every guess you made (marked as guesses). IF a `REVIEW.md` is absent, THEN offer once to copy the starter from the `review-rules` skill's `templates/` folder.
