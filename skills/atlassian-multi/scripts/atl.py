#!/usr/bin/env python3
"""atl: Jira + Confluence Cloud CLI that works with several Atlassian accounts.

Standard library only (Python 3.8+), so it runs anywhere python3 does.
Accounts live in ${ATL_CONFIG:-${XDG_CONFIG_HOME:-~/.config}/atlassian-multi/accounts.json}.
Run `atl.py --help` or `atl.py <group> --help` for usage.
"""
import argparse
import base64
import getpass
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

VERSION = "0.1.0"
ISSUE_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]+)-\d+$", re.I)


class ApiError(Exception):
    pass


def die(msg, code=1):
    print(f"atl: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- config


def config_path():
    if os.environ.get("ATL_CONFIG"):
        return Path(os.environ["ATL_CONFIG"]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "atlassian-multi" / "accounts.json"


def load_config():
    p = config_path()
    if not p.exists():
        return {"accounts": {}}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{p} is not valid JSON: {e}")
    cfg.pop("default", None)  # older configs had a default account; there is none now
    cfg.setdefault("accounts", {})
    return cfg


def save_config(cfg):
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    # mkstemp creates the file 0600, and os.replace keeps the swap atomic.
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".accounts-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def normalize_site(site):
    site = site.strip().rstrip("/")
    if not re.match(r"^https?://", site):
        if "." not in site:
            site += ".atlassian.net"
        site = "https://" + site
    # People paste Jira/Confluence page URLs; keep only scheme://host[:port].
    u = urllib.parse.urlparse(site)
    return f"{u.scheme}://{u.netloc}"


def split_keys(value):
    return [k.strip().upper() for k in (value or "").split(",") if k.strip()]


def token_source(acct):
    if acct.get("token_cmd"):
        return f"cmd: {acct['token_cmd']}"
    if acct.get("token_env"):
        return f"env: ${acct['token_env']}"
    return "stored" if acct.get("token") else "MISSING"


def get_token(alias, acct):
    if acct.get("token_cmd"):
        r = subprocess.run(acct["token_cmd"], shell=True, capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            die(f"token_cmd for '{alias}' failed: {r.stderr.strip() or 'no output'}")
        return r.stdout.strip()
    if acct.get("token_env"):
        value = os.environ.get(acct["token_env"])
        if not value:
            die(f"env var {acct['token_env']} (token for '{alias}') is not set")
        return value
    if acct.get("token"):
        return acct["token"]
    die(f"account '{alias}' has no token; run: atl accounts edit {alias} --prompt-token")


def resolve_alias(cfg, explicit=None, keys=(), kind="projects", site=None, hint="pass -a <alias>"):
    """Picks the account from what the command names: -a, a pasted URL's site, or project/space keys.

    There is deliberately no default account: a command that names nothing, or names things
    that point at different accounts, is an error rather than a guess.
    """
    accts = cfg["accounts"]
    if not accts:
        die("no accounts configured; run: atl accounts add <alias> --site <site> --email <email>")
    if explicit and explicit not in accts:
        die(f"unknown account '{explicit}'; known: {', '.join(sorted(accts))}")
    label = "project" if kind == "projects" else "space"
    owners, evidence = None, []
    if site:
        site = normalize_site(site)
        owners = {a for a, v in accts.items() if v["site"] == site}
        if not owners:
            die(f"no account configured for {site}; add one with: atl accounts add <alias> --site ...")
        evidence.append(site)
    for key in filter(None, (k.upper() for k in keys if k)):
        key_owners = {a for a, v in accts.items() if key in v.get(kind, [])}
        if not key_owners:
            if explicit:
                continue  # e.g. a project created after the last sync; -a vouches for it
            die(f"{label} {key} is not on any account; run `atl accounts sync`, or pass -a <alias>")
        owners = key_owners if owners is None else owners & key_owners
        evidence.append(f"{label} {key}")
        if not owners:
            die(f"{' and '.join(evidence)} are not on the same account")
    if explicit:
        if owners is not None and explicit not in owners:
            die(f"-a {explicit} does not match {' and '.join(evidence)} (on: {', '.join(sorted(owners))})")
        return explicit
    if owners is None:
        die(f"no account named; {hint} (accounts: {', '.join(sorted(accts))})")
    if len(owners) > 1:
        die(f"{' and '.join(evidence)} exist on several accounts ({', '.join(sorted(owners))}); pass -a <alias>")
    return owners.pop()


# --------------------------------------------------------------------------- http


class Client:
    def __init__(self, alias, acct, dry_run=False):
        self.alias = alias
        self.acct = acct
        self.site = acct["site"]
        self.dry_run = dry_run
        self._auth = None

    def _authorization(self):
        if self._auth is None:
            token = get_token(self.alias, self.acct)
            raw = f"{self.acct['email']}:{token}".encode()
            self._auth = "Basic " + base64.b64encode(raw).decode()
        return self._auth

    def request(self, method, path, params=None, body=None, read=False):
        """read=True marks a POST that only reads (JQL search) so --dry-run still sends it."""
        url = self.site + path
        if params:
            params = {k: v for k, v in params.items() if v is not None}
            if params:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        if self.dry_run and method != "GET" and not read:
            print(f"[dry-run:{self.alias}] {method} {url}", file=sys.stderr)
            if body is not None:
                print(json.dumps(body, indent=2), file=sys.stderr)
            return {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._authorization())
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", f"atl/{VERSION}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = summarize_error(e.read().decode("utf-8", errors="replace"))
            raise ApiError(f"{method} {path} -> HTTP {e.code} [{self.alias}]: {detail}{status_hint(e.code)}")
        except urllib.error.URLError as e:
            raise ApiError(f"cannot reach {self.site} [{self.alias}]: {e.reason}")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8", errors="replace")

    def get(self, path, **params):
        return self.request("GET", path, params=params)


def summarize_error(raw):
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()[:500] or "(empty body)"
    parts = []
    if isinstance(j, dict):
        parts += j.get("errorMessages") or []
        errs = j.get("errors")
        if isinstance(errs, dict):
            parts += [f"{k}: {v}" for k, v in errs.items()]
        elif isinstance(errs, list):
            parts += [e.get("detail") or e.get("title") or json.dumps(e) for e in errs if isinstance(e, dict)]
        if j.get("message"):
            parts.append(j["message"])
    return "; ".join(str(p) for p in parts) or raw.strip()[:500]


def status_hint(code):
    return {
        401: " (bad email/token, or the token expired; run: atl accounts test)",
        403: " (this account lacks permission, or has no access to this product)",
        404: " (not found, or not visible to this account; is it on another account?)",
    }.get(code, "")


# --------------------------------------------------------------------------- helpers


def read_text_arg(value):
    """'-' reads stdin, '@path' reads a file, anything else is literal text."""
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).expanduser().read_text(encoding="utf-8")
    return value


def parse_field(kv):
    if "=" not in kv:
        die(f"--field expects key=value, got '{kv}'")
    key, value = kv.split("=", 1)
    try:
        return key, json.loads(value)
    except json.JSONDecodeError:
        return key, value


def emit_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def name_of(obj, key="displayName"):
    return (obj or {}).get(key) or "-"


def page_id_from(ref):
    """Accepts a bare id or any Confluence page URL; returns (id, site-or-None)."""
    if ref.isdigit():
        return ref, None
    m = re.search(r"/pages/(\d+)", ref) or re.search(r"[?&]pageId=(\d+)", ref)
    if not m:
        die(f"cannot find a page id in '{ref}'")
    return m.group(1), ref


def issue_key_from(ref):
    """Accepts ABC-123 or a .../browse/ABC-123 URL; returns (key, site-or-None)."""
    if ISSUE_KEY_RE.match(ref):
        return ref.upper(), None
    m = re.search(r"/browse/([A-Z][A-Z0-9_]+-\d+)", ref, re.I) or re.search(r"selectedIssue=([A-Z][A-Z0-9_]+-\d+)", ref, re.I)
    if not m:
        die(f"'{ref}' is not an issue key or issue URL")
    return m.group(1).upper(), ref


def project_of(key):
    return key.split("-")[0].upper()


class _HtmlToText(HTMLParser):
    BLOCK = {"p", "div", "tr", "pre", "blockquote", "table", "ul", "ol", "ac:structured-macro"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "br" or tag in self.BLOCK:
            # <li><p>text</p></li> should stay on the bullet line.
            if not (self.out and self.out[-1] == "\n- "):
                self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK or re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)

    def unknown_decl(self, data):
        if data.startswith("CDATA["):
            self.out.append(data[6:])

    def text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self.out)).strip()


def html_to_text(html):
    p = _HtmlToText()
    p.feed(html or "")
    p.close()
    return p.text()


# --------------------------------------------------------------------------- accounts


def prompt_token(args, alias):
    if getattr(args, "token_stdin", False) or not sys.stdin.isatty():
        token = sys.stdin.readline().strip()
    else:
        print("Create a token at https://id.atlassian.com/manage-profile/security/api-tokens", file=sys.stderr)
        token = getpass.getpass(f"API token for '{alias}': ").strip()
    if not token:
        die("empty token")
    return token


def apply_token_flags(acct, args, alias, required):
    if args.token_env:
        acct.pop("token", None), acct.pop("token_cmd", None)
        acct["token_env"] = args.token_env
    elif args.token_cmd:
        acct.pop("token", None), acct.pop("token_env", None)
        acct["token_cmd"] = args.token_cmd
    elif required or args.token_stdin or getattr(args, "prompt_token", False):
        acct.pop("token_env", None), acct.pop("token_cmd", None)
        acct["token"] = prompt_token(args, alias)


def whoami(client):
    """Returns {'jira': name-or-error, 'confluence': name-or-error}."""
    result = {}
    for product, path in (("jira", "/rest/api/2/myself"), ("confluence", "/wiki/rest/api/user/current")):
        try:
            me = client.get(path)
            result[product] = {"ok": True, "user": me.get("displayName") or me.get("publicName") or me.get("accountId")}
        except ApiError as e:
            result[product] = {"ok": False, "error": str(e)}
    return result


def collect_keys(client):
    """All project keys and (non-personal) space keys visible to the account."""
    projects, spaces = [], []
    try:
        start = 0
        while start < 2000:
            r = client.get("/rest/api/2/project/search", startAt=start, maxResults=100)
            projects += [p["key"].upper() for p in r.get("values", [])]
            if r.get("isLast", True):
                break
            start += 100
    except ApiError:
        pass
    try:
        cursor = None
        for _ in range(20):
            r = client.get("/wiki/api/v2/spaces", limit=250, cursor=cursor)
            spaces += [s["key"].upper() for s in r.get("results", []) if not s["key"].startswith("~")]
            nxt = (r.get("_links") or {}).get("next")
            if not nxt:
                break
            cursor = urllib.parse.parse_qs(urllib.parse.urlparse(nxt).query).get("cursor", [None])[0]
    except ApiError:
        pass
    return sorted(set(projects)), sorted(set(spaces))


def cmd_accounts_add(args):
    cfg = load_config()
    alias = args.alias
    if alias in cfg["accounts"] and not args.force:
        die(f"account '{alias}' exists; use `atl accounts edit {alias}` or pass --force")
    acct = {"site": normalize_site(args.site), "email": args.email}
    apply_token_flags(acct, args, alias, required=not (args.token_env or args.token_cmd))
    if not args.no_verify:
        client = Client(alias, acct)
        status = whoami(client)
        if not status["jira"]["ok"] and not status["confluence"]["ok"]:
            die(f"credentials rejected, nothing saved:\n  {status['jira']['error']}\n  (re-run with --no-verify to save anyway)")
        for product, s in status.items():
            print(f"  {product}: {'ok as ' + str(s['user']) if s['ok'] else 'unavailable (' + s['error'] + ')'}")
        acct["projects"], acct["spaces"] = collect_keys(client)
    else:
        acct["projects"], acct["spaces"] = [], []
    acct["projects"] = sorted(set(acct["projects"]) | set(split_keys(args.projects)))
    acct["spaces"] = sorted(set(acct["spaces"]) | set(split_keys(args.spaces)))
    cfg["accounts"][alias] = acct
    save_config(cfg)
    print(f"saved '{alias}' ({acct['site']}, {len(acct['projects'])} projects, {len(acct['spaces'])} spaces)")
    shared = {k: [a for a, v in cfg["accounts"].items() if a != alias and k in v.get("projects", [])]
              for k in acct["projects"]}
    shared = {k: v for k, v in shared.items() if v}
    if shared:
        print("  note: these project keys also exist on other accounts, so they need -a: "
              + ", ".join(f"{k} ({', '.join(v)})" for k, v in sorted(shared.items())))


def cmd_accounts_list(args):
    cfg = load_config()
    rows = []
    for alias, a in sorted(cfg["accounts"].items()):
        rows.append({
            "alias": alias,
            "site": a["site"],
            "email": a["email"],
            "token": token_source(a),
            "projects": a.get("projects", []),
            "spaces": a.get("spaces", []),
        })
    if args.json:
        return emit_json({"config": str(config_path()), "accounts": rows})
    if not rows:
        print(f"no accounts (config: {config_path()})")
        return
    for r in rows:
        print(f"{r['alias']:<12} {r['site']:<36} {r['email']:<32} token {r['token']}")
        print(f"    projects: {', '.join(r['projects']) or '-'}")
        print(f"    spaces:   {', '.join(r['spaces']) or '-'}")
    print(f"(config: {config_path()})")


def cmd_accounts_which(args):
    cfg = load_config()
    keys = [project_of(k) if ISSUE_KEY_RE.match(k) else k for k in args.key]
    alias = resolve_alias(cfg, args.account, keys=keys, kind="spaces" if args.space else "projects")
    a = cfg["accounts"][alias]
    print(f"{alias} ({a['site']}, {a['email']})")


def cmd_accounts_edit(args):
    cfg = load_config()
    if args.alias not in cfg["accounts"]:
        die(f"unknown account '{args.alias}'")
    acct = cfg["accounts"][args.alias]
    if args.site:
        acct["site"] = normalize_site(args.site)
    if args.email:
        acct["email"] = args.email
    apply_token_flags(acct, args, args.alias, required=False)
    if args.projects is not None:
        acct["projects"] = split_keys(args.projects)
    if args.spaces is not None:
        acct["spaces"] = split_keys(args.spaces)
    alias = args.alias
    if args.rename:
        if args.rename in cfg["accounts"]:
            die(f"account '{args.rename}' already exists")
        cfg["accounts"][args.rename] = cfg["accounts"].pop(alias)
        alias = args.rename
    save_config(cfg)
    print(f"updated '{alias}'")


def cmd_accounts_remove(args):
    cfg = load_config()
    if args.alias not in cfg["accounts"]:
        die(f"unknown account '{args.alias}'")
    del cfg["accounts"][args.alias]
    save_config(cfg)
    print(f"removed '{args.alias}'")


def cmd_accounts_test(args):
    cfg = load_config()
    aliases = sorted(cfg["accounts"]) if args.all or not (args.alias or args.account) else [args.alias or args.account]
    failed = False
    for alias in aliases:
        if alias not in cfg["accounts"]:
            die(f"unknown account '{alias}'")
        status = whoami(Client(alias, cfg["accounts"][alias]))
        print(f"{alias} ({cfg['accounts'][alias]['site']})")
        for product, s in status.items():
            print(f"  {product:<10} " + (f"ok as {s['user']}" if s["ok"] else f"FAIL {s['error']}"))
        failed |= not status["jira"]["ok"] and not status["confluence"]["ok"]
    sys.exit(1 if failed else 0)


def cmd_accounts_sync(args):
    cfg = load_config()
    aliases = sorted(cfg["accounts"]) if args.all or not (args.alias or args.account) else [args.alias or args.account]
    for alias in aliases:
        if alias not in cfg["accounts"]:
            die(f"unknown account '{alias}'")
        acct = cfg["accounts"][alias]
        acct["projects"], acct["spaces"] = collect_keys(Client(alias, acct))
        print(f"{alias}: {len(acct['projects'])} projects, {len(acct['spaces'])} spaces")
    save_config(cfg)


# --------------------------------------------------------------------------- jira


def jira_client(args, key=None, project=None, url=None, hint="name a project (-p KEY) or pass -a <alias>"):
    cfg = load_config()
    keys = [project_of(key) if key else None] + split_keys(project)
    alias = resolve_alias(cfg, args.account, keys=keys, kind="projects", site=url, hint=hint)
    return Client(alias, cfg["accounts"][alias], dry_run=args.dry_run)


def resolve_user(client, who):
    if who.lower() in ("none", "unassigned", "null"):
        return None
    if who.lower() == "me":
        return client.get("/rest/api/2/myself")["accountId"]
    if re.fullmatch(r"[0-9a-f]{24}|\d+:[0-9a-f-]{36}", who):
        return who
    users = [u for u in client.get("/rest/api/2/user/search", query=who, maxResults=20) if u.get("accountType") == "atlassian"]
    exact = [u for u in users if who.lower() in ((u.get("emailAddress") or "").lower(), (u.get("displayName") or "").lower())]
    picks = exact or users
    if len(picks) == 1:
        return picks[0]["accountId"]
    if not picks:
        die(f"no user matches '{who}' on {client.alias}")
    die(f"'{who}' is ambiguous on {client.alias}: " + "; ".join(f"{u['displayName']} ({u['accountId']})" for u in picks[:8]))


def fmt_issue_line(issue):
    f = issue.get("fields", {})
    return "{key:<10} [{status}] {type} | {assignee} | {summary}".format(
        key=issue["key"],
        status=name_of(f.get("status"), "name"),
        type=name_of(f.get("issuetype"), "name"),
        assignee=name_of(f.get("assignee")) if f.get("assignee") else "unassigned",
        summary=f.get("summary", ""),
    )


def cmd_jira_search(args):
    c = jira_client(args, project=args.project)
    projects = split_keys(args.project)
    scope = f"project = {projects[0]}" if len(projects) == 1 else f"project in ({', '.join(projects)})"
    jql = args.jql.strip()
    if not jql:
        jql = scope
    elif jql.lower().startswith("order by"):
        jql = f"{scope} {jql}"
    else:
        jql = f"{scope} AND ({jql})"
    fields = args.fields.split(",") if args.fields else ["summary", "status", "issuetype", "assignee", "priority", "updated"]
    issues, token, is_last = [], None, True
    while len(issues) < args.limit:
        body = {"jql": jql, "maxResults": min(100, args.limit - len(issues)), "fields": fields}
        if token:
            body["nextPageToken"] = token
        r = c.request("POST", "/rest/api/2/search/jql", body=body, read=True)
        issues += r.get("issues", [])
        token, is_last = r.get("nextPageToken"), r.get("isLast", True)
        if is_last or not token:
            break
    if args.json:
        return emit_json(issues)
    print(f"# {c.alias}: {len(issues)} issue(s){'' if is_last else ' (more available; raise --limit)'}  jql: {jql}")
    for issue in issues:
        print(fmt_issue_line(issue))


def cmd_jira_get(args):
    key, url = issue_key_from(args.key)
    c = jira_client(args, key=key, url=url)
    fields = args.fields or ("summary,status,issuetype,assignee,reporter,priority,labels,created,updated,"
                             "description,parent,subtasks,issuelinks,comment,components,fixVersions")
    issue = c.get(f"/rest/api/2/issue/{key}", fields=fields)
    if args.json:
        return emit_json(issue)
    f = issue["fields"]
    print(f"# {issue['key']}: {f.get('summary')}")
    print(f"{c.site}/browse/{issue['key']}  [{c.alias}]")
    print(f"type: {name_of(f.get('issuetype'), 'name')} | status: {name_of(f.get('status'), 'name')} | "
          f"priority: {name_of(f.get('priority'), 'name')}")
    print(f"assignee: {name_of(f.get('assignee'))} | reporter: {name_of(f.get('reporter'))}")
    if f.get("labels"):
        print("labels: " + ", ".join(f["labels"]))
    if f.get("parent"):
        print(f"parent: {f['parent']['key']} {f['parent']['fields'].get('summary', '')}")
    for st in f.get("subtasks") or []:
        print(f"subtask: {st['key']} [{st['fields']['status']['name']}] {st['fields']['summary']}")
    for link in f.get("issuelinks") or []:
        other = link.get("outwardIssue") or link.get("inwardIssue")
        rel = link["type"]["outward"] if link.get("outwardIssue") else link["type"]["inward"]
        print(f"link: {rel} {other['key']} {other['fields'].get('summary', '')}")
    print(f"created: {f.get('created')} | updated: {f.get('updated')}")
    print("\n## Description\n" + (f.get("description") or "(none)"))
    comments = (f.get("comment") or {}).get("comments") or []
    if comments and args.comments:
        shown = comments[-args.comments:]
        print(f"\n## Comments ({len(shown)} of {len(comments)})")
        for cm in shown:
            print(f"\n--- {name_of(cm.get('author'))} @ {cm.get('created')} (id {cm['id']})\n{cm.get('body', '')}")


def build_issue_fields(c, args, creating):
    fields = {}
    if creating:
        fields["project"] = {"key": args.project.upper()}
        fields["issuetype"] = {"name": args.type}
    if args.summary:
        fields["summary"] = args.summary
    if args.description is not None:
        fields["description"] = read_text_arg(args.description)
    if args.labels is not None:
        fields["labels"] = [l.strip() for l in args.labels.split(",") if l.strip()]
    if args.priority:
        fields["priority"] = {"name": args.priority}
    if getattr(args, "parent", None):
        fields["parent"] = {"key": args.parent.upper()}
    if getattr(args, "assignee", None):
        fields["assignee"] = {"accountId": resolve_user(c, args.assignee)}
    for kv in args.field or []:
        k, v = parse_field(kv)
        fields[k] = v
    return fields


def cmd_jira_create(args):
    c = jira_client(args, project=args.project)
    fields = build_issue_fields(c, args, creating=True)
    r = c.request("POST", "/rest/api/2/issue", body={"fields": fields})
    if args.dry_run:
        return
    if args.json:
        return emit_json(r)
    print(f"created {r['key']}  {c.site}/browse/{r['key']}  [{c.alias}]")


def cmd_jira_update(args):
    key, url = issue_key_from(args.key)
    c = jira_client(args, key=key, url=url)
    body = {"fields": build_issue_fields(c, args, creating=False)}
    label_ops = [{"add": l} for l in args.add_label or []] + [{"remove": l} for l in args.remove_label or []]
    if label_ops:
        body["update"] = {"labels": label_ops}
    if not body["fields"] and not label_ops:
        die("nothing to update")
    c.request("PUT", f"/rest/api/2/issue/{key}", body=body)
    if not args.dry_run:
        print(f"updated {key}  {c.site}/browse/{key}  [{c.alias}]")


def cmd_jira_comment(args):
    key, url = issue_key_from(args.key)
    c = jira_client(args, key=key, url=url)
    r = c.request("POST", f"/rest/api/2/issue/{key}/comment", body={"body": read_text_arg(args.body)})
    if not args.dry_run:
        print(f"commented on {key} (id {r.get('id')})  {c.site}/browse/{key}?focusedCommentId={r.get('id')}  [{c.alias}]")


def cmd_jira_transitions(args):
    key, url = issue_key_from(args.key)
    c = jira_client(args, key=key, url=url)
    r = c.get(f"/rest/api/2/issue/{key}/transitions")
    if args.json:
        return emit_json(r["transitions"])
    for t in r["transitions"]:
        print(f"{t['id']:<6} {t['name']}  ->  {t['to']['name']}")


def cmd_jira_transition(args):
    key, url = issue_key_from(args.key)
    c = jira_client(args, key=key, url=url)
    available = c.get(f"/rest/api/2/issue/{key}/transitions")["transitions"]
    want = args.to.lower()
    match = ([t for t in available if t["id"] == args.to]
             or [t for t in available if t["name"].lower() == want]
             or [t for t in available if t["to"]["name"].lower() == want])
    if len(match) != 1:
        opts = "; ".join(f"{t['id']} {t['name']} -> {t['to']['name']}" for t in available)
        die(f"{'no' if not match else 'ambiguous'} transition '{args.to}' for {key}; available: {opts}")
    body = {"transition": {"id": match[0]["id"]}}
    if args.comment:
        body["update"] = {"comment": [{"add": {"body": read_text_arg(args.comment)}}]}
    if args.field:
        body["fields"] = dict(parse_field(kv) for kv in args.field)
    c.request("POST", f"/rest/api/2/issue/{key}/transitions", body=body)
    if not args.dry_run:
        print(f"{key}: {match[0]['name']} -> {match[0]['to']['name']}  [{c.alias}]")


def cmd_jira_assign(args):
    key, url = issue_key_from(args.key)
    c = jira_client(args, key=key, url=url)
    account_id = resolve_user(c, args.who)
    c.request("PUT", f"/rest/api/2/issue/{key}/assignee", body={"accountId": account_id})
    if not args.dry_run:
        print(f"{key} assigned to {args.who if account_id else 'nobody'}  [{c.alias}]")


def cmd_jira_projects(args):
    c = jira_client(args, hint="pass -a <alias>")
    r = c.get("/rest/api/2/project/search", query=args.query, maxResults=args.limit)
    if args.json:
        return emit_json(r.get("values", []))
    for p in r.get("values", []):
        print(f"{p['key']:<12} {p['name']}")


def cmd_jira_types(args):
    c = jira_client(args, project=args.project)
    r = c.get(f"/rest/api/2/issue/createmeta/{args.project.upper()}/issuetypes")
    types = r.get("issueTypes") or r.get("values") or []
    if args.json:
        return emit_json(types)
    for t in types:
        print(f"{t['id']:<8} {t['name']}" + (" (subtask)" if t.get("subtask") else ""))


def cmd_jira_fields(args):
    c = jira_client(args, project=args.project)
    types = c.get(f"/rest/api/2/issue/createmeta/{args.project.upper()}/issuetypes")
    types = types.get("issueTypes") or types.get("values") or []
    match = [t for t in types if t["name"].lower() == args.type.lower() or t["id"] == args.type]
    if not match:
        die(f"issue type '{args.type}' not in {args.project}: {', '.join(t['name'] for t in types)}")
    r = c.get(f"/rest/api/2/issue/createmeta/{args.project.upper()}/issuetypes/{match[0]['id']}", maxResults=200)
    fields = r.get("fields") or r.get("values") or []
    if args.json:
        return emit_json(fields)
    for f in fields:
        allowed = [v.get("name") or v.get("value") for v in f.get("allowedValues") or []][:15]
        print(f"{f['fieldId']:<22} {'*' if f.get('required') else ' '} {f['name']} ({(f.get('schema') or {}).get('type', '?')})"
              + (f"  values: {', '.join(str(a) for a in allowed)}" if allowed else ""))
    print("(* = required)")


def cmd_jira_users(args):
    c = jira_client(args, hint="pass -a <alias>")
    users = c.get("/rest/api/2/user/search", query=args.query, maxResults=20)
    if args.json:
        return emit_json(users)
    for u in users:
        if u.get("accountType") == "atlassian":
            print(f"{u['accountId']:<40} {u.get('displayName')}  {u.get('emailAddress') or ''}")


# --------------------------------------------------------------------------- confluence


def conf_client(args, space=None, url=None, hint="give a page URL or --space KEY, or pass -a <alias>"):
    cfg = load_config()
    alias = resolve_alias(cfg, args.account, keys=split_keys(space), kind="spaces", site=url, hint=hint)
    return Client(alias, cfg["accounts"][alias], dry_run=args.dry_run)


def space_id(c, key):
    r = c.get("/wiki/api/v2/spaces", keys=key.upper())
    if not r.get("results"):
        die(f"space '{key}' not found on {c.alias}")
    return r["results"][0]["id"]


def page_url(c, page):
    webui = (page.get("_links") or {}).get("webui")
    return f"{c.site}/wiki{webui}" if webui else f"{c.site}/wiki/pages/viewpage.action?pageId={page['id']}"


def cmd_conf_spaces(args):
    c = conf_client(args, hint="pass -a <alias>")
    r = c.get("/wiki/api/v2/spaces", limit=args.limit, keys=args.keys, type=args.type)
    if args.json:
        return emit_json(r.get("results", []))
    for s in r.get("results", []):
        print(f"{s['key']:<14} {s['name']}  (id {s['id']}, {s.get('type')})")


def cmd_conf_search(args):
    if not args.cql and not args.text:
        die("give a CQL query or --text")
    clauses = [args.cql] if args.cql else [f'text ~ "{args.text}"']
    spaces = split_keys(args.space)
    clauses.append(f"space = {spaces[0]}" if len(spaces) == 1 else f"space in ({', '.join(spaces)})")
    if args.type:
        clauses.append(f"type = {args.type}")
    cql = " AND ".join(f"({c})" if " or " in c.lower() else c for c in clauses)
    c = conf_client(args, space=args.space)
    r = c.get("/wiki/rest/api/search", cql=cql, limit=args.limit)
    if args.json:
        return emit_json(r.get("results", []))
    results = r.get("results", [])
    print(f"# {c.alias}: {len(results)} of {r.get('totalSize', '?')} result(s)  cql: {cql}")
    for res in results:
        content = res.get("content") or {}
        space = (res.get("resultGlobalContainer") or {}).get("title", "")
        print(f"{content.get('id', '-'):<12} [{content.get('type', res.get('entityType'))}] {res.get('title') or content.get('title')}"
              f"  | {space} | {c.site}/wiki{res.get('url', '')}")
        excerpt = html.unescape(re.sub(r"@@@(end)?hl@@@", "", res.get("excerpt") or "")).strip()
        if excerpt and not args.no_excerpt:
            print("             " + excerpt.replace("\n", " ")[:200])


def cmd_conf_get(args):
    pid, url = page_id_from(args.page)
    c = conf_client(args, url=url)
    fmt = "view" if args.text else args.format
    page = c.get(f"/wiki/api/v2/pages/{pid}", **{"body-format": fmt})
    if args.json:
        return emit_json(page)
    space = c.get(f"/wiki/api/v2/spaces/{page['spaceId']}")
    body = ((page.get("body") or {}).get(fmt) or {}).get("value", "")
    print(f"# {page['title']}")
    print(f"id {page['id']} | space {space.get('key')} | version {page['version']['number']} | "
          f"parent {page.get('parentId') or '-'} | {page_url(c, page)}  [{c.alias}]")
    print()
    print(html_to_text(body) if args.text else body)


def cmd_conf_children(args):
    pid, url = page_id_from(args.page)
    c = conf_client(args, url=url)
    r = c.get(f"/wiki/api/v2/pages/{pid}/direct-children", limit=args.limit)
    if args.json:
        return emit_json(r.get("results", []))
    for ch in r.get("results", []):
        print(f"{ch['id']:<12} [{ch.get('type')}] {ch.get('title')}")


def cmd_conf_create(args):
    if not args.space and not args.parent:
        die("give --space or --parent")
    parent_id, url = page_id_from(args.parent) if args.parent else (None, None)
    c = conf_client(args, space=args.space, url=url)
    if args.space:
        sid = space_id(c, args.space)
    else:
        sid = c.get(f"/wiki/api/v2/pages/{parent_id}")["spaceId"]
    body = {
        "spaceId": sid,
        "status": "draft" if args.draft else "current",
        "title": args.title,
        "body": {"representation": args.format, "value": read_text_arg(args.body)},
    }
    if parent_id:
        body["parentId"] = parent_id
    page = c.request("POST", "/wiki/api/v2/pages", body=body)
    if args.dry_run:
        return
    if args.json:
        return emit_json(page)
    print(f"created page {page['id']} '{page['title']}'  {page_url(c, page)}  [{c.alias}]")


def cmd_conf_update(args):
    pid, url = page_id_from(args.page)
    c = conf_client(args, url=url)
    if args.body is None and not args.title and not args.parent:
        die("nothing to update; give --body, --title or --parent")
    current = c.get(f"/wiki/api/v2/pages/{pid}", **({"body-format": "storage"} if args.body is None else {}))
    if args.body is None:
        new_body = {"representation": "storage", "value": current["body"]["storage"]["value"]}
    else:
        new_body = {"representation": args.format, "value": read_text_arg(args.body)}
    if args.expect_version and current["version"]["number"] != args.expect_version:
        die(f"page {pid} is at version {current['version']['number']}, not {args.expect_version}; re-read it before overwriting")
    body = {
        "id": pid,
        "status": "current",
        "title": args.title or current["title"],
        "body": new_body,
        "version": {"number": current["version"]["number"] + 1, "message": args.message or "Updated via atl"},
    }
    if args.parent:
        body["parentId"] = page_id_from(args.parent)[0]
    page = c.request("PUT", f"/wiki/api/v2/pages/{pid}", body=body)
    if args.dry_run:
        return
    print(f"updated page {pid} to version {page['version']['number']}  {page_url(c, page)}  [{c.alias}]")


def cmd_conf_comment(args):
    pid, url = page_id_from(args.page)
    c = conf_client(args, url=url)
    r = c.request("POST", "/wiki/api/v2/footer-comments",
                  body={"pageId": pid, "body": {"representation": args.format, "value": read_text_arg(args.body)}})
    if not args.dry_run:
        print(f"commented on page {pid} (comment id {r.get('id')})  [{c.alias}]")


def cmd_conf_comments(args):
    pid, url = page_id_from(args.page)
    c = conf_client(args, url=url)
    r = c.get(f"/wiki/api/v2/pages/{pid}/footer-comments", **{"body-format": "storage", "limit": args.limit})
    if args.json:
        return emit_json(r.get("results", []))
    for cm in r.get("results", []):
        text = html_to_text(((cm.get("body") or {}).get("storage") or {}).get("value", ""))
        print(f"--- comment {cm['id']} by {cm.get('version', {}).get('authorId', '?')} @ {cm.get('version', {}).get('createdAt', '?')}\n{text}\n")


# --------------------------------------------------------------------------- raw api


def cmd_api(args):
    cfg = load_config()
    alias = resolve_alias(cfg, args.account)
    c = Client(alias, cfg["accounts"][alias], dry_run=args.dry_run)
    params = dict(kv.split("=", 1) for kv in args.param or [])
    body = None
    if args.data is not None:
        raw = read_text_arg(args.data)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            die(f"--data is not valid JSON: {e}")
    path = args.path if args.path.startswith("/") else "/" + args.path
    r = c.request(args.method.upper(), path, params=params, body=body, read=args.read)
    if isinstance(r, (dict, list)):
        emit_json(r)
    elif r:
        print(r)


# --------------------------------------------------------------------------- cli


def build_parser():
    # Global flags are accepted both before and after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-a", "--account", default=argparse.SUPPRESS, help="account alias; required when the command names no project, space or URL")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print raw JSON")
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="send reads, but print writes instead of sending them")

    p = argparse.ArgumentParser(prog="atl", parents=[common], description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"atl {VERSION}")
    groups = p.add_subparsers(dest="group", required=True, metavar="{accounts,jira,conf,api}")

    def sub(parent, name, func, help_text, aliases=()):
        sp = parent.add_parser(name, parents=[common], help=help_text, description=help_text, aliases=list(aliases))
        sp.set_defaults(func=func)
        return sp

    def token_flags(sp, prompt_flag):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--token-stdin", action="store_true", help="read the API token from stdin (default: prompt)")
        g.add_argument("--token-env", metavar="VAR", help="read the token from this env var at run time; nothing stored")
        g.add_argument("--token-cmd", metavar="CMD", help="run this shell command to get the token (pass, op, secret-tool, ...)")
        if prompt_flag:
            g.add_argument("--prompt-token", action="store_true", help="prompt for a new token and store it")

    # accounts
    acc = groups.add_parser("accounts", aliases=["account", "acc"], help="add, list, test and remove accounts")
    a = acc.add_subparsers(dest="cmd", required=True)
    sp = sub(a, "add", cmd_accounts_add, "add an account (verifies it and indexes its projects/spaces)")
    sp.add_argument("alias", help="short name, e.g. work, clientx")
    sp.add_argument("--site", required=True, help="acme, acme.atlassian.net or https://acme.atlassian.net")
    sp.add_argument("--email", required=True, help="Atlassian login email for this account")
    token_flags(sp, prompt_flag=False)
    sp.add_argument("--projects", help="extra Jira project keys to route to this account, comma-separated")
    sp.add_argument("--spaces", help="extra Confluence space keys to route to this account, comma-separated")
    sp.add_argument("--no-verify", action="store_true", help="save without checking the credentials")
    sp.add_argument("--force", action="store_true", help="overwrite an existing alias")
    sub(a, "list", cmd_accounts_list, "list accounts (tokens are never printed)", aliases=["ls"])
    sp = sub(a, "which", cmd_accounts_which, "show which account issue/project keys (or --space keys) route to")
    sp.add_argument("key", nargs="+", help="issue or project keys, or space keys with --space")
    sp.add_argument("--space", action="store_true", help="treat keys as Confluence space keys")
    sp = sub(a, "edit", cmd_accounts_edit, "change an account's site, email, token or routing keys")
    sp.add_argument("alias")
    sp.add_argument("--site")
    sp.add_argument("--email")
    token_flags(sp, prompt_flag=True)
    sp.add_argument("--projects", help="replace routed project keys (comma-separated, '' to clear)")
    sp.add_argument("--spaces", help="replace routed space keys (comma-separated, '' to clear)")
    sp.add_argument("--rename", metavar="NEW_ALIAS")
    sp = sub(a, "remove", cmd_accounts_remove, "delete an account", aliases=["rm"])
    sp.add_argument("alias")
    sp = sub(a, "test", cmd_accounts_test, "check credentials against Jira and Confluence")
    sp.add_argument("alias", nargs="?")
    sp.add_argument("--all", action="store_true")
    sp = sub(a, "sync", cmd_accounts_sync, "re-index visible project and space keys for routing")
    sp.add_argument("alias", nargs="?")
    sp.add_argument("--all", action="store_true")

    # jira
    jira = groups.add_parser("jira", aliases=["j"], help="Jira issues")
    j = jira.add_subparsers(dest="cmd", required=True)
    sp = sub(j, "search", cmd_jira_search, "search issues with JQL")
    sp.add_argument("jql", nargs="?", default="ORDER BY updated DESC")
    sp.add_argument("-p", "--project", required=True,
                    help="project key(s), comma-separated; scopes the JQL and picks the account")
    sp.add_argument("-n", "--limit", type=int, default=25)
    sp.add_argument("--fields", help="comma-separated fields to return (with --json)")
    sp = sub(j, "get", cmd_jira_get, "show an issue with description and recent comments", aliases=["view"])
    sp.add_argument("key", help="ABC-123 or an issue URL")
    sp.add_argument("--comments", type=int, default=10, help="how many recent comments to show (0 = none)")
    sp.add_argument("--fields", help="comma-separated fields to fetch (default: a useful set; *all for everything)")

    def issue_field_flags(sp):
        sp.add_argument("-s", "--summary")
        sp.add_argument("-d", "--description", help="Jira wiki markup; '-' = stdin, '@file' = file")
        sp.add_argument("--labels", help="comma-separated; replaces existing labels")
        sp.add_argument("--priority", help="priority name, e.g. High")
        sp.add_argument("--field", action="append", metavar="KEY=VALUE",
                        help="any field; VALUE is parsed as JSON when possible (repeatable)")

    sp = sub(j, "create", cmd_jira_create, "create an issue")
    sp.add_argument("-p", "--project", required=True, help="project key; picks the account")
    sp.add_argument("-t", "--type", default="Task", help="issue type name (default Task)")
    issue_field_flags(sp)
    sp.add_argument("--assignee", help="me, an email/name, or an accountId")
    sp.add_argument("--parent", help="parent issue key (subtasks, or epics in team-managed projects)")
    sp.set_defaults(summary_required=True)
    sp = sub(j, "update", cmd_jira_update, "edit fields of an issue", aliases=["edit"])
    sp.add_argument("key")
    issue_field_flags(sp)
    sp.add_argument("--assignee", help="me, an email/name, an accountId, or none")
    sp.add_argument("--add-label", action="append")
    sp.add_argument("--remove-label", action="append")
    sp = sub(j, "comment", cmd_jira_comment, "add a comment (Jira wiki markup)")
    sp.add_argument("key")
    sp.add_argument("body", help="text; '-' = stdin, '@file' = file")
    sp = sub(j, "transitions", cmd_jira_transitions, "list the transitions available for an issue")
    sp.add_argument("key")
    sp = sub(j, "transition", cmd_jira_transition, "move an issue (by transition name, id, or target status)", aliases=["move"])
    sp.add_argument("key")
    sp.add_argument("to")
    sp.add_argument("--comment", help="comment to add with the transition")
    sp.add_argument("--field", action="append", metavar="KEY=VALUE", help="field required by the transition screen")
    sp = sub(j, "assign", cmd_jira_assign, "assign an issue")
    sp.add_argument("key")
    sp.add_argument("who", help="me, none, an email/name, or an accountId")
    sp = sub(j, "projects", cmd_jira_projects, "list projects")
    sp.add_argument("query", nargs="?")
    sp.add_argument("-n", "--limit", type=int, default=50)
    sp = sub(j, "types", cmd_jira_types, "list issue types of a project")
    sp.add_argument("project")
    sp = sub(j, "fields", cmd_jira_fields, "list the create fields for a project + issue type")
    sp.add_argument("project")
    sp.add_argument("type")
    sp = sub(j, "users", cmd_jira_users, "find users (for accountIds)")
    sp.add_argument("query")

    # confluence
    conf = groups.add_parser("conf", aliases=["confluence", "c"], help="Confluence pages")
    cf = conf.add_subparsers(dest="cmd", required=True)
    sp = sub(cf, "spaces", cmd_conf_spaces, "list spaces")
    sp.add_argument("--keys", help="comma-separated space keys")
    sp.add_argument("--type", choices=["global", "personal"])
    sp.add_argument("-n", "--limit", type=int, default=50)
    sp = sub(cf, "search", cmd_conf_search, "search with CQL (or --text)")
    sp.add_argument("cql", nargs="?")
    sp.add_argument("-t", "--text", help="full-text search instead of raw CQL")
    sp.add_argument("--space", required=True,
                    help="space key(s), comma-separated; scopes the search and picks the account")
    sp.add_argument("--type", choices=["page", "blogpost", "comment", "attachment"])
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.add_argument("--no-excerpt", action="store_true")
    sp = sub(cf, "get", cmd_conf_get, "read a page", aliases=["view"])
    sp.add_argument("page", help="page id or URL")
    sp.add_argument("--format", default="storage", choices=["storage", "atlas_doc_format", "view"],
                    help="body format (default storage: lossless, editable)")
    sp.add_argument("--text", action="store_true", help="render to plain text (read-only, fewer tokens)")
    sp = sub(cf, "children", cmd_conf_children, "list direct children of a page")
    sp.add_argument("page")
    sp.add_argument("-n", "--limit", type=int, default=100)
    sp = sub(cf, "create", cmd_conf_create, "create a page")
    sp.add_argument("--space", help="space key (or give --parent)")
    sp.add_argument("--parent", help="parent page id or URL")
    sp.add_argument("--title", required=True)
    sp.add_argument("--body", required=True, help="'-' = stdin, '@file' = file")
    sp.add_argument("--format", default="wiki", choices=["wiki", "storage"], help="body format (default wiki markup)")
    sp.add_argument("--draft", action="store_true")
    sp = sub(cf, "update", cmd_conf_update, "replace a page's body and/or title", aliases=["edit"])
    sp.add_argument("page")
    sp.add_argument("--title")
    sp.add_argument("--body", help="new full body; '-' = stdin, '@file' = file")
    sp.add_argument("--format", default="storage", choices=["wiki", "storage"],
                    help="body format (default storage, so edits keep macros)")
    sp.add_argument("--parent", help="move under this page (same space)")
    sp.add_argument("--message", help="version comment")
    sp.add_argument("--expect-version", type=int, help="refuse if the page is not at this version")
    sp = sub(cf, "comment", cmd_conf_comment, "add a footer comment to a page")
    sp.add_argument("page")
    sp.add_argument("body", help="'-' = stdin, '@file' = file")
    sp.add_argument("--format", default="wiki", choices=["wiki", "storage"])
    sp = sub(cf, "comments", cmd_conf_comments, "list footer comments on a page")
    sp.add_argument("page")
    sp.add_argument("-n", "--limit", type=int, default=25)

    # raw
    sp = groups.add_parser("api", parents=[common], help="call any REST endpoint with the account's auth")
    sp.set_defaults(func=cmd_api)
    sp.add_argument("method", help="GET, POST, PUT, DELETE")
    sp.add_argument("path", help="/rest/api/2/... (Jira) or /wiki/... (Confluence)")
    sp.add_argument("--param", action="append", metavar="KEY=VALUE")
    sp.add_argument("--data", help="JSON body; '-' = stdin, '@file' = file")
    sp.add_argument("--read", action="store_true", help="this POST only reads, so --dry-run still sends it")
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    for name, default in (("account", None), ("json", False), ("dry_run", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    if getattr(args, "summary_required", False) and not args.summary:
        die("--summary is required")
    try:
        args.func(args)
    except ApiError as e:
        die(str(e))
    except KeyboardInterrupt:
        die("interrupted", 130)


if __name__ == "__main__":
    main()
