# 生日提醒推送（企业微信群）

每天早上 **北京时间 09:00**，自动读取「农历/阳历提醒日历」里的顾客生日，
把当天该提醒的（当天 / 提前 1 / 3 / 7 天）汇总成 **一条消息**，发到指定企业微信群。

- 日历网页：https://lunar-reminder.app.workbuddy.host/
- 网页只负责录入/查看，本仓库只负责「定时 + 推送」，两边互不影响。

## 工作原理

```
GitHub Actions（每天 09:00 自动触发）
        ↓ 读
共享日历云端数据库（只读）
        ↓ 算
今天命中的提醒 → 汇总成一条消息
        ↓ 发
企业微信群机器人 Webhook → 指定群
        ↓ 记
写回「已发送记录」，避免同一天重复推
```

## 需要的两个仓库密钥（Secrets）

在仓库 **Settings → Secrets and variables → Actions → New repository secret** 里添加：

| 名称 | 说明 |
|---|---|
| `WEWORK_WEBHOOK_URL` | 企业微信群机器人地址，形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx` |
| `WB_ACCESS_KEY` | 共享日历云端读取密钥（可选，不填用脚本里的默认值） |

> 密钥只存在 GitHub 的加密 Secrets 里，不会出现在代码或日志中。

## 怎么拿到群机器人地址

企业微信里打开目标群 → 右上角「…」→ **群机器人** → **添加机器人** → 建好复制它的 **Webhook 地址**。

## 手动测试

仓库 → **Actions** → 左侧「生日提醒推送（企业微信群）」→ 右侧 **Run workflow**：

- 只想预览：`dry_run` 填 `true`（不会真发消息，只打印内容）
- 想测某一天：`date` 填 `2026-10-01`

## 本地运行

```bash
WEWORK_WEBHOOK_URL="你的webhook地址" python push_worker.py
```

参数：

- `--dry-run` 只打印不发送
- `--date 2026-10-01` 模拟指定日期
- `--webhook xxx` 直接指定 webhook（等价于环境变量）

## 安全说明

- 分享的日历链接不要外发到公开群，里面含顾客姓名/编号/生日。
- 想停掉推送：删掉这个仓库，或把 Actions 的 workflow 停用（Actions → 左侧工作流 → 右上「…」→ Disable workflow）。
