# claude-skills

Reusable [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills).

| Skill | What it does |
|---|---|
| [atlassian-multi](skills/atlassian-multi) | Jira + Confluence Cloud across several Atlassian accounts, routed by project so nothing hits the wrong site |

## Layout

```
skills/<name>/SKILL.md      # the skill (instructions + frontmatter)
skills/<name>/scripts/      # code the skill runs
skills/<name>/tests/        # tests for that code
.claude/skills/<name>       # symlink to skills/<name>, so a Claude session opened here loads it
```

## Using a skill

Symlink or copy the folder into `~/.claude/skills/` (all projects) or
`<project>/.claude/skills/` (one project):

```sh
ln -s "$PWD/skills/atlassian-multi" ~/.claude/skills/atlassian-multi
```

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` and `description` frontmatter.
2. `ln -s ../../skills/<name> .claude/skills/<name>` so it can be tried here.
3. Add a row to the table above.

## Tests

```sh
python3 -m unittest discover -s skills/<name>/tests -v
```
