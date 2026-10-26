"""Manifest video DRAFTs (PROMPT v1, 2026-10-26: every manifest variant goes through the gate). Run: python -m pytest tools/tests -q."""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import grok_review as gr  # noqa: E402

DATE = "2026-10-26"
VID = f"video-{DATE}-earnings-today-{DATE}"
MEDIA = f"https://asafb2k.github.io/rapidtradeview-media/v/{DATE}/earnings-today-{DATE}/reel_9x16.mp4"
CAPTION = ("Verizon Communications ($VZ) reports before the open today, Mon Oct 26.\n\nWhich report are you watching?\n\n"
           "Link in bio.\n\nNot investment advice.\n\n#earnings #stocks")
X_TEXT = "$VZ reports before the open today, Mon Oct 26. Not investment advice."
MANIFEST = {"date": DATE, "posts": [{"id": VID, "platforms": {
    "instagram": {"media_url": MEDIA, "caption": CAPTION},
    "x": {"media_url": MEDIA, "text": X_TEXT},
    "threads": {"media_url": MEDIA, "text": X_TEXT}}}]}


def draft(**kw):
    d = {"item_id": VID, "platform": "instagram", "text": CAPTION, "reply_text": None, "media_url": MEDIA,
         "planned_at": "2026-10-26T12:30:00Z", "format": "reel"}
    d.update(kw)
    return d


def test_manifest_ids_match_video_ids_only():
    assert gr.MANIFEST_ID.match(VID).group("date") == DATE
    assert not gr.MANIFEST_ID.match("2026-10-26-insider-flow-ANET-ea4143")
    assert not gr.MANIFEST_ID.match("video-2026-10-26")


def test_verbatim_caption_and_media_approve_on_each_platform():
    assert gr.review_manifest(draft(), MANIFEST, DATE) == ("APPROVE", [])
    assert gr.review_manifest(draft(platform="x", text=X_TEXT), MANIFEST, DATE) == ("APPROVE", [])
    # trailing spaces / an extra trailing newline are not a change
    assert gr.review_manifest(draft(text=CAPTION.replace("\n\n#earnings", "  \n\n#earnings") + "\n"), MANIFEST, DATE)[0] == "APPROVE"


def test_edited_text_wrong_media_or_missing_variant_reject():
    v, r = gr.review_manifest(draft(text=CAPTION.replace("Which report", "What report")), MANIFEST, DATE)
    assert v == "REJECT" and "verbatim" in r[0]
    v, r = gr.review_manifest(draft(media_url=MEDIA.replace("reel_9x16", "story_9x16")), MANIFEST, DATE)
    assert v == "REJECT" and "media_url" in r[0]
    v, r = gr.review_manifest(draft(platform="pinterest"), MANIFEST, DATE)
    assert v == "REJECT" and "no pinterest variant" in r[0]
    v, r = gr.review_manifest(draft(item_id=f"video-{DATE}-picks-{DATE}"), MANIFEST, DATE)
    assert v == "REJECT" and "not a post" in r[0]
    v, r = gr.review_manifest(draft(), None, DATE)
    assert v == "REJECT" and "no manifest" in r[0]


def test_other_day_and_provider_names_reject():
    v, r = gr.review_manifest(draft(planned_at="2026-10-27T12:30:00Z"), MANIFEST, DATE)
    assert v == "REJECT" and "planned_at" in r[0]
    v, r = gr.review_manifest(draft(reply_text="Dates via Zacks"), MANIFEST, DATE)
    assert v == "REJECT" and r[0].startswith("provider:")
