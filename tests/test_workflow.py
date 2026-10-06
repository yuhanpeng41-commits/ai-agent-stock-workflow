import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from stockflow import runner
from stockflow.feishu import DeliveryError, DeliveryUnknown, card_for, send_card, sign, validate_webhook
from stockflow.models import SHANGHAI, Stock
from stockflow.provider import Eastmoney, SourceError, a_share, board_matches, normalize_news, parse_jsonp
from stockflow.scoring import percentile, rank, summarize

NOW = datetime(2026, 9, 30, 11, 0, tzinfo=SHANGHAI)
WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/test-placeholder"


def stock(i=1):
    return Stock(f"{i:06d}", "测试公司", i * 1e8, i / 10, (i - 8) * 1e6, NOW.isoformat())


class ScoringTests(unittest.TestCase):
    def test_percentiles_ties_and_constant(self):
        self.assertEqual(percentile([1, 2, 2, 4]), [0, 50, 50, 100])
        self.assertEqual(percentile([0, 0, 0]), [0, 0, 0])

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            percentile([1, float("nan")])

    def test_negative_inflow_keeps_order(self):
        self.assertEqual(percentile([-100, -10, 0]), [0, 50, 100])

    def test_known_weighted_result(self):
        stocks = [stock(i) for i in range(1, 11)]
        top = rank(stocks)
        self.assertEqual(top[0].code, "000010")
        self.assertAlmostEqual(top[0].score, 90)  # No news: unchanged fixed weights.
        self.assertAlmostEqual(top[-1].score, 0)

    def test_news_can_change_final_top10(self):
        # Identical market data: the stock with news must rank first, so news is
        # calculated over all constituents, before selecting the final ten.
        stocks = [stock(i) for i in range(1, 12)]
        for s in stocks:
            s.turnover, s.change_pct, s.net_inflow = 100, 0, 0
        from stockflow.models import News
        stocks[-1].news = [News("测试公司新闻", "https://example.com/1", NOW.isoformat())]
        self.assertEqual(rank(stocks)[0].code, "000011")

    def test_summaries_strictly_less_than_50(self):
        stocks = runner.demo_stocks(NOW)
        for s in stocks:
            s.name = "股" * 80
            if s.news:
                s.news[0].title = "新" * 1000
            self.assertLess(len(summarize(s)), 50)

    def test_top10_requires_ten_valid_rows(self):
        with self.assertRaises(ValueError):
            rank([stock(1)])


class NewsTests(unittest.TestCase):
    def test_missing_quotes_are_disclosed_and_excessive_missing_stops_run(self):
        source = Eastmoney()
        source._fallback_members = []
        rows = {f"{i:06d}": {"f12": f"{i:06d}", "f14": "测试公司", "f6": 100,
                 "f3": 1, "f62": -20, "f124": int(NOW.timestamp())} for i in range(1, 21)}
        rows["000001"] = {"f12": "000001", "fetch_error": "单股行情接口无法获取"}
        with patch.object(source, "_quotes_for_members", return_value=rows):
            stocks, excluded = source.constituents([])
        self.assertEqual(len(stocks), 19)
        self.assertEqual(excluded, [{"code": "000001", "reason": "单股行情接口无法获取"}])
        for code in ["000002", "000003"]:
            rows[code] = {"f12": code, "fetch_error": "单股行情接口无法获取"}
        with patch.object(source, "_quotes_for_members", return_value=rows):
            with self.assertRaises(SourceError):
                source.constituents([])

    def test_single_quote_uses_money_field_not_flag_field(self):
        source = Eastmoney()
        reply = {"data": {"f57": "600131", "f58": "国网信通", "f48": 401873347.0,
                          "f170": 10.01, "f86": 1790755903, "f137": 70274280.0, "f62": 2}}
        with patch.object(source, "_get", return_value=reply):
            quote = source._single_quote("1.600131")
        self.assertEqual(quote["f62"], 70274280.0)
        self.assertEqual(quote["f124"], 1790755903)
        with patch.object(source, "_get", return_value=reply):
            with self.assertRaises(SourceError):
                source._single_quote("0.000032")

    def test_data_center_fallback_discovers_exact_concept(self):
        source = Eastmoney()
        reply = {"success": True, "result": {"count": 1, "pages": 1, "data": [{
            "SECUCODE": "000032.SZ", "SECURITY_CODE": "000032", "SECURITY_NAME_ABBR": "深桑达A",
            "BOARD_NAME": "AI智能体", "NEW_BOARD_CODE": "BK0809"}]}}
        with patch.object(source, "_clist", side_effect=SourceError("unavailable")), \
                patch.object(source, "_get", return_value=reply):
            boards = source.discover_boards()
        self.assertEqual([(b["name"], b["code"]) for b in boards], [("AI智能体", "BK0809")])
        self.assertEqual(len(source._fallback_members), 1)

    def test_data_center_wrong_concept_is_rejected(self):
        source = Eastmoney()
        reply = {"success": True, "result": {"count": 1, "pages": 1, "data": [{
            "SECURITY_CODE": "000032", "BOARD_NAME": "人工智能", "NEW_BOARD_CODE": "BK0000"}]}}
        with patch.object(source, "_get", return_value=reply):
            with self.assertRaises(SourceError):
                source._datacenter_members(["AI智能体"])

    def test_batch_quotes_must_cover_all_members(self):
        source = Eastmoney()
        source._fallback_members = [{"SECURITY_CODE": "000032", "SECUCODE": "000032.SZ", "NEW_BOARD_CODE": "BK0809"},
                                   {"SECURITY_CODE": "600131", "SECUCODE": "600131.SH", "NEW_BOARD_CODE": "BK0809"}]
        with patch.object(source, "_get", return_value={"data": {"diff": [{"f12": "000032"}]}}):
            with self.assertRaises(SourceError):
                source._quotes_for_members([{"code": "BK0809", "name": "AI智能体"}])

    def article(self, code, date, title="测试公司发布公告"):
        return {"code": code, "date": date, "title": title, "content": "测试公司内容", "mediaName": "媒体"}

    def test_today_cutoff_dedup_and_relevance(self):
        rows = [self.article("202609301111111", "2026-09-30 10:00:00"),
                self.article("202609301111111", "2026-09-30 10:00:00"),
                self.article("202609302222222", "2026-09-29 10:00:00", "旧闻"),
                self.article("202609303333333", "2026-09-30 12:00:00", "未来新闻"),
                {"code": "202609304444444", "date": "2026-09-30 09:00:00", "title": "其他公司", "content": "无关"}]
        result = normalize_news(rows, stock(), NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].url, "https://finance.eastmoney.com/a/202609301111111.html")

    def test_html_removed(self):
        rows = [self.article("202609301111111", "2026-09-30 10:00:00", "<em>测试公司</em>&amp;合作")]
        self.assertEqual(normalize_news(rows, stock(), NOW)[0].title, "测试公司&合作")

    def test_bad_date_and_url_fail(self):
        with self.assertRaises(SourceError):
            normalize_news([self.article("202609301111111", "bad")], stock(), NOW)
        row = self.article("202609301111111", "2026-09-30 10:00:00")
        row["url"] = "javascript:alert(1)"
        with self.assertRaises(SourceError):
            normalize_news([row], stock(), NOW)

    def test_jsonp_safe_parse(self):
        self.assertEqual(parse_jsonp('callback({"result":{}});'), {"result": {}})
        with self.assertRaises(SourceError):
            parse_jsonp("")

    def test_board_scope(self):
        self.assertTrue(board_matches("AI智能体"))
        self.assertTrue(board_matches("AI Agent"))
        self.assertFalse(board_matches("人工智能"))
        self.assertFalse(board_matches("机器人概念"))
        self.assertTrue(a_share("920799"))
        self.assertFalse(a_share("00700"))
        self.assertFalse(a_share("510300"))

    def test_actual_page_size_and_pagination_integrity(self):
        source = Eastmoney()
        values = [{"data": {"total": 3, "diff": [{"f12": "1"}, {"f12": "2"}]}},
                  {"data": {"total": 3, "diff": [{"f12": "3"}]}}]
        with patch.object(source, "_get", side_effect=values):
            self.assertEqual(len(source._clist("test", "f12")), 3)
        values[1]["data"]["diff"] = [{"f12": "1"}]
        with patch.object(source, "_get", side_effect=values):
            with self.assertRaises(SourceError):
                source._clist("test", "f12")

    def test_news_schema_failure_is_not_zero(self):
        source = Eastmoney()
        with patch.object(source, "_get", return_value={"result": {}}):
            with self.assertRaises(SourceError):
                source.news_for(stock(), NOW)


class DeliveryTests(unittest.TestCase):
    def test_saved_snapshot_recomputes_score_and_rejects_tampering(self):
        from stockflow.render import save_report
        report = runner.collect("demo", NOW, Mock())
        with tempfile.TemporaryDirectory() as tmp:
            save_report(report, tmp)
            path = Path(tmp) / "report.json"
            loaded = runner.load_saved_report(path, "demo", NOW)
            self.assertEqual(loaded.run_id, report.run_id)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["top10"][0]["score"] += 10
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(SourceError):
                runner.load_saved_report(path, "demo", NOW)

    def test_saved_snapshot_rejects_future_news_and_expired_live(self):
        from stockflow.render import save_report
        report = runner.collect("demo", NOW, Mock())
        with tempfile.TemporaryDirectory() as tmp:
            save_report(report, tmp)
            path = Path(tmp) / "report.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["stocks"][0]["news"][0]["published_at"] = (NOW + timedelta(hours=1)).isoformat()
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(SourceError):
                runner.load_saved_report(path, "demo", NOW)
            data["mode"] = "live"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(SourceError):
                runner.load_saved_report(path, "live", NOW + timedelta(minutes=30))

    def test_a_share_keyword_is_in_card_body_for_all_modes(self):
        for mode in ["live", "replay", "demo"]:
            report = runner.collect("demo", NOW, Mock())
            report.mode = mode
            card = card_for(report)
            self.assertIn("A股", card["elements"][0]["content"])
            self.assertIn("A股", card["header"]["title"]["content"])
            report.status = "no_current_quotes"
            report.top10 = []
            self.assertIn("A股", card_for(report)["elements"][0]["content"])

    def test_signature_known_vector(self):
        # Fixed vector computed independently using Node crypto during validation.
        self.assertEqual(sign("1700000000", "test-secret"), "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84=")

    def test_webhook_rejects_other_hosts_and_query(self):
        for url in ["http://open.feishu.cn/open-apis/bot/v2/hook/x", "https://evil.example/x", WEBHOOK + "?secret=x"]:
            with self.assertRaises(DeliveryError):
                validate_webhook(url)

    def test_business_failure_rejected_even_http_200(self):
        response = Mock(status_code=200)
        response.json.return_value = {"code": 19021}
        with patch("stockflow.feishu.requests.post", return_value=response) as post:
            with self.assertRaises(DeliveryError):
                send_card(WEBHOOK, "", {})
            self.assertEqual(post.call_count, 1)

    def test_timeout_not_retried(self):
        with patch("stockflow.feishu.requests.post", side_effect=requests.Timeout) as post:
            with self.assertRaises(DeliveryUnknown):
                send_card(WEBHOOK, "", {})
            self.assertEqual(post.call_count, 1)

    def test_daily_dedup_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"FEISHU_WEBHOOK": WEBHOOK}), \
                patch("stockflow.runner.send_card", return_value={"code": 0}) as send:
            args = ["--mode", "demo", "--send", "--output", str(Path(tmp) / "out"), "--state-dir", str(Path(tmp) / "state")]
            self.assertEqual(runner.main(args), 0)
            self.assertEqual(runner.main(args), 0)
            self.assertEqual(send.call_count, 1)
            receipt = json.loads((Path(tmp) / "out/demo/receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "sent")

    def test_unknown_state_blocks_next_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"FEISHU_WEBHOOK": WEBHOOK}), \
                patch("stockflow.runner.send_card", side_effect=DeliveryUnknown("送达状态未知")) as send:
            args = ["--mode", "demo", "--send", "--output", str(Path(tmp) / "out"), "--state-dir", str(Path(tmp) / "state")]
            self.assertEqual(runner.main(args), 1)
            self.assertEqual(runner.main(args), 1)
            self.assertEqual(send.call_count, 1)

    def test_scheduled_delay_guard(self):
        runner.check_schedule(NOW + timedelta(minutes=10), 20)
        for at in [NOW - timedelta(minutes=1), NOW + timedelta(minutes=30)]:
            with self.assertRaises(SourceError):
                runner.check_schedule(at, 20)

    def test_live_never_ranks_stale_quotes_on_a_trading_day(self):
        provider = Mock()
        provider.discover_boards.return_value = [{"code": "BK-test", "name": "AI智能体"}]
        provider.constituents.return_value = ([stock(i) for i in range(1, 11)], [])
        provider.trading_session.return_value = {"market_status": "trading", "quote_date": "2026-10-01", "calendar_source": "test"}
        with patch("stockflow.runner.now_shanghai", return_value=NOW + timedelta(days=1)):
            with self.assertRaises(SourceError):
                runner.collect("live", NOW + timedelta(days=1), provider)
        provider.enrich_news.assert_not_called()


if __name__ == "__main__":
    unittest.main()
