# 最终提交说明

## 1. 业务流程

每天北京时间 11:00 触发 → 查询交易日历 → 获取 A股 AI Agent / 智能体成分股及目标日行情 → 采集新闻 → 计算综合分 → 输出 Top10、少于 50 字符摘要和关键新闻链接 → 推送飞书。交易日使用当天行情；休市使用最近交易日行情，新闻优先运行当天，无当天相关新闻时逐股回退最近可用新闻日。详见 [流程图](workflow.md)。

## 2. 技术方案

使用 **Codex** 协作编写和调试；Python 实现采集、评分、摘要、飞书卡片和发送状态管理；GitHub Actions 调度。摘要使用事实提取，无额外大模型密钥。最新 42 项自动化测试通过，保留原始真实运行证据。

## 3. 热度计算公式

各指标先在全部有效成分股中转换为 0–100 百分位：

`P(x) = (升序平均秩(x) - 1) / (N - 1) × 100`

`热度分 = 40% × P(成交额) + 30% × P(涨跌幅) + 20% × P(主力净流入) + 10% × P(新闻提及数)`

同值使用平均秩；全相同指标贡献为零；总分并列按成交额降序、代码升序。新闻计数覆盖全部成分股，不能只对先选出的 Top10 检索。

## 4. 数据源

东方财富公开接口提供成分股、行情和新闻；原始验收 `AI智能体 / BK0809`，183 只有效成分股。资金为主力净流入。深交所公开月度交易日历提供开闭市标记，动态确定最新交易日。新闻过滤时间、相关性及重复；休市回退标注实际新闻日，无可用新闻时说明，采集失败不伪装为零条。

## 5. 部署方式

目标仓库：[ai-agent-stock-workflow](https://github.com/yuhanpeng41-commits/ai-agent-stock-workflow)，默认分支 `main`。在仓库 Actions Secrets 配置 `FEISHU_WEBHOOK`；启用签名时再配置 `FEISHU_SECRET`。

[daily.yml](.github/workflows/daily.yml) 包含 `cron: '0 3 * * *'`（UTC 03:00 = 北京时间 11:00）、`workflow_dispatch`，Webhook 从 `${{ secrets.FEISHU_WEBHOOK }}` 读取。Actions 可能排队延迟，程序允许启动延迟最多 20 分钟。配置已核对；Secrets、云端发送及定时运行仍需验收。

## 6. 真实飞书推送已验证

本地完整采集、Top10 生成和真实发送成功：

| 验收项 | 结果 |
|---|---|
| 飞书接受时间 | 2026-10-05 22:08:04，北京时间 |
| 回执 | `status=sent`、`code=0` |
| run_id | `b2fefc387537` |
| 成分股 / 榜单 | 183 只 / Top10 |
| 摘要最大长度 | 49 字符 |
| Top10 新闻 | 6 只有相关新闻，4 只明确标注暂无新闻 |
| 关键词 | 标题与正文包含“A股” |

原始报告、实际发送卡片和回执见 [evidence/verified-run](evidence/verified-run/)。接收端真实截图尚需从飞书群补入，回执不能替代截图。

## 7. 历史数据演示说明

**首次验收因数据源最新交易日为 2026 年 9 月 30 日，使用历史数据演示模式。** 执行日为 10 月 5 日，原始真实消息标题为“【历史数据演示】A股 AI智能体 · 热度 Top10”，该报告、卡片与回执保持原样。

最新正式规则把正常休市回退标为 **“最新交易日数据”**，不标为历史演示。推送显示运行时间、行情数据日期和休市/交易状态。9 月 30 日仅是首次证据的数据日期，程序没有固定该日期，开市后自动使用新交易日行情。手动 `replay` 仍用于明确的历史回放。

## 8. 提交范围

提交：`README.md`、`FINAL_SUBMISSION.md`、`workflow.md`、`docs/workflow.svg`、`stockflow/`、`tests/`、`scripts/`、`requirements.txt`、`.github/workflows/daily.yml`、`.gitignore`、空凭据模板 `.env.example`、`evidence/README.md`、`evidence/verified-run/` 和接收端截图。

不要提交：`.env` 及其他真实凭据、`.venv/`、`.state/`、`outputs/`、`__pycache__/`、临时依赖、缓存、日志。打包工具使用白名单并检查凭据，不将本地运行环境放入提交包。

## 9. 仍需完成

1. 飞书群截取实际机器人消息，保存为 `evidence/01-feishu-top.png`、`evidence/02-feishu-bottom.png`；新闻页面验证图可保存为 `evidence/03-news-link.png`。
2. 配置 GitHub Secrets，手动以 `live` 模式运行 Actions，检查云端日志、报告和接收端，再确认一次定时触发。
3. 补入截图后执行 `python scripts/pack_submission.py` 重新打包。详见 [README](README.md)。
