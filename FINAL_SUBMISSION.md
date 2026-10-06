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

[daily.yml](.github/workflows/daily.yml) 包含 `cron: '0 3 * * *'`（每天 UTC 03:00 = 北京时间 11:00）、`workflow_dispatch`，Webhook 从 `${{ secrets.FEISHU_WEBHOOK }}` 读取。Secrets 已配置，云端部署与手动运行已验证。Actions 可能排队延迟，程序允许启动延迟最多 20 分钟。schedule 已配置；首次实际定时触发尚未记录，不将手动运行当作定时运行证据。

Node.js 20 deprecated 和 ubuntu-latest migration 在本次成功运行中均为非阻塞提示：平台已强制相关 Action 使用 Node.js 24；Ubuntu 提示为镜像迁移通知。本次保留已验证配置，无须立即改动。后续升级 Action 或镜像时单独复验，详见 [README 平台警告处理](README.md#平台警告处理)。

## 6. 真实飞书推送已验证

**GitHub Actions 云端 `live` 部署、`workflow_dispatch` 手动触发、真实飞书推送及休市回退均已验证成功。** 用户已确认飞书群收到新版消息：

| 验收项 | 结果 |
|---|---|
| 云端运行 | [37427321823](https://github.com/yuhanpeng41-commits/ai-agent-stock-workflow/actions/runs/37427321823)，`success` |
| 触发 / 模式 | `workflow_dispatch` / `live` |
| 运行时间 | 2026-10-06 15:03:45，北京时间 |
| 飞书接受时间 | 2026-10-06 15:06:38，北京时间 |
| 回执 | `status=sent`、`code=0` |
| run_id | `2c99136e1810` |
| 休市/交易状态 | 休市 |
| 行情数据日期 | 2026-09-30，按日历自动回退最近交易日 |
| 新闻截止 | 2026-10-06 15:04:02，北京时间；逐股优先运行当天，无则回退 |
| 成分股 / 榜单 | 183 只 / Top10 |
| 摘要最大长度 | 49 字符 |
| Top10 新闻 | 10 只均有选定新闻日的相关新闻链接 |
| 关键词 | 标题与正文包含“A股” |

原始云端报告、实际发送卡片、成功回执及 GitHub 元数据见 [evidence/cloud-run](evidence/cloud-run/)，已从本次 Actions 审计产物下载并验证一致。接收端已确认收到；截图文件尚需从飞书群补入。

## 7. 行情日期与证据说明

本次最终截图应使用新版云端真实推送，标题为 **“【最新交易日数据】A股 AI智能体 · 热度 Top10”**，清楚显示运行时间、行情数据日期和休市状态。10 月 6 日休市，最近交易日为 9 月 30 日，属于正常休市回退，不标为历史数据演示。

首次本地 `replay` 验收资料仍保留在 `evidence/verified-run/`，原来的历史演示标题未改写；最终主要证据是新版云端 `live`。程序未固定 9 月 30 日，开市后自动使用新交易日行情。

## 8. 提交范围

提交：`README.md`、`FINAL_SUBMISSION.md`、`workflow.md`、`docs/workflow.svg`、`stockflow/`、`tests/`、`scripts/`、`requirements.txt`、`.github/workflows/daily.yml`、`.gitignore`、空凭据模板 `.env.example`、`evidence/README.md`、`evidence/cloud-run/`、`evidence/verified-run/` 和实际截图。

不要提交：`.env` 及其他真实凭据、`.venv/`、`.state/`、`outputs/`、`__pycache__/`、临时依赖、缓存、日志。打包工具使用白名单并检查凭据，不将本地运行环境放入提交包。

## 9. 收尾状态

1. 核心业务、GitHub 云端部署、手动触发、真实飞书发送和休市回退验收已完成，本次未修改核心业务或工作流配置。
2. 实际截图尚未放入项目：飞书卡片上下部分、Actions 成功运行、schedule 配置；新闻打开截图可选。文件名见 [evidence/README](evidence/README.md)。补图后运行 `python scripts/pack_submission.py` 更新提交 ZIP。
3. 每天北京时间 11:00 的 schedule 已配置。首次实际自动运行记录可在后续补充，无须为本次手动云端验收重新部署。
