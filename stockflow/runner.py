import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from .feishu import DeliveryError, DeliveryUnknown, card_for, send_card, validate_webhook
from .models import News, Report, SHANGHAI, Stock, now_shanghai
from .provider import Eastmoney, SourceError
from .render import save_report
from .scoring import rank

ROOT = Path(__file__).resolve().parents[1]


def load_saved_report(path, mode, now):
    """Resume a collected, reviewed snapshot, without substituting or inventing data."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("mode") != mode or data.get("status") not in {"ranked", "no_current_quotes"}:
        raise SourceError("快照模式或状态不匹配")
    cutoff = datetime.fromisoformat(data["cutoff_at"])
    if cutoff.tzinfo is None or cutoff > now + timedelta(minutes=5):
        raise SourceError("快照截止时间无效")
    if mode == "live" and (cutoff.date() != now.date() or (now - cutoff).total_seconds() > 15 * 60):
        raise SourceError("正式榜单快照已过期，需重新采集")
    report = Report(data["run_id"], mode, data["collected_at"], data["cutoff_at"],
                    data["boards"], data["status"], warnings=data.get("warnings", []), excluded=data.get("excluded", []),
                    run_at=data.get("run_at", data["collected_at"]), quote_date=data.get("quote_date", ""),
                    market_status=data.get("market_status", "unknown"), calendar_source=data.get("calendar_source", ""))
    if mode == "live":
        session = Eastmoney().trading_session(now)
        if report.market_status != session["market_status"] or report.quote_date != session["quote_date"]:
            raise SourceError("正式快照不符合当前交易日历，需重新采集")
    for item in data.get("stocks", []):
        fields = {k: v for k, v in item.items() if k not in {"news", "news_mentions"}}
        stock = Stock(**fields)
        stock.news = [News(**n) for n in item.get("news", [])]
        for news in stock.news:
            published = datetime.fromisoformat(news.published_at)
            selected_day = stock.news_date or cutoff.date().isoformat()
            if (published.tzinfo is None or published.date().isoformat() != selected_day or published > cutoff
                    or (report.market_status != "closed" and published.date() != cutoff.date())
                    or (selected_day != cutoff.date().isoformat() and stock.news_selection != "latest_available")):
                raise SourceError("快照新闻不符合日期/截止时间要求")
        if mode == "live" and datetime.fromisoformat(stock.quote_at).date().isoformat() != report.quote_date:
            raise SourceError("快照行情日期不符合交易日历")
        report.stocks.append(stock)
    if len({s.code for s in report.stocks}) != len(report.stocks):
        raise SourceError("快照含重复股票")
    if report.status == "ranked":
        expected = [(s["code"], float(s["score"])) for s in data["top10"]]
        report.top10 = rank(report.stocks)
        actual = [(s.code, s.score) for s in report.top10]
        if len(expected) != 10 or any(a[0] != b[0] or abs(a[1] - b[1]) > 1e-8 for a, b in zip(expected, actual)):
            raise SourceError("快照评分与重新计算结果不一致")
    elif data.get("top10"):
        raise SourceError("无当日行情快照不应包含榜单")
    print(f"已恢复真实采集快照并重新验证评分/摘要/新闻，run_id={report.run_id}", flush=True)
    return report


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def check_schedule(now, max_delay):
    target = now.replace(hour=11, minute=0, second=0, microsecond=0)
    if not 0 <= (now - target).total_seconds() <= max_delay * 60:
        raise SourceError(f"定时任务未在 11:00 至 11:{max_delay:02d} 窗口启动，停止生成榜单；Actions 不保证准点")


def demo_stocks(now):
    stocks = []
    for i in range(1, 17):
        stock = Stock(f"DEMO{i:02d}", f"演示股票{i:02d}", (17 - i) * 1.1e8,
                      ((i * 7) % 19 - 9) / 2, ((i * 11) % 21 - 10) * 1e7, now.isoformat())
        stock.news = [News(f"{stock.name}：这是用于验收流程的模拟新闻 {j + 1}",
                           f"https://example.com/demo/{i}/{j}", now.isoformat(), "模拟数据")
                      for j in range(i % 4)]
        stocks.append(stock)
    return stocks


def collect(mode, now, provider):
    report = Report(uuid.uuid4().hex[:12], mode, now.isoformat(), now.isoformat(), [], "ranked")
    report.run_at = now.isoformat()
    if mode == "demo":
        report.market_status, report.quote_date = "demo", now.date().isoformat()
        report.boards = [{"code": "DEMO", "name": "模拟板块"}]
        report.stocks = demo_stocks(now)
        report.warnings.append("所有股票、指标和新闻均为模拟数据，仅验证程序。")
    else:
        if mode == "live":
            session = provider.trading_session(now)
            report.market_status = session["market_status"]
            report.quote_date = session["quote_date"]
            report.calendar_source = session["calendar_source"]
        else:
            report.market_status = "historical"
        report.boards = provider.discover_boards(os.getenv("CONCEPT_NAME", ""))
        report.stocks, report.excluded = provider.constituents(report.boards)
        print(f"已获取 {len(report.stocks)} 只有效真实行情，排除 {len(report.excluded)} 条。", flush=True)
        if report.excluded:
            report.warnings.append(f"排除{len(report.excluded)}只零成交、停牌或行情不可用股票；排名基于有效成分股，排除代码及原因见报告。")
        # Cutoff is captured after quote retrieval, before all-stock news requests.
        cutoff = now_shanghai()
        report.collected_at = cutoff.isoformat()
        report.cutoff_at = cutoff.isoformat()
        timestamps = [datetime.fromisoformat(s.quote_at) for s in report.stocks]
        latest = max(timestamps)
        if latest > cutoff + timedelta(minutes=5):
            raise SourceError("行情时间晚于本次采集时间，请检查时钟或数据源")
        if mode == "live":
            if now.date() != cutoff.date():
                raise SourceError("采集跨越运行日期，需重新运行")
            if latest.date().isoformat() != report.quote_date:
                raise SourceError(f"日历要求行情日期为 {report.quote_date}，接口最新为 {latest.date()}，停止生成榜单")
            if report.market_status == "closed":
                report.warnings.append("休市：使用最新交易日数据；新闻优先运行当天，无当天相关新闻时使用最近可用新闻日。")
        if mode == "replay":
            cutoff = latest
            report.cutoff_at = cutoff.isoformat()
            report.quote_date = latest.date().isoformat()
            report.warnings.append("历史数据演示：使用接口最新行情，非当日11:00快照；成分股为当前列表。")
        target_date = report.quote_date
        fresh_required = (mode == "live" and report.market_status == "trading"
                          and ((9, 30) <= (cutoff.hour, cutoff.minute) <= (11, 30)
                               or (13, 0) <= (cutoff.hour, cutoff.minute) <= (15, 0)))
        valid = []
        for stock in report.stocks:
            stamp = datetime.fromisoformat(stock.quote_at)
            if stamp.date().isoformat() != target_date:
                report.excluded.append({"code": stock.code, "reason": "非目标日行情"})
            elif fresh_required and (cutoff - stamp).total_seconds() > 15 * 60:
                report.excluded.append({"code": stock.code, "reason": "行情超过15分钟未更新"})
            else:
                valid.append(stock)
        if len(valid) < len(report.stocks) * 0.9:
            raise SourceError("目标日/新鲜行情覆盖不足90%，停止生成榜单")
        report.stocks = provider.enrich_news(valid, cutoff, fallback_latest=report.market_status == "closed")
        capped = [s.code for s in report.stocks if s.news_capped]
        if capped:
            report.warnings.append(f"{len(capped)}只股票检索达到100篇上限，新闻提及为有限样本。")
        report.warnings.append("新闻提及按个股选定新闻日、截止前发布的去重文章计数；关键新闻优先标题直接提及公司。")
    report.top10 = rank(report.stocks)
    return report


def main(argv=None):
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="A股 AI智能体 Top10 → 飞书")
    parser.add_argument("--mode", choices=["live", "replay", "demo"], default="live")
    parser.add_argument("--send", action="store_true", help="真实发送到 .env 或 Secrets 指定的飞书群")
    parser.add_argument("--scheduled", action="store_true", help="检查北京时间11:00的触发窗口，仅供正式定时任务")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".state")
    parser.add_argument("--from-report", type=Path, help="恢复已采集的 report.json，重新验证后可发送，避免重复采集")
    args = parser.parse_args(argv)
    output = args.output / args.mode
    now = now_shanghai()
    state_file = args.state_dir / f"{now.date()}-{args.mode}.json"
    try:
        if args.scheduled and args.mode != "live":
            raise SourceError("定时任务只能使用 live 模式")
        if args.scheduled and args.from_report:
            raise SourceError("定时任务必须重新采集，不允许使用快照")
        webhook, secret = os.getenv("FEISHU_WEBHOOK", ""), os.getenv("FEISHU_SECRET", "")
        if args.send:
            validate_webhook(webhook)
            if state_file.exists():
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if state["status"] == "sent":
                    print(f"当日 {args.mode} 已成功推送，跳过。run_id={state['run_id']}")
                    return 0
                if state["status"] in {"pending", "unknown"}:
                    raise DeliveryUnknown("上次送达状态未知，需核对飞书群并处理状态文件后再发送")
        if args.scheduled:
            check_schedule(now, int(os.getenv("MAX_SCHEDULE_DELAY_MINUTES", "20")))
        provider = Eastmoney(int(os.getenv("HTTP_TIMEOUT", "15")), int(os.getenv("NEWS_WORKERS", "2")))
        report = load_saved_report(args.from_report, args.mode, now) if args.from_report else collect(args.mode, now, provider)
        save_report(report, output)
        (output / "error.json").unlink(missing_ok=True)
        print(f"mode={args.mode} status={report.status} stocks={len(report.stocks)} top10={len(report.top10)} run_id={report.run_id}")
        if not args.send:
            print(f"预览已保存：{output / 'preview.html'}；未发送消息。")
            return 0
        card = card_for(report)
        state = {"status": "pending", "mode": args.mode, "run_id": report.run_id,
                 "date": now.date().isoformat(), "report_status": report.status,
                 "payload_sha256": hashlib.sha256(json.dumps(card, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
        # Persist before POST. On process interruption the state stays pending.
        write_json(state_file, state)
        try:
            receipt = send_card(webhook, secret, card)
        except DeliveryUnknown:
            state["status"] = "unknown"
            write_json(state_file, state)
            raise
        except DeliveryError:
            state["status"] = "failed"
            write_json(state_file, state)
            raise
        state.update(status="sent", receipt=receipt)
        write_json(state_file, state)
        write_json(output / "receipt.json", state)
        print(f"飞书业务回执 code=0，真实发送成功。run_id={report.run_id}")
        return 0
    except (SourceError, DeliveryError, ValueError, OSError) as exc:
        # Exception messages are controlled above; never emit request traces with secrets.
        error = {"status": "failed", "mode": args.mode, "at": now.isoformat(), "error": str(exc)}
        write_json(output / "error.json", error)
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
