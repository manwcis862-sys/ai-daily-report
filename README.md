# AI 行业日报 - GitHub Actions 版

自动搜索 AI 行业动态，每天发送早报和晚报到邮箱。

## 功能

- 🕘 每天 09:00 发送昨日 AI 早报
- 🕖 每天 19:00 发送今日 AI 晚报
- 📧 邮件自动发送到指定邮箱
- 🔍 多路搜索：SearXNG + DuckDuckGo
- 🏷️ 自动分类：OpenAI / Google / 国内大模型 / 开源生态 / 行业动态
- 🧪 支持手动触发测试

## 部署步骤

### 1. Fork 或创建仓库

将本项目推送到你的 GitHub 仓库。

### 2. 配置 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

| Secret 名称 | 值 | 说明 |
|-------------|-----|------|
| `SMTP_EMAIL` | `victory3690@qq.com` | 发件邮箱 |
| `SMTP_PASS` | `你的QQ邮箱授权码` | SMTP授权码（不是QQ密码） |
| `TO_EMAIL` | `victory3690@qq.com` | 收件邮箱 |

### 3. 手动测试

Actions → AI Daily Report → Run workflow → 选择 morning 或 evening

### 4. 自动运行

GitHub Actions 会按 cron 时间表自动执行，无需手动操作。

## 自定义

- 修改 `report.py` 中的搜索关键词覆盖不同领域
- 修改 `.github/workflows/daily-report.yml` 调整发送时间
- 报告内容会自动根据搜索结果分类整理

## 注意事项

- GitHub Actions cron 可能有几分钟延迟（正常现象）
- 免费账户每月 2000 分钟 Actions 额度，本项目每月约用 30 分钟
- 如果搜索结果为空，会发送提示邮件
