import calendar
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from stockflow import runner
from stockflow.feishu import card_for
from stockflow.models import SHANGHAI, Stock
from stockflow.provider import Eastmoney, SourceError, normalize_news
from stockflow.render import save_report


def month_rows(year, month, open_dates):
    return {"data": [{"jyrq": date(year, month, day).isoformat(),
                      "jybz": "1" if date(year, month, day) in open_dates else "0"}
                     for day in range(1, calendar.monthrange(year, month)[1] + 1)]}


class CalendarTests(unittest.TestCase):
    def test_closed_month_crosses_to_previous_month(self):
        source = Eastmoney()
        now = datetime(2030, 1, 2, 11, tzinfo=SHANGHAI)
        with patch.object(source, "_get", side_effect=[month_rows(2030, 1, set()),
                month_rows(2029, 12, {date(2029, 12, 31)})]) as get:
            session = source.trading_session(now)
        self.assertEqual(session["market_status"], "closed")
        self.assertEqual(session["quote_date"], "2029-12-31")
        self.assertIn("month=2029-12", get.call_args_list[1].args[0])

    def test_new_open_day_switches_automatically(self):
        source = Eastmoney()
        now = datetime(2030, 1, 8, 11, tzinfo=SHANGHAI)
        with patch.object(source, "_get", return_value=month_rows(2030, 1, {date(2030, 1, 8)})):
            session = source.trading_session(now)
        self.assertEqual(session["market_status"], "trading")
        self.assertEqual(session["quote_date"], "2030-01-08")

    def test_bad_or_incomplete_calendar_stops_run(self):
        source = Eastmoney()
        now = datetime(2030, 1, 8, 11, tzinfo=SHANGHAI)
        complete = month_rows(2030, 1, {date(2030, 1, 8)})
        duplicate = {"data": complete["data"] + [complete["data"][0]]}
        for value in ({}, {"data": []}, {"data": complete["data"][:-1]}, duplicate,
                      {"data": [{"jyrq": "bad", "jybz": "1"}]},
                      {"data": [{"jyrq": "2030-01-01", "jybz": "unknown"}]}):
            with self.subTest(value=value), patch.object(source, "_get", return_value=value):
                with self.assertRaises(SourceError):
                    source.trading_session(now)


class HolidayNewsTests(unittest.TestCase):
    NOW = datetime(2030, 1, 2, 11, tzinfo=SHANGHAI)

    def row(self, day, identifier, title="测试公司新闻", content="测试公司"):
        return {"date": day + " 10:00:00", "code": identifier,
                "title": title, "content": content}

    def stock(self):
        return Stock("000001", "测试公司", 100, 1, 20, self.NOW.isoformat())

    def test_running_day_beats_historical_headline_priority(self):
        rows = [self.row("2030-01-02", "20300102111111", "行业资讯"),
                self.row("2030-01-01", "20300101111111", "测试公司旧新闻")]
        result = normalize_news(rows, self.stock(), self.NOW, fallback_latest=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].published_at[:10], "2030-01-02")

    def test_latest_relevant_day_not_latest_unrelated_article(self):
        rows = [self.row("2030-01-02", "20300102111111", "其他公司", "无关"),
                self.row("2029-12-31", "20291231111111", "测试公司最新消息"),
                self.row("2029-12-31", "20291231222222", "测试公司新合作"),
                self.row("2029-12-30", "20291230111111", "测试公司更旧消息")]
        result = normalize_news(rows, self.stock(), self.NOW, fallback_latest=True)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(n.published_at[:10] == "2029-12-31" for n in result))
        self.assertEqual(normalize_news(rows, self.stock(), self.NOW), [])

    def test_future_news_never_used_and_empty_stays_empty(self):
        future = self.row("2030-01-03", "20300103111111")
        self.assertEqual(normalize_news([future], self.stock(), self.NOW, True), [])
        self.assertEqual(normalize_news([], self.stock(), self.NOW, True), [])

    def test_fallback_pagination_continues_until_relevant_day(self):
        source = Eastmoney()
        irrelevant = [self.row("2030-01-01", f"20300101{i:06d}", f"其他公司{i}", "无关") for i in range(10)]
        relevant = [self.row("2029-12-31", "20291231111111")]
        pages = [{"result": {"cmsArticleWebOld": rows}} for rows in (irrelevant, relevant)]
        with patch.object(source, "_get", side_effect=pages) as get:
            s = source.news_for(self.stock(), self.NOW, fallback_latest=True)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(s.news_date, "2029-12-31")
        self.assertEqual(s.news_selection, "latest_available")


class LiveSessionTests(unittest.TestCase):
    def provider(self, quote_time, run_time, closed):
        provider = Mock()
        provider.trading_session.return_value = {"market_status": "closed" if closed else "trading",
            "quote_date": quote_time.date().isoformat(), "calendar_source": "https://www.szse.cn/"}
        provider.discover_boards.return_value = [{"code": "BK-test", "name": "AI智能体"}]
        provider.constituents.return_value = ([Stock(f"{i:06d}", f"测试公司{i}", i * 100, i, -i,
            quote_time.isoformat()) for i in range(1, 12)], [])
        provider.enrich_news.side_effect = lambda stocks, cutoff, **kwargs: stocks
        return provider

    def test_holiday_ranks_old_quotes_and_uses_current_news_cutoff(self):
        run_time = datetime(2030, 1, 2, 11, tzinfo=SHANGHAI)
        quotes = datetime(2029, 12, 31, 15, tzinfo=SHANGHAI)
        provider = self.provider(quotes, run_time, True)
        with patch("stockflow.runner.now_shanghai", return_value=run_time):
            report = runner.collect("live", run_time, provider)
        self.assertEqual(len(report.top10), 10)
        self.assertEqual(report.quote_date, "2029-12-31")
        self.assertEqual(report.cutoff_at, run_time.isoformat())
        self.assertTrue(provider.enrich_news.call_args.kwargs["fallback_latest"])
        card = card_for(report)
        text = json.dumps(card, ensure_ascii=False)
        self.assertIn("最新交易日数据", text)
        self.assertNotIn("历史数据演示", text)
        for value in ("运行时间", "行情数据日期", "休市/交易状态：休市"):
            self.assertIn(value, text)

    def test_reopened_market_uses_new_quotes_and_strict_today_news(self):
        run_time = datetime(2030, 1, 8, 11, tzinfo=SHANGHAI)
        provider = self.provider(run_time, run_time, False)
        with patch("stockflow.runner.now_shanghai", return_value=run_time):
            report = runner.collect("live", run_time, provider)
        self.assertEqual(report.quote_date, "2030-01-08")
        self.assertFalse(provider.enrich_news.call_args.kwargs["fallback_latest"])
        self.assertIn("交易日", card_for(report)["elements"][0]["content"])

    def test_trading_session_stale_intraday_quotes_rejected(self):
        run_time = datetime(2030, 1, 8, 11, tzinfo=SHANGHAI)
        provider = self.provider(run_time - timedelta(hours=1), run_time, False)
        with patch("stockflow.runner.now_shanghai", return_value=run_time):
            with self.assertRaises(SourceError):
                runner.collect("live", run_time, provider)

    def test_after_close_accepts_same_day_closing_quotes(self):
        run_time = datetime(2030, 1, 8, 22, tzinfo=SHANGHAI)
        provider = self.provider(run_time.replace(hour=15), run_time, False)
        with patch("stockflow.runner.now_shanghai", return_value=run_time):
            report = runner.collect("live", run_time, provider)
        self.assertEqual(len(report.top10), 10)

    def test_closed_snapshot_roundtrip_and_date_tampering(self):
        from stockflow.models import News
        run_time = datetime(2030, 1, 2, 11, tzinfo=SHANGHAI)
        quote_time = datetime(2029, 12, 31, 15, tzinfo=SHANGHAI)
        provider = self.provider(quote_time, run_time, True)
        def enriched(stocks, cutoff, **kwargs):
            s = stocks[0]
            s.news = [News("测试公司1新闻", "https://example.com/1", quote_time.isoformat())]
            s.news_date, s.news_selection = "2029-12-31", "latest_available"
            return stocks
        provider.enrich_news.side_effect = enriched
        with patch("stockflow.runner.now_shanghai", return_value=run_time):
            report = runner.collect("live", run_time, provider)
        with tempfile.TemporaryDirectory() as tmp:
            save_report(report, tmp)
            path = Path(tmp)/"report.json"
            with patch.object(Eastmoney, "trading_session", return_value=provider.trading_session.return_value):
                loaded = runner.load_saved_report(path, "live", run_time)
                self.assertEqual(loaded.quote_date, "2029-12-31")
                data = json.loads(path.read_text(encoding="utf-8"))
                data["stocks"][0]["quote_at"] = run_time.isoformat()
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(SourceError):
                    runner.load_saved_report(path, "live", run_time)


if __name__ == "__main__":
    unittest.main()
