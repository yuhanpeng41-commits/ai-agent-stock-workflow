# A股 AI Agent / 智能体热度日报

使用 **Codex** 协作开发的 Python 自动化工作流：每天北京时间 11:00 触发，获取智能体概念成分股，按四项指标排序，生成 Top10、少于 50 字符摘要及新闻链接，同步推送飞书群。

## 本次验收结果

**GitHub Actions 云端 `live` 模式部署已验证**，`workflow_dispatch` 手动触发成功，飞书回执 `status=sent`、`code=0`；用户已确认群内收到新版真实消息。云端休市回退也已验证。最新代码的 42 项自动化测试已通过。

| 云端验收项 | 结果 |
|---|---|
| Actions 运行 | [37427321823](https://github.com/yuhanpeng41-commits/ai-agent-stock-workflow/actions/runs/37427321823)，`workflow_dispatch`，`success` |
| 模式 / 业务 run_id | `live` / `2c99136e1810` |
| 运行时间 | 2026-10-06 15:03:45，北京时间 |
| 交易状态 / 行情日期 | 休市 / 2026-09-30，交易日历动态决定 |
| 榜单 / 摘要 | 183 只股票，Top10，最长 49 字符 |
| 推送标题 | 【最新交易日数据】A股 AI智能体 · 热度 Top10 |
| 定时配置 | 每天 UTC 03:00 / 北京时间 11:00；首次实际 schedule 触发尚未记录 |

原始云端报告、实际发送卡片、回执和 GitHub 元数据见 [evidence/cloud-run](evidence/cloud-run/)。接收端已确认，截图文件尚需保存到项目。

以下为首次本地验收记录，保留原样供追溯：

| 项目 | 结果 |
|---|---|
| 概念板块 | 东方财富 AI智能体，BK0809 |
| 有效成分股 | 183 只 |
| 输出 | Top10，摘要最长 49 字符 |
| Top10 新闻 | 6 只有相关新闻，4 只明确标注暂无新闻 |
| 新闻样本 | 全部个股共 41 条关联记录，非独立文章总数 |
| 数据/新闻截止 | 2026-09-30 16:12:01，北京时间 |
| 飞书接受时间 | 2026-10-05 22:08:04，北京时间 |
| 关键词校验 | 标题和正文包含“A股”，飞书已接受 |

**保留的首次验收使用 9 月 30 日真实行情，以历史数据演示模式发送。** 原消息标题为“【历史数据演示】A股 AI智能体 · 热度 Top10”，不代表执行日 11:00 快照。该证据保留原样；最新正式规则见下方，正常休市回退不再标为历史演示。

首次本地验收原始记录见 [evidence/verified-run](evidence/verified-run/)；最终提交以新版云端 `live` 验收为主要证据，正常休市回退不属于历史演示。

## 交易日与休市规则

每天北京时间 11:00 运行，不因休市取消。程序每次查询 [深交所公开交易日历](https://www.szse.cn/marketServices/tradingcalendar/index.html)，按月动态获取交易标记并校验完整性；不硬编码某个交易日，也不把行情延迟当作休市。

- **交易日**：成交额、涨跌幅、主力净流入使用当天行情；新闻使用运行当天截至采集时间的相关新闻。交易时段行情超过 15 分钟未更新会排除，覆盖不足则停止；收盘后手动运行可使用当天收盘行情。
- **休市**：三项行情指标使用日历确定的最近交易日；新闻逐股优先运行当天，若没有，则使用该股最近可用新闻日的相关去重文章。关键新闻标明实际发布日期，新闻提及数按该股选定新闻日计算。不同股票可能采用不同新闻日期。
- 每条推送明确显示 **运行时间、行情数据日期、休市/交易状态**。休市榜单标题使用 **“【最新交易日数据】A股 AI智能体 · 热度 Top10”**，开市后自动恢复当天行情。
- 日历不可用、月份覆盖不完整、行情日期不符合日历或接口失败时停止生成榜单，不以旧行情冒充当天数据。最近可用新闻仅限检索源可见的最新 100 篇样本，达到上限会披露。

真实接口检查：日历返回 2026-10-06 为休市、最近交易日为 2026-09-30；2026-10-08 为交易日、目标行情日为 2026-10-08。重新开市使用新行情的行为已通过日期可变的自动化测试验证。

2026-10-06 14:40 已实际运行新版 `live` 全流程：183 只股票、Top10、最大摘要 49 字符，休市回退与新闻日期校验通过，卡片标题为“最新交易日数据”；本次验证仅生成报告，没有再次发送。

## 文件与流程图

完整 Mermaid：[workflow.md](workflow.md)；独立图片：[workflow.svg](docs/workflow.svg)；简洁提交说明：[FINAL_SUBMISSION.md](FINAL_SUBMISSION.md)。

| 文件 | 用途 |
|---|---|
| `stockflow/provider.py` | 板块、成分股、行情、新闻采集和备用接口 |
| `stockflow/scoring.py` | 百分位评分、Top10、摘要 |
| `stockflow/feishu.py` | 飞书卡片、签名、发送与回执判断 |
| `stockflow/runner.py` | 流程编排、快照恢复、发送状态 |
| `stockflow/models.py`、`render.py` | 数据模型和报告输出 |
| `tests/` | 42 项自动化测试，含交易日历与休市回退 |
| `scripts/check_config.py` | 检查配置，不打印凭据 |
| `scripts/verify_artifacts.py` | 验证报告和真实发送回执 |
| `scripts/pack_submission.py` | 白名单打包及凭据检查 |
| `.github/workflows/daily.yml` | 每日定时、手动触发及审计产物 |
| `evidence/verified-run/` | 本次真实运行报告、卡片、回执 |
| `evidence/cloud-run/` | 新版云端 live 报告、卡片、回执和 GitHub 运行证据 |

## 本地安装与运行

需要 Python 3.11 或以上。本地验收环境为 Python 3.14；Actions 配置 Python 3.12。

```powershell
Set-Location 'D:\面试\ai-agent-stock-workflow'
$env:PYTHONIOENCODING='utf-8'

# 新电脑首次安装；已有 .venv 和 .env 时保留原配置
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

在本地 `.env` 中填写 `FEISHU_WEBHOOK`，机器人启用签名时再填 `FEISHU_SECRET`。当前电脑已配置完成，无需重新创建。`.env` 已忽略，模板保留空凭据；不要输出或上传真实 Webhook。

```powershell
# 正式采集，不发送
.\.venv\Scripts\python.exe -m stockflow.runner --mode live

# 正式采集并推送，交易日/休市自动判断
.\.venv\Scripts\python.exe -m stockflow.runner --mode live --send

# 接口最新交易日的真实数据演示，不发送
.\.venv\Scripts\python.exe -m stockflow.runner --mode replay

# 真实采集并推送；同一日期和模式已成功时自动跳过
.\.venv\Scripts\python.exe -m stockflow.runner --mode replay --send

# 从已完成采集的快照恢复，重新校验后发送
.\.venv\Scripts\python.exe -m stockflow.runner --mode replay --from-report evidence\verified-run\report.json --send

# 只验证已保留的证据，不会发送消息
.\.venv\Scripts\python.exe scripts\verify_artifacts.py evidence\verified-run
```

`demo` 模式为离线模拟，不能作为真实采集证明。运行时的报告和预览写入 `outputs/<mode>/`，本地发送状态保存在 `.state/`。

## 热度计算与新闻口径

对全部有效成分股的每项指标计算升序平均秩，再转换为百分位：

`P(x) = (平均秩(x) - 1) / (N - 1) × 100`

`热度分 = 0.4 × P(成交额) + 0.3 × P(涨跌幅) + 0.2 × P(主力净流入) + 0.1 × P(新闻提及数)`

同值使用平均秩；某项全部相等时贡献为零，权重不临时调整。净流出保留负数。总分相同按成交额降序、代码升序。

- 成交额：目标交易日截至实际采集时的成交金额，单位元。
- 涨跌幅：相对昨收的百分数，较大的涨跌幅得分更高。
- 资金：东方财富主力资金净流入金额，不等同于全市场净资金变化。
- 新闻：对全部成分股检索，标题或摘要须提及股票代码或名称，按链接和相同标题去重；任何模式都排除截止后新闻。正式休市日按上述规则回退，交易日只计运行当天；每股最多检索 100 篇，达到上限会披露。

新闻采集在选 Top10 之前完成。关键新闻优先选标题直接提及公司的文章，再按发布时间排序。摘要采用行情事实与新闻标题提取，硬性限制少于 50 字符；无新闻时明确说明，避免编造链接。本题要求 AI agent 参与开发，摘要不依赖额外大模型密钥。

## 数据源与异常处理

东方财富公开接口：

1. 概念及成分股列表 `/api/qt/clist/get`，完整分页并核对总数和重复。
2. 列表入口不可用时，使用 `datacenter-web.eastmoney.com` 的 `RPT_F10_CORETHEME_BOARDTYPE` 按板块名称获取成分股。
3. `/api/qt/ulist.np/get` 批量行情；必要时 `/api/qt/stock/get` 逐股备用。主力净流入批量字段 `f62` 与单股字段 `f137` 已用真实值交叉验证。
4. 东方财富新闻检索接口，使用时间排序、目标日期过滤、个股相关性过滤及去重；解析 JSONP 不使用 `eval`。

交易日历为深交所 `GET /api/report/exchange/onepersistenthour/monthList?month=YYYY-MM`，读取 `jyrq` 与 `jybz`。跨月或跨年休市会继续查询前月，直到找到最近交易日；月度日期缺失时拒绝猜测。

公共数据使用独立 `curl_cffi` 会话并校验 HTTPS 证书，不继承失效系统代理。行情无法获取时披露排除代码和原因；缺失超过 10% 则停止榜单，零成交股票单独排除。新闻接口失败或结构变化会停止评分，不把失败当作零条新闻。

## GitHub Actions 部署

1. 目标仓库：[yuhanpeng41-commits/ai-agent-stock-workflow](https://github.com/yuhanpeng41-commits/ai-agent-stock-workflow)，分支 `main`。仓库根目录直接包含 `stockflow/`、`requirements.txt` 和 `.github/`。
2. **Settings → Secrets and variables → Actions → New repository secret** 添加 `FEISHU_WEBHOOK`；启用签名时再添加 `FEISHU_SECRET`。本地 `.env` 不会自动同步到云端。
3. **Actions → AI Agent Stock Daily → Run workflow**：先选 `live`、`send=false` 验证云端交易日或正常休市采集，再选 `live`、`send=true` 做正式推送验收。只有明确需要历史回放时才选 `replay`。
4. 工作流配置 `cron: '0 3 * * *'`，每天 UTC 03:00，即北京时间 11:00；定时固定使用 `live` 并发送。`workflow_dispatch` 支持手动触发；Webhook 从 `${{ secrets.FEISHU_WEBHOOK }}` 读取。
5. GitHub Actions 可能排队延迟；程序允许北京时间 11:00–11:20 启动，超出窗口停止。报告显示实际采集时间，不能承诺严格准点；严格要求时需改用常驻服务器调度。
6. 每次 Actions 的 **Artifacts → audit-…** 保存审计产物 30 天，Job summary 展示报告。首次云端执行后应再确认一次定时触发。

本仓库 Secrets 已配置，云端手动运行及真实飞书推送验收已完成。上述步骤保留用于其他环境部署；无须为了本次收尾重复触发发送。schedule 已配置，实际定时首跑尚未记录，不将手动触发等同于定时触发验收。

并发组串行执行，每日发送状态用 Actions cache 恢复。成功状态防止重复发送，`pending/unknown` 阻止送达不明时自动重发，POST 不自动重试。缓存是尽力去重，缓存丢失或进程中断仍可能导致重复，不能承诺跨故障 exactly-once。

### 平台警告处理

本次云端作业成功，两项提示均为非阻塞平台提示，保留已经验证的 Action 版本和 `ubuntu-latest` 配置。

- Node.js 20 deprecated：本次运行注释明确表示相关 Action 的声明目标为 Node.js 20，但实际由平台强制使用 Node.js 24。此提示不属于 Python 业务错误；后续可单独升级 Action 版本并复验，当前不必为消除提示改动流程。参见 [GitHub 官方运行时迁移说明](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/)。
- ubuntu-latest migration：通知托管镜像将切换版本；当前运行成功。镜像迁移后检查 Python 安装、依赖和采集即可；如发生兼容问题再固定镜像版本并复验。参见 [官方 runner-images 迁移通知](https://github.com/actions/runner-images/issues/14748)。

## 真实推送截图

打开飞书群，找到新版云端消息 **“【最新交易日数据】A股 AI智能体 · 热度 Top10”**，正文 `run_id=2c99136e1810`。用 `Win + Shift + S` 截取真实群消息并保存：

1. `evidence/01-feishu-top.png`：群聊名、机器人、标题、运行时间、行情数据日期、休市状态、run_id 和榜单前几项。
2. `evidence/02-feishu-bottom.png`：剩余榜单和新闻链接。
3. `evidence/03-news-link.png`：点击新闻后的文章页面，可选验证图。
4. `evidence/04-github-actions.png`：上述云端运行页，显示 Success、手动触发、main 分支和运行时间。
5. `evidence/05-schedule.png`：工作流文件中的 `cron: '0 3 * * *'` 与北京时间注释、`workflow_dispatch`。

上述文件名已加入 Git 提交白名单。不要截机器人设置或 `.env`。本地 `preview.html` 不能代替真实推送截图。回执 `code=0` 证明飞书接受请求，接收端截图证明实际呈现；当前截图尚待补入。

## 测试、依赖和最终打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\verify_artifacts.py evidence\verified-run
.\.venv\Scripts\python.exe scripts\verify_artifacts.py evidence\cloud-run
.\.venv\Scripts\python.exe scripts\pack_submission.py
```

42 项测试覆盖评分、新闻日期与去重、摘要长度、成分股完整性、快照校验、签名和发送状态，以及跨月/跨年日历、交易日旧行情拒绝、休市新闻优先和回退、重新开市自动切换及调度延迟。

`requirements.txt` 仅包含 `requests`、`curl_cffi`、`python-dotenv`、`tzdata`，当前环境的依赖完整性检查已通过，无需额外分析包。

打包生成 `submission/ai-agent-stock-workflow-submission.zip` 和 `SUBMISSION_MANIFEST.json`。工具按白名单收集代码、测试、文档及证据，并检查没有本地真实凭据。补入截图后重新打包。

**不要提交** `.env`、其他真实凭据、`.venv/`、`.state/`、`outputs/`、缓存、临时依赖和日志。`.env.example` 保持空凭据。清理后仍保留原始成功输出和本地发送状态供复查，它们不进入提交包。

**业务开发、云端部署和手动真实推送验收已完成**。提交材料尚需补入实际截图并重新打包；首次自动定时触发尚未记录，待后续 schedule 运行后可补充，无需修改核心业务代码。
