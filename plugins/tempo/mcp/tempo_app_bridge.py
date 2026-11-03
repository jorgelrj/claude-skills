#!/usr/bin/env python3
"""Bridges Claude Code (stdio) to the TEMPO app's MCP server (HTTP).

With TEMPO_APP_TOKEN set and the app reachable, every message is passed to
${TEMPO_APP_URL:-http://127.0.0.1:4310}/mcp with the token. Without a token, or
when the app does not answer the handshake, the server starts with no tools, so
the plugin works as before and nothing shows as an error.
"""
import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("TEMPO_APP_TOKEN", "").strip()
URL = os.environ.get("TEMPO_APP_URL", "http://127.0.0.1:4310").rstrip("/") + "/mcp"
TIMEOUT = 60

online = bool(TOKEN)
why_off = "TEMPO_APP_TOKEN is not set." if not TOKEN else ""


def post(message):
    """Sends one message to the app; returns the parsed answer or None for 202."""
    req = urllib.request.Request(
        URL,
        data=json.dumps(message).encode(),
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        body = res.read()
        return json.loads(body) if body.strip() else None


def offline(message):
    """Answers locally: a server with no tools."""
    if "id" not in message or "method" not in message:
        return None
    method, mid = message["method"], message["id"]
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": asked,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tempo-app", "version": "off"},
                "instructions": f"The TEMPO app is not connected ({why_off}) Set TEMPO_APP_TOKEN (and TEMPO_APP_URL if needed) and restart Claude Code to use it.",
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": []}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"The TEMPO app is not connected: {why_off}"}}


def write(answer):
    if answer is None:
        return
    sys.stdout.write(json.dumps(answer) + "\n")
    sys.stdout.flush()


def main():
    global online, why_off
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not online:
            write(offline(message))
            continue
        try:
            write(post(message))
        except (urllib.error.URLError, OSError, ValueError) as err:
            reason = getattr(err, "reason", None) or err
            if isinstance(err, urllib.error.HTTPError) and err.code == 401:
                reason = "the app rejected TEMPO_APP_TOKEN"
            if isinstance(message, dict) and message.get("method") == "initialize":
                # No app at the handshake: stay quiet for this session.
                online, why_off = False, f"{URL} did not answer: {reason}."
                write(offline(message))
            elif isinstance(message, dict) and "id" in message:
                write({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": f"TEMPO app error: {reason}"}})


if __name__ == "__main__":
    main()
