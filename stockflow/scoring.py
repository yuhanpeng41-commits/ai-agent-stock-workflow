import math
from .models import Stock

WEIGHTS = {"turnover": 0.4, "change_pct": 0.3, "net_inflow": 0.2, "news_mentions": 0.1}


def percentile(values: list[float]) -> list[float]:
    """Average tied ranks, normalized to 0..100; a constant factor contributes 0."""
    if not values or any(not math.isfinite(x) for x in values):
        raise ValueError("评分数据为空或包含非有限数值")
    if len(set(values)) == 1:
        return [0.0] * len(values)
    ordered = sorted(values)
    ranks = {}
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j] == ordered[i]:
            j += 1
        ranks[ordered[i]] = ((i + j - 1) / 2) / (len(values) - 1) * 100
        i = j
    return [ranks[x] for x in values]


def summarize(stock: Stock) -> str:
    # Deterministic extraction: no unsupported causal statements or model credential needed.
    prefix = f"涨跌{stock.change_pct:+.2f}%，主力净流入{stock.net_inflow / 1e8:+.2f}亿。"
    detail = "暂无可用相关新闻。" if stock.news_selection == "running_day" else "当日暂无相关新闻。"
    if stock.news:
        detail = ("最近新闻：" if stock.news_selection == "latest_available" else "新闻：") + stock.news[0].title
    text = prefix + detail
    return text if len(text) < 50 else text[:48] + "…"


def rank(stocks: list[Stock]) -> list[Stock]:
    if len(stocks) < 10:
        raise ValueError("有效成分股不足 10 只，无法生成 Top10")
    for key, weight in WEIGHTS.items():
        scores = percentile([float(getattr(s, key)) for s in stocks])
        for stock, value in zip(stocks, scores):
            stock.factors[key] = value
    for stock in stocks:
        stock.score = sum(stock.factors[k] * w for k, w in WEIGHTS.items())
        stock.summary = summarize(stock)
    return sorted(stocks, key=lambda s: (-s.score, -s.turnover, s.code))[:10]
