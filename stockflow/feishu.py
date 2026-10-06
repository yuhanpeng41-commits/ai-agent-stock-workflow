import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime
from urllib.parse import quote, urlsplit

import requests


class DeliveryError(RuntimeError):
    pass


class DeliveryUnknown(DeliveryError):
    """Server may have accepted the message: check the group before retrying."""


def validate_webhook(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "open.feishu.cn"
            or not re.fullmatch(r"/open-apis/bot/v2/hook/[A-Za-z0-9-]+", parts.path)
            or parts.query or parts.fragment):
        raise DeliveryError("FEISHU_WEBHOOK 必须是飞书自定义机器人的 HTTPS 地址")


def sign(timestamp, secret):
    key = f"{timestamp}\n{secret}".encode()
    return base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()


def escape_md(text):
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", str(text)).replace("\n", " ")


def card_for(report):
    tag = {"live": "", "replay": "【历史数据演示】", "demo": "【模拟数据】"}[report.mode]
    if report.mode == "live" and report.market_status == "closed":
        tag = "【最新交易日数据】"
    market_status = {"trading": "交易日", "closed": "休市", "historical": "历史回放",
                     "demo": "模拟数据", "unknown": "未记录（旧版报告）"}[report.market_status]
    quote_date = report.quote_date or (max(s.quote_at[:10] for s in report.stocks) if report.stocks else "暂无")
    title = tag + "A股 AI智能体 · 热度 Top10"
    elements = [{"tag": "markdown", "content": (
        "A股 AI Agent / 智能体概念热度日报\n"
        f"运行时间：{report.run_at or report.collected_at}\n行情数据日期：{quote_date}\n"
        f"休市/交易状态：{market_status}\n采集时间：{report.collected_at}\n新闻截止：{report.cutoff_at}\n"
        "权重：成交额40% / 涨跌30% / 主力净流入20% / 新闻10%\n"
        f"有效股票：{len(report.stocks)}；run_id：{report.run_id}"
    )}]
    if report.status == "no_current_quotes":
        title = tag + "A股 AI智能体 · 暂无当日行情"
        elements.append({"tag": "markdown", "content": "数据源未提供有效行情，本次未生成 Top10，请核对行情日期。"})
    for i, stock in enumerate(report.top10, 1):
        content = (
            f"**{i}. {escape_md(stock.name)} ({stock.code}) · {stock.score:.2f}分**\n"
            f"成交{stock.turnover / 1e8:.2f}亿｜涨跌{stock.change_pct:+.2f}%｜"
            f"主力净流入{stock.net_inflow / 1e8:+.2f}亿｜新闻{stock.news_mentions}篇\n"
            f"摘要：{escape_md(stock.summary)}\n"
        )
        if stock.news:
            story = stock.news[0]
            url = quote(story.url, safe=":/?=&%#.-_")
            news_label = "最近可用新闻" if stock.news_selection == "latest_available" else "当日关键新闻"
            content += f"[{news_label}]({url}) · {escape_md(story.source)} · {story.published_at[:16]}"
        else:
            content += "暂无可用相关新闻链接。" if report.market_status == "closed" else "当日暂无相关新闻链接。"
        elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": content}])
    if report.warnings:
        elements.append({"tag": "markdown", "content": "说明：" + escape_md("；".join(report.warnings))})
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "新闻为东方财富检索可见样本；热度反映关注度，不代表收益预测。"}]})
    return {"config": {"wide_screen_mode": True}, "header": {
        "template": "blue" if report.mode == "live" else "orange",
        "title": {"tag": "plain_text", "content": title}}, "elements": elements}


def send_card(webhook, secret, card):
    validate_webhook(webhook)
    payload = {"msg_type": "interactive", "card": card}
    if secret:
        timestamp = str(int(time.time()))
        payload.update(timestamp=timestamp, sign=sign(timestamp, secret))
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 28000:
        raise DeliveryError("飞书卡片过大，拒绝发送")
    try:
        # Do not retry this POST: a timeout can happen after a successful delivery.
        response = requests.post(webhook, json=payload, timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise DeliveryUnknown("推送连接异常，送达状态未知；先核对飞书群再重试") from None
    if response.status_code >= 500:
        raise DeliveryUnknown(f"飞书返回 HTTP {response.status_code}，送达状态未知")
    if response.status_code != 200:
        raise DeliveryError(f"飞书拒绝请求：HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise DeliveryUnknown("飞书回执无法解析，送达状态未知") from None
    code = data.get("code", data.get("StatusCode"))
    if code != 0:
        if code is None:
            raise DeliveryUnknown("飞书回执缺少业务状态码")
        raise DeliveryError(f"飞书业务校验失败，错误码 {code}；请检查签名、关键词或 IP 设置")
    return {"code": 0, "accepted_at": datetime.now().astimezone().isoformat()}
