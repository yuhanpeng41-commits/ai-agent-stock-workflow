"""Public Eastmoney adapters. Field mappings checked against AKShare upstream.

GET requests retry; POST delivery deliberately does not. No stored browser cookies.
"""
import calendar
import html
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit

from curl_cffi import requests as curl_requests

from .models import News, SHANGHAI, Stock


class SourceError(RuntimeError):
    pass


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))).strip()


def parse_jsonp(text):
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.fullmatch(r"[\w.$]+\((.*)\);?", text, flags=re.DOTALL)
    if not match:
        raise SourceError("新闻接口返回空响应或非 JSONP 数据")
    return json.loads(match.group(1))


def board_matches(name):
    compact = re.sub(r"[\s_/-]+", "", name).lower()
    return compact in {"ai智能体", "智能体", "aiagent", "aiagents"}


def a_share(code):
    return bool(re.fullmatch(r"(?:00\d{4}|30\d{4}|60\d{4}|68\d{4}|[48]\d{5}|92\d{4})", code))


def normalize_news(rows, stock, cutoff, fallback_latest=False):
    """Select today's relevant stories, or the newest available relevant news day."""
    result = []
    seen = set()
    midnight = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    for row in rows:
        raw_date = str(row.get("date", ""))
        try:
            published = datetime.fromisoformat(raw_date)
            if published.tzinfo is None:
                published = published.replace(tzinfo=SHANGHAI)
            published = published.astimezone(SHANGHAI)
        except ValueError as exc:
            raise SourceError(f"{stock.code} 新闻时间字段无法解析") from exc
        if published > cutoff or (not fallback_latest and published < midnight):
            continue
        title = clean_text(row.get("title"))
        snippet = clean_text(row.get("content"))
        text = title + " " + snippet
        names = [stock.name, re.sub(r"^(?:\*?ST|N|C)", "", stock.name)]
        if stock.code not in text and not any(name and name in text for name in names):
            continue
        url = str(row.get("url") or "")
        if not url:
            article_code = str(row.get("code") or "")
            if not re.fullmatch(r"\d{10,}", article_code):
                raise SourceError(f"{stock.code} 新闻链接字段无效")
            url = f"https://finance.eastmoney.com/a/{article_code}.html"
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise SourceError(f"{stock.code} 新闻链接不是 HTTP(S) URL")
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        # Same URL or identical title on different URLs count only once.
        if url in seen or title in seen or not title:
            continue
        seen.update((url, title))
        result.append(News(title, url, published.isoformat(), clean_text(row.get("mediaName")), snippet))
    if fallback_latest and result:
        today = [n for n in result if datetime.fromisoformat(n.published_at).date() == cutoff.date()]
        latest_day = max(datetime.fromisoformat(n.published_at).date() for n in result)
        result = today or [n for n in result if datetime.fromisoformat(n.published_at).date() == latest_day]
    # Key story: company named in headline first, then newest. No inferred price attribution.
    result.sort(key=lambda n: (stock.name in n.title, n.published_at), reverse=True)
    return result


class Eastmoney:
    def __init__(self, timeout=15, workers=2):
        self.timeout = timeout
        self.workers = max(1, min(workers, 4))
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._fallback_members = None

    def _get(self, url, *, news=False):
        last = "unknown"
        for attempt in range(3):
            with self._lock:
                delay = 0.25 - (time.monotonic() - self._last_request)
                if delay > 0:
                    time.sleep(delay)
                self._last_request = time.monotonic()
            try:
                headers = {**self.headers, "Referer": "https://so.eastmoney.com/"} if news else self.headers
                if urlsplit(url).netloc == "www.szse.cn":
                    headers = {**self.headers, "Referer": "https://www.szse.cn/"}
                request_url = url
                if urlsplit(url).netloc == "push2.eastmoney.com":
                    node = ["push2.eastmoney.com", "29.push2.eastmoney.com", "17.push2.eastmoney.com"][attempt]
                    request_url = url.replace("https://push2.eastmoney.com/", f"https://{node}/", 1)
                # Domestic public sources work with direct browser-compatible TLS.
                # Scope this setting to our session; never alter system proxy settings.
                with curl_requests.Session(trust_env=False, impersonate="chrome") as session:
                    response = session.get(request_url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                value = parse_jsonp(response.text) if news else response.json()
                if not isinstance(value, dict):
                    raise SourceError("接口 JSON 结构异常")
                return value
            except Exception as exc:
                # Never log the full URL or request object (may contain future credentials).
                last = type(exc).__name__
                if attempt < 2:
                    time.sleep(0.6 * 2 ** attempt)
        path = urlsplit(url).path
        stage = {"/api/qt/clist/get": "行情列表", "/api/qt/ulist.np/get": "批量报价",
                 "/api/qt/stock/get": "单股报价", "/api/data/v1/get": "概念成分股", "/search/jsonp": "新闻",
                 "/api/report/exchange/onepersistenthour/monthList": "交易日历"}.get(path, "公开数据")
        raise SourceError(f"{stage}接口读取失败 ({last})")

    def trading_session(self, now):
        """Use the exchange's monthly calendar; never infer closure from stale quotes."""
        source = "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
        cursor = now.date()
        is_open = None
        for _ in range(3):
            month = cursor.strftime("%Y-%m")
            value = self._get(source + "?" + urlencode({"month": month}))
            rows = value.get("data")
            if not isinstance(rows, list):
                raise SourceError("交易日历结构异常")
            days = {}
            for row in rows:
                try:
                    day = date.fromisoformat(str(row["jyrq"]))
                    flag = str(row["jybz"])
                except (ValueError, KeyError, TypeError):
                    raise SourceError("交易日历日期字段无效") from None
                if day.strftime("%Y-%m") != month or day in days or flag not in {"0", "1"}:
                    raise SourceError("交易日历月份、重复日期或交易标记异常")
                days[day] = flag == "1"
            expected = calendar.monthrange(cursor.year, cursor.month)[1]
            if len(days) != expected:
                raise SourceError("交易日历日期覆盖不完整，拒绝猜测休市")
            if is_open is None:
                is_open = days[now.date()]
            eligible = [day for day, opened in days.items() if opened and day <= now.date()]
            if eligible:
                return {"market_status": "trading" if is_open else "closed",
                        "quote_date": max(eligible).isoformat(), "calendar_source": source}
            cursor = cursor.replace(day=1) - timedelta(days=1)
        raise SourceError("交易日历未找到最近交易日")

    def _clist(self, fs, fields):
        all_rows = []
        expected = None
        page = 1
        while page <= 100:
            params = {"pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                      "fid": "f12", "fs": fs, "fields": fields}
            # Retain colons/commas in the public endpoint URL; '+' encodes spaces in fs.
            url = "https://push2.eastmoney.com/api/qt/clist/get?" + urlencode(params, safe=":,!" )
            value = self._get(url)
            data = value.get("data")
            if value.get("rc", 0) != 0 or not isinstance(data, dict):
                raise SourceError("行情接口缺少 data，不能当成无股票")
            total = int(data.get("total", -1))
            if total < 1:
                raise SourceError("行情接口返回空成分股")
            if expected is None:
                expected = total
            elif total != expected:
                raise SourceError("分页期间成分股数量发生变化，请重跑")
            rows = data.get("diff") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            if not rows:
                raise SourceError("行情分页提前结束")
            all_rows.extend(rows)
            if len(all_rows) >= expected:
                break
            page += 1
        unique = {str(row["f12"]): row for row in all_rows}
        if expected != len(unique):
            raise SourceError(f"行情分页不完整: 预期 {expected}，实际 {len(unique)}")
        return list(unique.values())

    def discover_boards(self, exact_name=""):
        try:
            rows = self._clist("m:90 t:3 f:!50", "f12,f14")
        except SourceError:
            print("行情列表接口不可用，切换东方财富数据中心成分股接口。", flush=True)
            self._fallback_members = self._datacenter_members([exact_name] if exact_name else None)
            boards = {row["NEW_BOARD_CODE"]: {"code": row["NEW_BOARD_CODE"], "name": row["BOARD_NAME"],
                       "source": "东方财富数据中心 RPT_F10_CORETHEME_BOARDTYPE"}
                      for row in self._fallback_members}
            return list(boards.values())
        boards = [{"code": row["f12"], "name": row["f14"]} for row in rows
                  if (row["f14"] == exact_name if exact_name else board_matches(row["f14"]))]
        if not boards:
            raise SourceError("未发现 AI Agent/智能体板块，请核对 CONCEPT_NAME；不会替换为其他 AI 概念")
        return boards

    def _datacenter_members(self, names=None):
        names = names or ["AI智能体", "AI Agent", "AIAgent", "智能体"]
        if any(not re.fullmatch(r"[\w\s/-]{1,80}", name) for name in names):
            raise SourceError("概念名称含无效字符")
        rows = []
        expected_count, expected_pages = None, None
        page = 1
        while page <= 100:
            params = {"reportName": "RPT_F10_CORETHEME_BOARDTYPE",
                      "columns": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,BOARD_NAME,NEW_BOARD_CODE",
                      "pageSize": 200, "pageNumber": page, "sortColumns": "SECURITY_CODE", "sortTypes": 1,
                      "filter": '(BOARD_NAME in (' + ','.join('"' + name + '"' for name in names) + '))'}
            data = self._get("https://datacenter-web.eastmoney.com/api/data/v1/get?" + urlencode(params))
            result = data.get("result")
            if not data.get("success") or not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise SourceError("数据中心成分股接口返回异常")
            count, pages = int(result.get("count", -1)), int(result.get("pages", -1))
            if count < 1 or pages < 1:
                raise SourceError("数据中心未找到目标概念成分股")
            if expected_count is None:
                expected_count, expected_pages = count, pages
            elif (count, pages) != (expected_count, expected_pages):
                raise SourceError("数据中心分页期间成员数量变化，请重跑")
            block = result["data"]
            if not block:
                raise SourceError("数据中心成分股分页提前结束")
            for row in block:
                if (row.get("BOARD_NAME") not in names or not re.fullmatch(r"BK\d+", str(row.get("NEW_BOARD_CODE", "")))
                        or not re.fullmatch(r"\d{6}", str(row.get("SECURITY_CODE", "")))):
                    raise SourceError("数据中心成分股字段或概念范围异常")
            rows.extend(block)
            if page >= pages:
                break
            page += 1
        if len(rows) != expected_count or len({(r["SECURITY_CODE"], r["NEW_BOARD_CODE"]) for r in rows}) != expected_count:
            raise SourceError("数据中心成分股分页不完整或重复")
        print(f"数据中心获取 {len(rows)} 条真实成分股记录。", flush=True)
        return rows

    def _quotes_for_members(self, boards):
        if self._fallback_members is None:
            self._fallback_members = self._datacenter_members([board["name"] for board in boards])
        board_codes = {board["code"] for board in boards}
        members = {r["SECURITY_CODE"]: r for r in self._fallback_members
                   if r["NEW_BOARD_CODE"] in board_codes and a_share(r["SECURITY_CODE"])}
        secids = []
        for code, member in sorted(members.items()):
            suffix = str(member.get("SECUCODE", "")).rsplit(".", 1)[-1]
            if suffix not in {"SH", "SZ", "BJ"}:
                raise SourceError(f"{code} 的交易所字段无效")
            secids.append(("1." if suffix == "SH" else "0.") + code)
        quotes = {}
        def individual(secid):
            try:
                return self._single_quote(secid)
            except SourceError:
                code = secid.split('.')[1]
                # Preserve the membership record and explicitly exclude unavailable
                # quotes downstream. Never create prices or zero-valued money flows.
                return {"f12": code, "fetch_error": "单股行情接口无法获取"}
        for start in range(0, len(secids), 50):
            batch = secids[start:start + 50]
            params = {"secids": ','.join(batch), "fields": "f12,f13,f14,f3,f6,f62,f124", "fltt": 2, "invt": 2}
            try:
                value = self._get("https://push2.eastmoney.com/api/qt/ulist.np/get?" + urlencode(params, safe=":,."))
            except SourceError:
                print("批量报价接口波动，切换同源逐股行情接口（含真实主力净流入）。", flush=True)
                with ThreadPoolExecutor(max_workers=self.workers) as executor:
                    quotes = {}
                    for item in executor.map(individual, secids):
                        quotes[item["f12"]] = item
                        if len(quotes) % 30 == 0 or len(quotes) == len(secids):
                            print(f"逐股行情采集进度 {len(quotes)}/{len(secids)}", flush=True)
                break
            data = value.get("data")
            if value.get("rc", 0) != 0 or not isinstance(data, dict) or not isinstance(data.get("diff"), list):
                raise SourceError("批量报价接口返回异常")
            returned = {str(r.get("f12")): r for r in data["diff"]}
            if set(returned) != {secid.split('.')[1] for secid in batch}:
                raise SourceError("批量报价未完整返回目标股票")
            quotes.update(returned)
        if set(quotes) != set(members):
            raise SourceError("成分股与批量报价数量不一致")
        return quotes

    def _single_quote(self, secid):
        params = {"secid": secid, "fields": "f57,f58,f48,f170,f86,f137", "fltt": 2, "invt": 2}
        value = self._get("https://push2.eastmoney.com/api/qt/stock/get?" + urlencode(params, safe=":,."))
        data = value.get("data")
        if (value.get("rc", 0) != 0 or not isinstance(data, dict) or str(data.get("f57")) != secid.split('.')[1]
                or not all(k in data for k in ("f58", "f48", "f170", "f86", "f137"))):
            raise SourceError("单股行情字段缺失或股票代码不匹配")
        # stock/get's f137 is main-force net inflow; its f62 is NOT the clist
        # f62 money field. Checked against real 600131: both net fields=70274280.
        return {"f12": str(data["f57"]), "f14": data["f58"], "f6": data["f48"],
                "f3": data["f170"], "f124": data["f86"], "f62": data["f137"]}

    def constituents(self, boards):
        raw = {}
        if self._fallback_members is not None:
            raw = self._quotes_for_members(boards)
        else:
            try:
                for board in boards:
                    rows = self._clist(f"b:{board['code']} f:!50", "f12,f13,f14,f3,f6,f62,f124")
                    raw.update({str(r["f12"]): r for r in rows if a_share(str(r["f12"]))})
            except SourceError:
                print("成分股行情列表不可用，切换同源数据中心 + 批量报价接口。", flush=True)
                raw = self._quotes_for_members(boards)
        stocks, excluded = [], []
        for code, row in raw.items():
            if row.get("fetch_error"):
                excluded.append({"code": code, "reason": row["fetch_error"]})
                continue
            try:
                values = [float(row[key]) for key in ("f6", "f3", "f62")]
                if not all(math.isfinite(v) for v in values) or values[0] < 0:
                    raise ValueError("invalid numeric field")
                quote_at = datetime.fromtimestamp(int(row["f124"]), SHANGHAI)
                if values[0] == 0:
                    excluded.append({"code": code, "reason": "零成交/停牌"})
                    continue
                stocks.append(Stock(code, str(row["f14"]), *values, quote_at.isoformat()))
            except (ValueError, TypeError, KeyError, OverflowError):
                excluded.append({"code": code, "reason": "行情字段缺失或无效"})
        if not stocks or sum(x["reason"] != "零成交/停牌" for x in excluded) > len(raw) * 0.1:
            raise SourceError("有效行情覆盖不足，拒绝生成可能失真的榜单")
        return stocks, excluded

    def news_for(self, stock, cutoff, fallback_latest=False):
        rows, seen_ids = [], set()
        previous_oldest = None
        capped = False
        for page in range(1, 11):
            # Ten pages * ten articles: observed upstream page-size limit is respected.
            query = {"uid": "", "keyword": stock.code, "type": ["cmsArticleWebOld"],
                     "client": "web", "clientType": "web", "clientVersion": "curr",
                     "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                         "pageIndex": page, "pageSize": 10, "preTag": "<em>", "postTag": "</em>"}}}
            url = "https://search-api-web.eastmoney.com/search/jsonp?" + urlencode({
                "cb": "stocknews", "param": json.dumps(query, ensure_ascii=False), "_": int(time.time() * 1000)})
            value = self._get(url, news=True)
            result = value.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("cmsArticleWebOld"), list):
                raise SourceError(f"{stock.code} 新闻结构异常，不能按零提及计分")
            block = result["cmsArticleWebOld"]
            ids = {str(r.get("code") or r.get("url") or r.get("title")) for r in block}
            if block and ids <= seen_ids:
                raise SourceError(f"{stock.code} 新闻分页未前进")
            seen_ids.update(ids)
            rows.extend(block)
            dates = [str(r.get("date", "")) for r in block]
            # 'time' was verified against the real endpoint. Refuse an unexpected
            # relevance ordering instead of silently discarding newer stories.
            if dates != sorted(dates, reverse=True) or (dates and previous_oldest and dates[0] > previous_oldest):
                raise SourceError(f"{stock.code} 新闻接口未按时间倒序返回")
            previous_oldest = dates[-1] if dates else previous_oldest
            if len(block) < 10:
                break
            if dates:
                selected = normalize_news(rows, stock, cutoff, fallback_latest)
                selected_day = (datetime.fromisoformat(selected[0].published_at).date().isoformat()
                                if selected else None)
                boundary = selected_day if fallback_latest else cutoff.date().isoformat()
                if boundary and dates[-1][:10] < boundary:
                    break
            if page == 10:
                capped = True
        stock.news = normalize_news(rows, stock, cutoff, fallback_latest)
        stock.news_date = stock.news[0].published_at[:10] if stock.news else ""
        stock.news_selection = ("latest_available" if stock.news_date and stock.news_date != cutoff.date().isoformat()
                                else "running_day") if fallback_latest else "target_day"
        stock.news_capped = capped
        return stock

    def enrich_news(self, stocks, cutoff, fallback_latest=False):
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            result = []
            for enriched in executor.map(lambda stock: self.news_for(stock, cutoff, fallback_latest), stocks):
                result.append(enriched)
                if len(result) % 20 == 0 or len(result) == len(stocks):
                    print(f"新闻采集进度 {len(result)}/{len(stocks)}", flush=True)
            return result
