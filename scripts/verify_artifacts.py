"""Validate saved output against the interview acceptance criteria."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
args = parser.parse_args()
report = json.loads((args.directory / "report.json").read_text(encoding="utf-8"))
assert len({s["code"] for s in report["stocks"]}) == len(report["stocks"])
if report["status"] == "ranked":
    assert len(report["top10"]) == 10
    assert all(len(s["summary"]) < 50 for s in report["top10"])
    assert all(a["score"] >= b["score"] for a, b in zip(report["top10"], report["top10"][1:]))
    from datetime import datetime
    cutoff = datetime.fromisoformat(report["cutoff_at"])
    if report.get("market_status") in {"closed", "trading"}:
        assert report["mode"] == "live"
        assert report["quote_date"] and report["run_at"] and report["calendar_source"]
        if report["market_status"] == "trading":
            assert report["quote_date"] == cutoff.date().isoformat()
        else:
            assert report["quote_date"] < cutoff.date().isoformat()
    for s in report["stocks"]:
        recomputed = sum(s["factors"][k] * w for k, w in {"turnover": .4, "change_pct": .3, "net_inflow": .2, "news_mentions": .1}.items())
        assert abs(recomputed - s["score"]) < 1e-8
        if report.get("quote_date"):
            assert s["quote_at"][:10] == report["quote_date"]
        for n in s["news"]:
            stamp = datetime.fromisoformat(n["published_at"])
            assert stamp <= cutoff
            assert stamp.date().isoformat() == (s.get("news_date") or cutoff.date().isoformat())
            if report.get("market_status") != "closed" or s.get("news_selection") != "latest_available":
                assert stamp.date() == cutoff.date()
            assert n["url"].startswith(("https://", "http://"))
    print("PASS: Top10、四项评分、摘要<50字、新闻日期/链接均通过")
else:
    assert report["status"] == "no_current_quotes" and report["top10"] == []
    print("PASS: 旧行情未被当成当日榜单")
receipt_path = args.directory / "receipt.json"
if receipt_path.exists():
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["run_id"] == report["run_id"]
    assert receipt["status"] == "sent" and receipt["receipt"]["code"] == 0
    print("PASS: 真实发送成功回执，run_id一致；还需接收端截图作为界面证据")
else:
    print("发送回执：无（本次未完成真实发送）")
