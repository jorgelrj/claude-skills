---
name: atlassian-multi
description: Reads and writes Jira issues and Confluence pages across several Atlassian Cloud accounts at once, and manages those saved accounts (add, list, test, sync, remove). Use when the user mentions a Jira issue key (ABC-123), JQL, a Jira or Confluence URL, Confluence pages or spaces, or asks to add or manage Atlassian accounts, especially when more than one Atlassian site or login is involved.
---

# Atlassian (multi-account)

Everything goes through one stdlib-only Python script in this skill's directory:

```
python3 <skill-dir>/scripts/atl.py <group> <command> [args]
```

`<skill-dir>` is the base directory this skill was loaded from. Below, `atl`
stands for that whole command. Every command accepts `-a/--account <alias>`,
`--json` (raw API output) and `--dry-run` (reads go out, writes are printed
instead of sent), either before or after the subcommand.

## Which account a call uses

**There is no default account.** Every command has to name its target, and the
account is derived from that:

- **Jira:** the issue key (`DB-12`) or `-p PROJ`. `jira search` and
  `jira create` require `-p`. `-p` takes several keys (`-p DB,RM`) if they're
  all on the same account.
- **Confluence:** `--space KEY` (required for `conf search`), or a page URL.
  A bare page id carries no account, so it needs `-a`.
- **Pasted URLs:** the URL's site picks the account.
- **Commands with no project** (`jira projects`, `jira users`, `conf spaces`,
  `api`): `-a <alias>` is required.

`accounts add` and `accounts sync` index each account's project and space keys.
The CLI refuses, rather than guesses, when:
- a key isn't on any account (run `accounts sync`, or pass `-a`)
- a key is on several accounts (pass `-a`)
- the named things point at different accounts
- `-a` contradicts the key

Don't work around these errors. If the user didn't say which account they
mean, ask them.

Every output line that touches an account ends in `[alias]`. When reporting
results, say which account they came from.

`atl accounts which <KEY ...>` shows where keys route without calling the API.
Add `--space` for space keys.

## Managing accounts

```
atl accounts list                  # tokens are never printed
atl accounts which KEY [KEY ...]   # which account keys route to (--space for space keys)
atl accounts test [alias|--all]    # checks Jira and Confluence separately
atl accounts sync [alias|--all]    # re-index project/space keys after new ones appear
atl accounts edit <alias> [--site S] [--email E] [--prompt-token | --token-env VAR | --token-cmd CMD]
                          [--projects A,B] [--spaces X,Y] [--rename NEW]
atl accounts remove <alias>
```

**Adding an account needs an API token, which must never pass through the
chat.** Don't ask for the token. Give the user this command to run in their own
terminal (it prompts for the token without echoing it, checks the credentials,
then indexes projects and spaces):

```
python3 <skill-dir>/scripts/atl.py accounts add <alias> --site <name>.atlassian.net --email <login-email>
```

Tokens come from https://id.atlassian.com/manage-profile/security/api-tokens.
Use **Create API token**, not "with scopes"; scoped tokens don't work against
the site URL. They expire after at most a year, so a 401 from a working
account usually means it's time to run `accounts edit <alias> --prompt-token`.

If the user keeps secrets in a manager, use `--token-cmd` instead (e.g.
`--token-cmd "op read op://Private/jira-work/credential"`, `"pass show jira/work"`,
`"secret-tool lookup service jira-work"`). Use `--token-env VAR` for CI. With
either, the config file holds no secret.

## Jira

```
atl jira search -p PROJ[,PROJ2] ["<JQL>"] [-n 25]   # JQL is ANDed with the project scope
atl jira get ABC-123 [--comments 10]                 # also accepts the issue URL
atl jira create -p PROJ -t Bug -s "Summary" -d @/tmp/desc.txt [--labels a,b] [--priority High]
                [--assignee me|email|accountId] [--parent ABC-1] [--field customfield_10010='{"value":"x"}']
atl jira update ABC-123 [-s ...] [-d ...] [--add-label x] [--remove-label y] [--assignee none] [--field k=v]
atl jira comment ABC-123 @/tmp/comment.txt
atl jira transitions ABC-123
atl jira move ABC-123 "Done" [--comment "..."]       # transition name, id, or target status
atl jira assign ABC-123 me|none|email
atl jira projects -a <alias> [query]
atl jira types PROJ                                  # issue types
atl jira fields PROJ Bug                             # create fields, required ones starred
atl jira users -a <alias> "name or email"
```

Descriptions and comments use **Jira wiki markup**, not Markdown:

| Want | Write |
|---|---|
| heading | `h2. Title` |
| bold / italic / code | `*bold*` `_italic_` `{{code}}` |
| bullets / numbered | `* item` / `# item` (nest with `**`, `##`) |
| link | `[label\|https://example.com]` |
| code block | `{code:dart}...{code}` |
| quote / panel | `{quote}...{quote}` / `{panel}...{panel}` |
| table | `\|\|head\|\|head\|\|` then `\|cell\|cell\|` |

For anything longer than one line, write it to a temp file and pass `@file`
(or pipe with `-`) instead of fighting shell quoting.

If a create fails on a required field, run `atl jira fields PROJ <Type>` and add
it with `--field`.

## Confluence

```
atl conf search --space ENG[,OPS] --text "deploy runbook" [--type page]
atl conf search --space ENG 'title ~ "release" AND lastmodified > now("-30d")'   # raw CQL
atl conf get <url> --text               # plain text, cheap to read (bare id: add -a <alias>)
atl conf get <url>                      # storage XHTML, lossless; use this before editing
atl conf children <url>
atl conf spaces -a <alias>
atl conf create --space ENG [--parent <id|url>] --title "T" --body @/tmp/page.wiki   # wiki markup
atl conf update <id|url> --body @/tmp/page.xhtml --expect-version N --message "why"
atl conf update <id|url> --title "New title"                          # keeps the body
atl conf comment <id|url> "text"        # wiki markup
atl conf comments <id|url>
```

Editing an existing page:

1. `atl conf get <page>` and note the `version` in the header.
2. Edit the storage XHTML. Keep every `<ac:...>` and `<ri:...>` element as it
   is; those are macros, mentions and attachments.
3. `atl conf update <page> --body @file --expect-version <N>`. The default
   `--format storage` round-trips losslessly. `--expect-version` refuses the
   write if someone else saved in the meantime.

Use `--format wiki` only for new pages or full rewrites. Converting a page with
macros to wiki markup loses them.

## Anything else

`atl -a <alias> api METHOD /path [--param k=v] [--data @body.json]` calls any Jira
(`/rest/api/2|3/...`) or Confluence (`/wiki/rest/api/...`, `/wiki/api/v2/...`)
endpoint with the chosen account's auth. Pass `--read` for a POST that only
reads, so `--dry-run` still sends it.

## Errors

- `HTTP 401`: bad or expired token. Have the user run `accounts edit <alias> --prompt-token`.
- `not on any account` / `exist on several accounts` / `does not match`: the
  routing safeguards. Ask the user which account they mean, or run
  `accounts sync` if the project is new.
- `confluence: FAIL` in `accounts test` with Jira ok: the account has no
  Confluence access on that site. Jira commands still work.
