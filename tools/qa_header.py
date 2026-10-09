"""Access-policy header for Growth's own tools (Infra access policy, 2026-10-09).

api.rapidtradeview.trade, api-rs-prod-production.up.railway.app and www.rapidtradeview.trade answer 403 to
non-browser clients except verified crawlers. Our own scripts send  X-RTV-Automated-QA: <RTV_QA_MARKER_SECRET>.
The value is read at runtime from D:/rtv-ops/secrets/access-keys.env (KEY=VALUE lines), sent only to OUR_HOSTS
(never github.io, sec.gov, a favicon host, ...), dropped again if a redirect leaves our hosts, and never printed,
logged, written to evidence or put in an error message. A missing file or key keeps the old behaviour (no header)
and prints one warning line that names the file.

    import qa_header as qa
    with qa.urlopen(urllib.request.Request(url, headers={...}), timeout=30) as r: ...   # drop-in for urllib
    requests.get(url, headers={**qa.headers_for(url), ...})                              # or any other client

The same file lives in rapidtradeview-media/tools, growth-video/scripts and D:/rtv-ops/tracks/growth/bin: keep the
three identical (tools/tests/test_qa_header.py guards it in the media repo).
"""
from __future__ import annotations

import os
import re
import socket
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HEADER = 'X-RTV-Automated-QA'
KEY = 'RTV_QA_MARKER_SECRET'
ENV_FILE = Path(os.environ.get('RTV_ACCESS_KEYS_FILE') or 'D:/rtv-ops/secrets/access-keys.env')
OUR_HOSTS = frozenset({
    'api.rapidtradeview.trade',
    'www.rapidtradeview.trade',
    'rapidtradeview.trade',
    'api-rs-prod-production.up.railway.app',
})

_cache: dict[str, str | None] = {}


def _read_secret() -> str | None:
    try:
        text = ENV_FILE.read_text(encoding='utf-8-sig')
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        if k.strip() == KEY:
            v = v.strip().strip('"\'')
            return v if re.fullmatch(r'[\x21-\x7e]+', v) else None   # a header value: printable ASCII, no spaces
    return None


def secret() -> str | None:
    """The marker value, read once per process; None (and one warning line, never the value) when it is not usable."""
    if 'v' not in _cache:
        _cache['v'] = _read_secret()
        if _cache['v'] is None:
            print(f'warning: {ENV_FILE} is missing or has no usable {KEY}; requests to our hosts go out without {HEADER}',
                  file=sys.stderr, flush=True)
    return _cache['v']


def is_ours(url: str) -> bool:
    """True for an https URL on one of our hosts (userinfo tricks like https://api.rapidtradeview.trade@evil.test are not)."""
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and (p.hostname or '').lower() in OUR_HOSTS
    except ValueError:
        return False


def headers_for(url: str) -> dict[str, str]:
    """{HEADER: value} for a URL on our hosts when the secret is available, else {}."""
    if not is_ours(url):
        return {}
    v = secret()
    return {HEADER: v} if v else {}


def sign(req: urllib.request.Request) -> urllib.request.Request:
    """Add the header to a urllib Request for one of our hosts (no-op for any other host or without the secret)."""
    for k, v in headers_for(req.full_url).items():
        req.add_header(k, v)
    return req


class _OurHostsOnly(urllib.request.HTTPRedirectHandler):
    """urllib copies a request's headers onto the redirected request, third-party hosts included: drop ours there."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            for k in [k for k in new.headers if k.lower() == HEADER.lower()]:
                del new.headers[k]
            sign(new)
        return new


_opener = urllib.request.build_opener(_OurHostsOnly())


def urlopen(req, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
    """urllib.request.urlopen that signs requests to our hosts and keeps the header on our hosts only."""
    if isinstance(req, str):
        req = urllib.request.Request(req)
    return _opener.open(sign(req), timeout=timeout)
