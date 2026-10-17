import json

import pytest
from click.testing import CliRunner

from slack_tools import actions
from slack_tools.cli import main


def test_load_blocks_accepts_list_and_wrapper(tmp_path):
    blk = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
    a = tmp_path / "a.json"; a.write_text(json.dumps(blk))
    b = tmp_path / "b.json"; b.write_text(json.dumps({"blocks": blk}))
    assert actions.load_blocks(str(a)) == blk
    assert actions.load_blocks(str(b)) == blk


@pytest.mark.parametrize("bad", [[], {"blocks": []}, [{"text": "no type"}], "x", [{"type": "divider"}] * 51])
def test_load_blocks_rejects_bad_shapes(tmp_path, bad):
    p = tmp_path / "bad.json"; p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        actions.load_blocks(str(p))


def test_post_passes_blocks(monkeypatch, tmp_path):
    sent = {}

    class FakeClient:
        def chat_postMessage(self, **kw):
            sent.update(kw)
            return {"ok": True, "channel": kw["channel"], "ts": "1.2"}

    monkeypatch.setattr("slack_tools.client.get_bot_client", lambda: FakeClient())
    monkeypatch.setattr(actions, "resolve_channel", lambda c, ch: ch)
    p = tmp_path / "b.json"; p.write_text(json.dumps([{"type": "divider"}]))
    r = CliRunner().invoke(main, ["post", "D1", "fallback", "--blocks-file", str(p)])
    assert r.exit_code == 0, r.output
    assert sent == {"channel": "D1", "text": "fallback", "blocks": [{"type": "divider"}]}


def test_post_bad_blocks_fails_loudly(tmp_path):
    p = tmp_path / "b.json"; p.write_text("[]")
    r = CliRunner().invoke(main, ["post", "D1", "fallback", "--blocks-file", str(p)])
    assert r.exit_code != 0 and "non-empty" in r.output
