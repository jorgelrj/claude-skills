"""End-to-end tests for atl.py against two fake Atlassian sites (stdlib only).

Run: python3 -m unittest discover -s skills/atlassian-multi/tests -v
"""
import base64
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ATL = Path(__file__).resolve().parent.parent / "scripts" / "atl.py"


class FakeSite:
    """A tiny Jira + Confluence stand-in that records every request."""

    def __init__(self, email, token, projects, spaces):
        self.auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
        self.projects = projects
        self.spaces = spaces
        self.requests = []
        self.page_version = 3
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                u = urlparse(self.path)
                site.requests.append({"method": self.command, "path": u.path, "query": parse_qs(u.query),
                                      "body": body, "auth": self.headers.get("Authorization")})
                if self.headers.get("Authorization") != site.auth:
                    return self._send(401, {"errorMessages": ["Client must be authenticated"]})
                status, payload = site.route(self.command, u.path, parse_qs(u.query), body)
                self._send(status, payload)

            def _send(self, status, payload):
                raw = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def route(self, method, path, q, body):
        if path == "/rest/api/2/myself":
            return 200, {"accountId": "aaaaaaaaaaaaaaaaaaaaaaaa", "displayName": "Test User"}
        if path == "/wiki/rest/api/user/current":
            return 200, {"accountId": "aaaaaaaaaaaaaaaaaaaaaaaa", "displayName": "Test User"}
        if path == "/rest/api/2/project/search":
            return 200, {"isLast": True, "values": [{"key": k, "name": k + " project"} for k in self.projects]}
        if path == "/wiki/api/v2/spaces":
            keys = q.get("keys", [None])[0]
            res = [{"id": str(100 + i), "key": k, "name": k + " space", "type": "global"}
                   for i, k in enumerate(self.spaces + ["~personal"]) if not keys or k == keys]
            return 200, {"results": res, "_links": {}}
        if re.fullmatch(r"/wiki/api/v2/spaces/\d+", path):
            return 200, {"id": path.rsplit("/", 1)[1], "key": self.spaces[0]}
        if path == "/rest/api/2/search/jql":
            key = self.projects[0]
            issues = [{"key": f"{key}-{i}", "fields": {"summary": f"Issue {i}", "status": {"name": "To Do"},
                                                          "issuetype": {"name": "Task"}, "assignee": None}}
                      for i in range(1, 4)]
            if body.get("nextPageToken"):
                return 200, {"issues": issues[2:], "isLast": True}
            return 200, {"issues": issues[:2], "nextPageToken": "tok2", "isLast": False}
        if path == "/rest/api/2/issue" and method == "POST":
            return 201, {"id": "10001", "key": body["fields"]["project"]["key"] + "-99"}
        m = re.fullmatch(r"/rest/api/2/issue/([A-Z]+-\d+)", path)
        if m and method == "GET":
            return 200, {"key": m.group(1), "fields": {
                "summary": "Fix the thing", "status": {"name": "In Progress"}, "issuetype": {"name": "Bug"},
                "priority": {"name": "High"}, "assignee": {"displayName": "Ann"}, "reporter": {"displayName": "Bob"},
                "labels": ["api"], "description": "h2. Steps\n# one", "created": "c", "updated": "u",
                "comment": {"comments": [{"id": "5", "author": {"displayName": "Ann"}, "created": "t", "body": "looks good"}]}}}
        if m and method == "PUT":
            return 204, None
        if path.endswith("/transitions") and method == "GET":
            return 200, {"transitions": [{"id": "11", "name": "Start", "to": {"name": "In Progress"}},
                                         {"id": "31", "name": "Finish", "to": {"name": "Done"}}]}
        if path.endswith("/transitions") and method == "POST":
            return 204, None
        if path.endswith("/comment") and method == "POST":
            return 201, {"id": "777"}
        if path.endswith("/assignee"):
            return 204, None
        if path == "/rest/api/2/user/search":
            return 200, [{"accountId": "bbbbbbbbbbbbbbbbbbbbbbbb", "displayName": "Ann Lee",
                          "emailAddress": "ann@x.com", "accountType": "atlassian"}]
        if path == "/wiki/rest/api/search":
            return 200, {"totalSize": 1, "results": [{"title": "Runbook", "url": "/spaces/ENG/pages/42",
                                                       "excerpt": "@@@hl@@@deploy@@@endhl@@@ steps",
                                                       "content": {"id": "42", "type": "page"},
                                                       "resultGlobalContainer": {"title": "Engineering"}}]}
        m = re.fullmatch(r"/wiki/api/v2/pages/(\d+)", path)
        if m and method == "GET":
            page = {"id": m.group(1), "title": "Runbook", "spaceId": "100", "parentId": "1",
                    "version": {"number": self.page_version}, "_links": {"webui": "/spaces/ENG/pages/42"}}
            fmt = q.get("body-format", [None])[0]
            if fmt:
                page["body"] = {fmt: {"value": "<h1>Deploy</h1><p>Run <code>make</code></p><ul><li>a</li></ul>"}}
            return 200, page
        if m and method == "PUT":
            return 200, {"id": m.group(1), "title": body["title"], "version": body["version"],
                         "_links": {"webui": "/spaces/ENG/pages/42"}}
        if path == "/wiki/api/v2/pages" and method == "POST":
            return 200, {"id": "555", "title": body["title"], "_links": {"webui": "/spaces/ENG/pages/555"}}
        if path == "/wiki/api/v2/footer-comments":
            return 201, {"id": "888"}
        return 404, {"errorMessages": [f"no route {method} {path}"]}

    def last(self, method, path):
        return [r for r in self.requests if r["method"] == method and r["path"] == path][-1]

    def count(self, method, path):
        return len([r for r in self.requests if r["method"] == method and r["path"] == path])


class AtlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = FakeSite("me@work.com", "work-token", ["WRK", "OPS"], ["ENG"])
        cls.client = FakeSite("me@client.com", "client-token", ["DB"], ["DOCS"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "cfg" / "accounts.json"
        self.env = {**os.environ, "ATL_CONFIG": str(self.cfg)}
        self.env.pop("ATL_ACCOUNT", None)

    def tearDown(self):
        self.tmp.cleanup()

    def atl(self, *args, stdin="", ok=True, env=None):
        r = subprocess.run([sys.executable, str(ATL), *args], input=stdin, capture_output=True, text=True,
                           env=env or self.env, timeout=30)
        if ok and r.returncode != 0:
            self.fail(f"atl {' '.join(args)} failed ({r.returncode}):\n{r.stderr}")
        if not ok and r.returncode == 0:
            self.fail(f"atl {' '.join(args)} unexpectedly succeeded:\n{r.stdout}")
        return r

    def add_both(self):
        self.atl("accounts", "add", "work", "--site", self.work.url, "--email", "me@work.com", "--token-stdin",
                 stdin="work-token\n")
        self.atl("accounts", "add", "client", "--site", self.client.url, "--email", "me@client.com",
                 "--token-stdin", stdin="client-token\n")

    # ---------------------------------------------------------------- accounts

    def test_add_stores_private_config_and_indexes_keys(self):
        self.add_both()
        cfg = json.loads(self.cfg.read_text())
        self.assertNotIn("default", cfg)
        self.assertEqual(cfg["accounts"]["work"]["projects"], ["OPS", "WRK"])
        self.assertEqual(cfg["accounts"]["work"]["spaces"], ["ENG"])  # personal ~space skipped
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o600)

    def test_add_rejects_bad_token_and_saves_nothing(self):
        r = self.atl("accounts", "add", "work", "--site", self.work.url, "--email", "me@work.com",
                     "--token-stdin", stdin="wrong\n", ok=False)
        self.assertIn("credentials rejected", r.stderr)
        self.assertFalse(self.cfg.exists())

    def test_list_never_prints_tokens(self):
        self.add_both()
        out = self.atl("accounts", "list").stdout + self.atl("accounts", "list", "--json").stdout
        self.assertNotIn("work-token", out)
        self.assertNotIn("client-token", out)
        self.assertIn("work ", out)

    def test_which_edit_remove(self):
        self.add_both()
        self.assertIn("work", self.atl("accounts", "which", "WRK-12").stdout)
        self.assertIn("client", self.atl("accounts", "which", "DB").stdout)
        self.assertIn("work", self.atl("accounts", "which", "--space", "ENG").stdout)
        self.atl("accounts", "edit", "client", "--rename", "pod")
        self.assertIn("pod", self.atl("accounts", "which", "DB-1").stdout)
        self.atl("accounts", "remove", "pod")
        self.assertEqual(list(json.loads(self.cfg.read_text())["accounts"]), ["work"])

    def test_legacy_default_is_ignored(self):
        self.add_both()
        cfg = json.loads(self.cfg.read_text())
        cfg["default"] = "work"
        self.cfg.write_text(json.dumps(cfg))
        r = self.atl("api", "GET", "/rest/api/2/myself", ok=False)
        self.assertIn("no account named", r.stderr)
        self.atl("accounts", "edit", "work", "--email", "me@work.com")
        self.assertNotIn("default", json.loads(self.cfg.read_text()))

    # ---------------------------------------------------------------- no default account

    def test_commands_that_name_nothing_fail(self):
        self.add_both()
        r = self.atl("jira", "search", "assignee = currentUser()", ok=False)
        self.assertIn("--project", r.stderr)  # -p is required
        r = self.atl("jira", "projects", ok=False)
        self.assertIn("no account named; pass -a <alias>", r.stderr)
        r = self.atl("conf", "get", "42", ok=False)
        self.assertIn("give a page URL or --space KEY, or pass -a <alias>", r.stderr)
        r = self.atl("conf", "search", "--text", "x", ok=False)
        self.assertIn("--space", r.stderr)
        r = self.atl("api", "GET", "/rest/api/2/myself", ok=False)
        self.assertIn("no account named", r.stderr)

    def test_unknown_project_fails_instead_of_guessing(self):
        self.add_both()
        r = self.atl("jira", "get", "ZZZ-1", ok=False)
        self.assertIn("project ZZZ is not on any account", r.stderr)
        self.atl("jira", "get", "ZZZ-1", "-a", "work")  # -a vouches for a not-yet-synced project

    def test_project_on_two_accounts_needs_a(self):
        self.add_both()
        self.atl("accounts", "edit", "client", "--projects", "DB,WRK")
        r = self.atl("jira", "get", "WRK-1", ok=False)
        self.assertIn("exist on several accounts (client, work)", r.stderr)
        self.assertIn("[work]", self.atl("jira", "get", "WRK-1", "-a", "work").stdout)

    def test_account_flag_must_agree_with_project(self):
        self.add_both()
        r = self.atl("jira", "search", "-p", "WRK", "-a", "client", ok=False)
        self.assertIn("-a client does not match project WRK (on: work)", r.stderr)
        r = self.atl("jira", "search", "-p", "WRK,DB", ok=False)
        self.assertIn("project WRK and project DB are not on the same account", r.stderr)
        r = self.atl("jira", "get", f"{self.work.url}/browse/DB-1", ok=False)
        self.assertIn("are not on the same account", r.stderr)

    def test_token_env_and_token_cmd(self):
        env = {**self.env, "CLIENT_TOKEN": "client-token"}
        self.atl("accounts", "add", "client", "--site", self.client.url, "--email", "me@client.com",
                 "--token-env", "CLIENT_TOKEN", env=env)
        self.atl("accounts", "add", "work", "--site", self.work.url, "--email", "me@work.com",
                 "--token-cmd", "echo work-token")
        accounts = json.loads(self.cfg.read_text())["accounts"]
        self.assertNotIn("token", accounts["client"])
        self.assertNotIn("token", accounts["work"])
        self.assertEqual(accounts["work"]["token_cmd"], "echo work-token")
        self.assertIn("ok as Test User", self.atl("accounts", "test", "--all", env=env).stdout)
        r = self.atl("accounts", "test", "client", ok=False)  # env var missing
        self.assertIn("CLIENT_TOKEN", r.stderr)

    def test_test_reports_expired_token(self):
        self.add_both()
        self.atl("accounts", "edit", "work", "--token-stdin", stdin="expired\n")
        r = self.atl("accounts", "test", "work", ok=False)
        self.assertIn("HTTP 401", r.stdout)

    # ---------------------------------------------------------------- jira

    def test_search_routes_by_project_and_paginates(self):
        self.add_both()
        out = self.atl("jira", "search", "-p", "DB", "status = 'To Do'").stdout
        self.assertIn("# client: 3 issue(s)", out)
        req = self.client.last("POST", "/rest/api/2/search/jql")
        self.assertEqual(req["body"]["jql"], "project = DB AND (status = 'To Do')")
        self.assertEqual(req["auth"], self.client.auth)

    def test_multi_project_search_and_flag_after_subcommand(self):
        self.add_both()
        self.atl("jira", "search", "-p", "wrk,OPS", "--account", "work", "assignee = currentUser()")
        self.assertEqual(self.work.last("POST", "/rest/api/2/search/jql")["body"]["jql"],
                         "project in (WRK, OPS) AND (assignee = currentUser())")
        self.atl("jira", "search", "-p", "DB")
        self.assertEqual(self.client.last("POST", "/rest/api/2/search/jql")["body"]["jql"],
                         "project = DB ORDER BY updated DESC")

    def test_get_issue_from_url(self):
        self.add_both()
        out = self.atl("jira", "get", f"{self.client.url}/browse/DB-7").stdout
        self.assertIn("# DB-7: Fix the thing", out)
        self.assertIn("looks good", out)
        self.assertIn("[client]", out)
        r = self.atl("jira", "get", "https://elsewhere.atlassian.net/browse/DB-7", ok=False)
        self.assertIn("no account configured for https://elsewhere.atlassian.net", r.stderr)

    def test_create_with_description_file_and_assignee(self):
        self.add_both()
        desc = Path(self.tmp.name) / "d.txt"
        desc.write_text("h2. Context\n* point")
        out = self.atl("jira", "create", "-p", "DB", "-t", "Bug", "-s", "Crash on login",
                       "-d", f"@{desc}", "--labels", "app,bug", "--assignee", "ann@x.com",
                       "--field", 'customfield_1={"value": "x"}').stdout
        self.assertIn("created DB-99", out)
        f = self.client.last("POST", "/rest/api/2/issue")["body"]["fields"]
        self.assertEqual(f["description"], "h2. Context\n* point")
        self.assertEqual(f["labels"], ["app", "bug"])
        self.assertEqual(f["assignee"], {"accountId": "bbbbbbbbbbbbbbbbbbbbbbbb"})
        self.assertEqual(f["customfield_1"], {"value": "x"})

    def test_dry_run_sends_nothing(self):
        self.add_both()
        before = self.client.count("POST", "/rest/api/2/issue")
        r = self.atl("--dry-run", "jira", "create", "-p", "DB", "-s", "x")
        self.assertIn("[dry-run:client] POST", r.stderr)
        self.assertEqual(self.client.count("POST", "/rest/api/2/issue"), before)

    def test_transition_by_target_status_with_comment(self):
        self.add_both()
        self.assertIn("Finish -> Done", self.atl("jira", "move", "WRK-1", "done", "--comment", "shipped").stdout)
        body = self.work.last("POST", "/rest/api/2/issue/WRK-1/transitions")["body"]
        self.assertEqual(body["transition"], {"id": "31"})
        self.assertEqual(body["update"]["comment"][0]["add"]["body"], "shipped")
        r = self.atl("jira", "move", "WRK-1", "Nope", ok=False)
        self.assertIn("31 Finish -> Done", r.stderr)

    def test_update_comment_assign(self):
        self.add_both()
        self.atl("jira", "update", "WRK-2", "--summary", "New", "--add-label", "x")
        body = self.work.last("PUT", "/rest/api/2/issue/WRK-2")["body"]
        self.assertEqual(body, {"fields": {"summary": "New"}, "update": {"labels": [{"add": "x"}]}})
        self.atl("jira", "comment", "WRK-2", "-", stdin="multi\nline")
        self.assertEqual(self.work.last("POST", "/rest/api/2/issue/WRK-2/comment")["body"], {"body": "multi\nline"})
        self.atl("jira", "assign", "WRK-2", "me")
        self.assertEqual(self.work.last("PUT", "/rest/api/2/issue/WRK-2/assignee")["body"],
                         {"accountId": "aaaaaaaaaaaaaaaaaaaaaaaa"})

    # ---------------------------------------------------------------- confluence

    def test_conf_search_routes_by_space(self):
        self.add_both()
        out = self.atl("conf", "search", "--text", "deploy", "--space", "DOCS", "--type", "page").stdout
        self.assertIn("# client:", out)
        self.assertIn("42", out)
        self.assertNotIn("@@@", out)
        cql = self.client.last("GET", "/wiki/rest/api/search")["query"]["cql"][0]
        self.assertEqual(cql, 'text ~ "deploy" AND space = DOCS AND type = page')

    def test_conf_get_text(self):
        self.add_both()
        out = self.atl("conf", "get", "42", "--text", "-a", "work").stdout
        self.assertIn("# Runbook", out)
        self.assertIn("# Deploy", out)
        self.assertIn("- a", out)
        self.assertNotIn("<p>", out)

    def test_conf_create_wiki_in_space(self):
        self.add_both()
        out = self.atl("conf", "create", "--space", "ENG", "--title", "Notes", "--body", "h1. Hi").stdout
        self.assertIn("created page 555", out)
        body = self.work.last("POST", "/wiki/api/v2/pages")["body"]
        self.assertEqual(body["spaceId"], "100")
        self.assertEqual(body["body"], {"representation": "wiki", "value": "h1. Hi"})

    def test_conf_update_bumps_version_and_guards(self):
        self.add_both()
        out = self.atl("conf", "update", f"{self.work.url}/wiki/spaces/ENG/pages/42/Runbook",
                       "--body", "<p>new</p>", "--message", "edit").stdout
        self.assertIn("version 4", out)
        body = self.work.last("PUT", "/wiki/api/v2/pages/42")["body"]
        self.assertEqual(body["version"], {"number": 4, "message": "edit"})
        self.assertEqual(body["title"], "Runbook")
        r = self.atl("conf", "update", "42", "-a", "work", "--title", "X", "--expect-version", "2", ok=False)
        self.assertIn("version 3", r.stderr)
        self.atl("conf", "update", "42", "-a", "work", "--title", "Renamed")  # title only keeps the body
        body = self.work.last("PUT", "/wiki/api/v2/pages/42")["body"]
        self.assertEqual(body["body"]["representation"], "storage")
        self.assertIn("<h1>Deploy</h1>", body["body"]["value"])

    def test_conf_comment_and_raw_api(self):
        self.add_both()
        self.atl("conf", "comment", "-a", "work", "42", "nice")
        self.assertEqual(self.work.last("POST", "/wiki/api/v2/footer-comments")["body"]["pageId"], "42")
        out = self.atl("-a", "client", "api", "GET", "/rest/api/2/myself").stdout
        self.assertEqual(json.loads(out)["displayName"], "Test User")

    def test_404_hint_names_account(self):
        self.add_both()
        r = self.atl("-a", "work", "api", "GET", "/rest/api/2/nope", ok=False)
        self.assertIn("HTTP 404 [work]", r.stderr)
        self.assertIn("another account", r.stderr)


if __name__ == "__main__":
    unittest.main()
