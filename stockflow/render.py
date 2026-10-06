import html
import json
from pathlib import Path

from .feishu import card_for


def save_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "feishu-card.json").write_text(json.dumps(card_for(report), ensure_ascii=False, indent=2), encoding="utf-8")
    status = {"trading": "交易日", "closed": "休市", "historical": "历史回放",
              "demo": "模拟数据", "unknown": "未记录（旧版报告）"}[report.market_status]
    quote_date = report.quote_date or (max(s.quote_at[:10] for s in report.stocks) if report.stocks else "暂无")
    lines = [f"# AI智能体 Top10 ({report.mode})", "", f"运行时间：{report.run_at or report.collected_at}",
             f"行情数据日期：{quote_date}", f"休市/交易状态：{status}", f"采集：{report.collected_at}",
             f"新闻截止：{report.cutoff_at}", f"run_id：{report.run_id}", ""]
    if not report.top10:
        lines.append("暂无当日有效行情；未生成榜单。")
    for i, stock in enumerate(report.top10, 1):
        lines += [f"## {i}. {stock.name} ({stock.code}) — {stock.score:.2f}分", "",
                  f"成交{stock.turnover / 1e8:.2f}亿 / 涨跌{stock.change_pct:+.2f}% / 主力净流入{stock.net_inflow / 1e8:+.2f}亿 / 新闻{stock.news_mentions}篇",
                  stock.summary, ""]
        if stock.news:
            lines += [f"[{stock.news[0].title}]({stock.news[0].url}) · {stock.news[0].published_at}", ""]
        else:
            lines += ["暂无可用相关新闻链接。" if report.market_status == "closed" else "当日暂无相关新闻链接。", ""]
    lines += ["说明：" + "；".join(report.warnings)]
    markdown = "\n".join(lines)
    (directory / "report.md").write_text(markdown, encoding="utf-8")
    # Local review page: explicitly labelled as a preview, never claimed as push evidence.
    blocks = []
    for i, stock in enumerate(report.top10, 1):
        story = stock.news[0] if stock.news else None
        label = '最近可用新闻' if stock.news_selection == 'latest_available' else '当日关键新闻'
        link = (f'<a href="{html.escape(story.url, quote=True)}" target="_blank" rel="noopener">{label} ↗</a> · {html.escape(story.published_at[:16])}'
                if story else ('暂无可用相关新闻' if report.market_status == 'closed' else '当日暂无相关新闻'))
        blocks.append(f'<article><div class="rank">{i:02}</div><div><h2>{html.escape(stock.name)} <small>{stock.code}</small></h2><p>成交 {stock.turnover / 1e8:.2f} 亿 · 涨跌 {stock.change_pct:+.2f}% · 主力净流入 {stock.net_inflow / 1e8:+.2f} 亿 · 新闻 {stock.news_mentions} 篇</p><p>{html.escape(stock.summary)}</p>{link}</div><b>{stock.score:.2f}<small>热度综合分</small></b></article>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI智能体热度日报预览</title>
<style>body{margin:0;background:#0c1425;color:#e9eef7;font:15px/1.7 "Microsoft YaHei",sans-serif}main{max-width:1000px;margin:50px auto;padding:24px}header{padding:32px;background:#15243e;border-radius:18px}h1{margin:12px 0;font-size:36px}.label{color:#8ab8ff;font-size:13px;letter-spacing:2px}p{color:#acb8cd;margin:6px 0}article{display:flex;gap:22px;align-items:center;padding:22px;background:#121f35;border:1px solid #233454;border-radius:14px;margin:12px 0}article>div:nth-child(2){flex:1}.rank{font-size:26px;color:#6a9be9}h2{margin:0;font-size:20px}small{font-size:12px;color:#9cabbe;font-weight:normal}b{font-size:26px;color:#6cddb6;text-align:right}b small{display:block}a{color:#87b6ff}footer{color:#99aac4;font-size:13px;padding:20px}.warn{color:#ffce80}@media(max-width:600px){main{margin:0;padding:14px}article{gap:10px;padding:14px}.rank{font-size:18px}h1{font-size:26px}h2{font-size:16px}}</style><main>
'''
    page += f'<header><div class="label">CODEX × DAILY WORKFLOW</div><h1>AI 智能体 · 热度 Top10</h1><p class="warn">本地预览 / {html.escape(report.mode)} 模式 · 此页面不是实际推送截图</p><p>运行时间 {html.escape(report.run_at or report.collected_at)}<br>行情数据日期 {html.escape(quote_date)}<br>休市/交易状态 {status}<br>采集 {html.escape(report.collected_at)}<br>新闻截止 {html.escape(report.cutoff_at)}<br>run_id {report.run_id}</p><p>成交额 40% · 涨跌幅 30% · 主力净流入 20% · 新闻提及 10%</p></header>'
    page += "".join(blocks) or '<article>暂无当日有效行情，本次未生成榜单。</article>'
    page += '<footer>' + html.escape("；".join(report.warnings)) + '</footer></main></html>'
    (directory / "preview.html").write_text(page, encoding="utf-8")
    return directory
