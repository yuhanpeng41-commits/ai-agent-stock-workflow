# 真实推送截图保存位置

最终主要证据为新版 GitHub Actions 云端 `live` 运行：真实飞书回执 `code=0`，`run_id=2c99136e1810`，用户已确认群内收到。

`cloud-run/` 保存 Actions 运行 [37427321823](https://github.com/yuhanpeng41-commits/ai-agent-stock-workflow/actions/runs/37427321823) 的原始报告、实际发送卡片、回执及 GitHub 元数据。运行时间为 2026-10-06 15:03:45，北京时间；休市，行情日期自动回退到 2026-09-30。手动触发成功，schedule 已配置但首次实际触发尚未记录。

`verified-run/` 保存原始成功报告、实际发送卡片和回执，已与原始文件逐个核对 SHA-256 一致，可随代码提交。数据日期为 2026-09-30，真实发送日期为 2026-10-05。

打开飞书群，找到新版 **“【最新交易日数据】A股 AI智能体 · 热度 Top10”**，`run_id=2c99136e1810`。不要把旧版历史演示消息作为新版休市回退的主要截图。

建议使用 Win + Shift + S 保存：

1. `01-feishu-top.png`：群聊名、机器人名称、卡片标题、运行时间、行情数据日期、休市状态、run_id 和排名前几项。
2. `02-feishu-bottom.png`：剩余排名和新闻链接。
3. `03-news-link.png`：点击其中一条新闻后打开的文章，可选验证图。
4. `04-github-actions.png`：该次 Actions 页面，显示 Success、手动触发、main 分支和运行时间。
5. `05-schedule.png`：工作流代码，显示 UTC 03:00 cron、北京时间 11:00 注释和手动触发配置。

这五个 PNG 文件名已允许 Git 跟踪并纳入打包白名单。补图后运行 `python scripts/pack_submission.py` 更新提交包。其他截图默认忽略，避免误提交设置截图。

这里尚未放入接收端截图，需要从你的飞书客户端截取。本地 preview.html 不是实际推送截图。不要截取机器人设置或 .env 文件。
