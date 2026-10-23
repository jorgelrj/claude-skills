# atlassian-multi

A Claude skill for Jira and Confluence Cloud that works with several Atlassian
accounts at once. Each command is routed by the project or space it names. It's a single Python
script with no dependencies (Python 3.8+) and runs on macOS, Linux and
Windows/WSL.

## Install

From the [jorgelrj-skills](../../../../README.md) marketplace:

```sh
claude plugin marketplace add jorgelrj/claude-skills
claude plugin install atlassian-multi@jorgelrj-skills
```

Then ask Claude to "add a Jira account". It gives you the exact `accounts add`
command for where the plugin is installed. Run that command in your own
terminal, because it prompts for the API token.

To use the CLI outside Claude, clone the repo and put the script on your PATH:

```sh
ln -s "$PWD/plugins/atlassian-multi/skills/atlassian-multi/scripts/atl.py" ~/.local/bin/atl
```

## Accounts

Each account is an alias plus a site, a login email and an API token. Use a
classic token from
<https://id.atlassian.com/manage-profile/security/api-tokens> (**Create API
token**, not the scoped kind). The same token works for both Jira and
Confluence.

```sh
atl accounts add work   --site acme.atlassian.net   --email me@acme.com     # prompts for the token
atl accounts add client --site client.atlassian.net --email me@client.com
atl accounts list
atl accounts which DB-12         # which account a key routes to
atl accounts test --all          # checks Jira and Confluence for every account
atl accounts edit work --prompt-token     # rotate an expired token
atl accounts remove client
```

There is **no default account**, so a command can't land on the wrong site by
accident. `add` checks the credentials and indexes every project and space key
the account can see, and each command picks its account from what it names:

- `atl jira get DB-12` and `atl jira search -p DB` go to whichever account owns `DB`.
- `atl conf search --space ENG …` goes to the account that owns the `ENG` space.
- Pasted URLs go to the account for that site.
- Commands that name no project (`jira projects`, `conf spaces`, `api`, a bare
  page id) need `-a <alias>`.

The command fails instead of guessing when a key is unknown, a key is on
several accounts, or `-a` contradicts the key. Run `accounts sync` after new
projects or spaces appear.

### Where tokens live

The config is `${XDG_CONFIG_HOME:-~/.config}/atlassian-multi/accounts.json`
(override with `ATL_CONFIG`). Its folder is mode 0700 and the file 0600, the
same model as `gh` or `~/.netrc`. To keep tokens out of the file entirely:

```sh
atl accounts add work ... --token-cmd "op read op://Private/jira-work/credential"   # 1Password
atl accounts add work ... --token-cmd "pass show atlassian/work"                    # pass
atl accounts add work ... --token-cmd "secret-tool lookup service atlassian-work"   # GNOME keyring
atl accounts add work ... --token-cmd "security find-generic-password -s atlassian-work -w"  # macOS
atl accounts add ci   ... --token-env ATLASSIAN_TOKEN                                # CI
```

## Usage

Run `atl --help` and `atl <group> <command> --help`. [SKILL.md](SKILL.md) has
the full command reference Claude follows.

## Tests

```sh
python3 -m unittest discover -s plugins/atlassian-multi/skills/atlassian-multi/tests -v
```

The tests run the CLI end to end against two fake Atlassian sites on
localhost. No network access or real accounts needed.
