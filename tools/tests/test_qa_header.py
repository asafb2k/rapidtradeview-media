"""The access-policy header goes to our own hosts only. Run: python -m pytest tools/tests -q (no network, a dummy value)."""
import sys
import urllib.request
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import qa_header as qa  # noqa: E402

DUMMY = "dummy-not-a-real-value"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    f = tmp_path / "access-keys.env"
    f.write_text(f"RTV_SSR_KEY=other\nRTV_QA_MARKER_SECRET={DUMMY}\n", encoding="utf-8")
    monkeypatch.setattr(qa, "ENV_FILE", f)
    monkeypatch.setattr(qa, "_cache", {})
    return f


def test_header_only_for_our_hosts(env_file):
    for url in ("https://api.rapidtradeview.trade/snapshot/AAPL", "https://www.rapidtradeview.trade/dashboard/AAPL",
                "https://api-rs-prod-production.up.railway.app/health"):
        assert qa.headers_for(url) == {qa.HEADER: DUMMY}
    for url in ("https://asafb2k.github.io/rapidtradeview-media/v/x.mp4", "https://www.sec.gov/x",
                "http://www.rapidtradeview.trade/x", "https://www.rapidtradeview.trade.evil.test/x",
                "https://www.rapidtradeview.trade@evil.test/x"):
        assert qa.headers_for(url) == {}


def test_missing_file_or_key_sends_nothing_and_warns_once_without_the_value(tmp_path, monkeypatch, capsys):
    f = tmp_path / "access-keys.env"
    f.write_text("RTV_SSR_KEY=other\n", encoding="utf-8")
    monkeypatch.setattr(qa, "ENV_FILE", f)
    monkeypatch.setattr(qa, "_cache", {})
    assert qa.headers_for("https://api.rapidtradeview.trade/x") == {}
    assert qa.headers_for("https://api.rapidtradeview.trade/y") == {}
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and str(f) in err[0]
    monkeypatch.setattr(qa, "ENV_FILE", tmp_path / "nope.env")
    monkeypatch.setattr(qa, "_cache", {})
    assert qa.headers_for("https://api.rapidtradeview.trade/x") == {}


def test_header_dropped_when_a_redirect_leaves_our_hosts(env_file):
    req = qa.sign(urllib.request.Request("https://www.rapidtradeview.trade/a"))
    assert req.get_header(qa.HEADER.capitalize()) == DUMMY
    h = qa._OurHostsOnly()
    away = h.redirect_request(req, None, 302, "Found", {}, "https://favicon.example/x.png")
    assert not any(k.lower() == qa.HEADER.lower() for k in away.headers)
    home = h.redirect_request(req, None, 302, "Found", {}, "https://www.rapidtradeview.trade/b")
    assert home.get_header(qa.HEADER.capitalize()) == DUMMY


@pytest.mark.parametrize("other", [Path("D:/rtv-ops/tracks/growth/bin/qa_header.py"), Path("D:/rtvw/growth-video/scripts/qa_header.py")])
def test_the_copies_stay_identical(other):
    """qa_header.py lives in this repo (tools/), in growth-video (scripts/) and in tracks/growth/bin: one module, three places."""
    if not other.is_file():
        pytest.skip(f"{other} is not on this machine (or not merged yet)")
    assert other.read_bytes().replace(b"
", b"
") == (TOOLS / "qa_header.py").read_bytes().replace(b"
", b"
")   # git autocrlf may differ per checkout
