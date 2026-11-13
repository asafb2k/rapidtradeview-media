"""Minimal MCP stdio client for `filmcraft-cli mcp` (headless engine session, no window). Copied from the FilmCraft trial
(.ops/filmcraft-trial/fcmcp.py); FilmCraft 0.20.1 portable lives in <media>/.ops/cache/filmcraft (untracked)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

def _ops_cache() -> Path:
    """<media repo>/.ops/cache: $RTV_OPS_CACHE, else the first parent folder that has .ops/cache (a worktree finds the
    main checkout's)."""
    import os
    env = os.environ.get("RTV_OPS_CACHE")
    if env:
        return Path(env)
    for p in Path(__file__).resolve().parents:
        if (p / ".ops" / "cache" / "filmcraft").is_dir():
            return p / ".ops" / "cache"
    raise SystemExit("no .ops/cache/filmcraft found above fcmcp.py (set RTV_OPS_CACHE)")


FC = _ops_cache() / "filmcraft" / "app" / "filmcraft-0.20.1-windows-x64-portable" / "filmcraft-cli.exe"
TICKS = 254_016_000_000


class FilmCraft:
    def __init__(self, *args: str, log: Path | None = None):
        self.p = subprocess.Popen([str(FC), "mcp", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.n = 0
        self.log = open(log, "w", encoding="utf-8") if log else None
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "rtv-walkthrough", "version": "1"}})
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
        except Exception:
            self.p.kill()
        if self.log:
            self.log.close()


def t(seconds: float) -> int:
    return round(seconds * TICKS)
