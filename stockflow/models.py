from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class News:
    title: str
    url: str
    published_at: str
    source: str = "东方财富"
    snippet: str = ""


@dataclass
class Stock:
    code: str
    name: str
    turnover: float
    change_pct: float
    net_inflow: float
    quote_at: str
    news: list[News] = field(default_factory=list)
    news_capped: bool = False
    factors: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    summary: str = ""
    news_date: str = ""
    news_selection: str = "target_day"

    @property
    def news_mentions(self):
        return len(self.news)


@dataclass
class Report:
    run_id: str
    mode: str
    collected_at: str
    cutoff_at: str
    boards: list[dict]
    status: str
    stocks: list[Stock] = field(default_factory=list)
    top10: list[Stock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    run_at: str = ""
    quote_date: str = ""
    market_status: str = "unknown"
    calendar_source: str = ""

    def to_dict(self):
        result = asdict(self)
        for key in ("stocks", "top10"):
            for stock in result[key]:
                stock["news_mentions"] = len(stock["news"])
        return result


def now_shanghai():
    return datetime.now(SHANGHAI)
