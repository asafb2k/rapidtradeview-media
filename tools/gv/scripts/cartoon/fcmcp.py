"""Minimal MCP stdio client for `filmcraft-cli mcp` (FilmCraft 0.20.1 headless engine session, no window).

Moved here from the .ops/filmcraft-trial build (2026-11-13) so that make_member_story.py can drive it. The binary lives in
<media>/.ops/cache/filmcraft/app/filmcraft-0.20.1-windows-x64-portable/ ($RTV_FILMCRAFT_CLI overrides the path).
Every call is a `command_run` (id + params); the full call log goes to `log` (JSONL) when given.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

TICKS = 254_016_000_000                           # FilmCraft time units per second


def _ops_cache() -> Path:
    env = os.environ.get("RTV_OPS_CACHE")
    if env:
        return Path(env)
    for p in Path(__file__).resolve().parents:
        if (p / ".ops" / "cache").is_dir():
            return p / ".ops" / "cache"
    raise SystemExit("no .ops/cache found above fcmcp.py (set RTV_OPS_CACHE)")


def cli_path() -> Path:
    env = os.environ.get("RTV_FILMCRAFT_CLI")
    if env:
        return Path(env)
    return _ops_cache() / "filmcraft" / "app" / "filmcraft-0.20.1-windows-x64-portable" / "filmcraft-cli.exe"


class FilmCraft:
    def __init__(self, *args: str, log: Path | None = None):
        exe = cli_path()
        if not exe.is_file():
            raise SystemExit(f"FilmCraft CLI not found: {exe}")
        self.p = subprocess.Popen([str(exe), "mcp", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.n = 0
        self.log = open(log, "w", encoding="utf-8") if log else None
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "rtv-member-story", "version": "1"}})
        self.server = init.get("serverInfo")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("filmcraft-cli mcp exited: " + self.p.stderr.read())
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    def tool(self, name: str, args: dict):
        res = self.rpc("tools/call", {"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if self.log:
            self.log.write(json.dumps({"tool": name, "args": args, "isError": res.get("isError", False),
                                       "result": text[:4000]}) + "\n")
            self.log.flush()
        if res.get("isError"):
            raise RuntimeError(f"{name} {json.dumps(args)[:400]} -> {text}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def run(self, cid: str, **params):
        return self.tool("command_run", {"id": cid, "params": params})

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:  # noqa: BLE001 - never leave the engine running
            self.p.kill()
            self.p.wait(timeout=10)
        if self.log:
            self.log.close()


def t(seconds: float) -> int:
    return round(seconds * TICKS)
