# 交付脚本参考

本文件只说明 `scripts/` 下可用的交付辅助脚本。是否生成 HTML/PDF、是否生成邮件正文、是否发送邮件，由外部调用方或用户明确需求决定；主分析流程不默认执行这些动作。

## 环境变量

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `X_DAILY_HOME` | `~/data/x-daily` | 数据根目录 |
| `X_DAILY_REPORTS_DIR` | `$X_DAILY_HOME/reports` | 报告输出目录 |
| `X_DAILY_CREDENTIALS` | `$X_DAILY_HOME/email-conf/credentials.env` | SMTP 配置 |
| `X_DAILY_RECIPIENTS` | `$X_DAILY_HOME/email-conf/recipients.txt` | 收件人列表 |
| `X_DAILY_EMAIL_FOOTER` | 空 | `email_body.py` 邮件落款 |
| `PLAYWRIGHT_MODULE_PATH` | 空，则用 `require('playwright')` | `render_pdf.js` 的 Playwright 包路径 |

## 脚本清单

| 脚本 | 阶段 | 作用 |
|------|------|------|
| `email_body.py` | report 后 | 生成邮件速览纯文本正文 |
| `txt_to_html.py` | report 后 | report TXT 转结构化 HTML |
| `render_pdf.js` | HTML 后 | HTML 转 PDF |
| `send_email.py` | 投递 | 发送邮件，目标用户通过 SMTP envelope 隐式 Bcc，附 TXT 与可选 PDF |

## `email_body.py`

**用途**：从 report TXT 为每个类别取第一个有效主题，拼出「今日各领域首要事实速览」及附件说明。

**调用**：

```bash
python3 "{SKILL_ROOT}/scripts/email_body.py" <REPORT_TXT> <YYYY-MM-DD> [-o OUTPUT] [--no-pdf] [--footer TEXT] [--pdf PATH]
```

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `REPORT_TXT` | 是 | - | 完整 report 路径，须符合 `references/report-output.md` |
| `YYYY-MM-DD` | 是 | - | 报告日期，通常用于附件文件名 |
| `-o` / `--output` | 否 | stdout | 输出文件路径 |
| `--no-pdf` | 否 | 自动检测 | footer 只列 TXT |
| `--footer` | 否 | `X_DAILY_EMAIL_FOOTER` | 邮件落款；两者皆空则无落款行 |
| `--pdf` | 否 | 同目录 `_full.pdf` | 用于判断是否附 PDF |

**跳过主题**：标题含「详见」；或 `事实` 以「详见」开头且含「不重复展开」；或 `事实` 为空。

## `txt_to_html.py`

**用途**：解析 report TXT 标记，生成分层 HTML，供 PDF 或本地浏览。

**调用**：

```bash
python3 "{SKILL_ROOT}/scripts/txt_to_html.py" <REPORT_TXT> <OUTPUT_HTML>
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `REPORT_TXT` | 是 | 输入 report 纯文本路径 |
| `OUTPUT_HTML` | 是 | 输出 HTML 路径，覆盖已存在文件 |

**输入要求**：含 `【类别】`、`【主题 NN】`、`事实：` / 视角对应判断段 / `推文链接：`、`今日总判断` 等。

**输出**：成功打印 `OK <path> <bytes> bytes`；失败抛异常退出。

## `render_pdf.js`

**用途**：用 Chromium/Playwright 将 HTML 打印为 A4 PDF。

**调用**：

```bash
node "{SKILL_ROOT}/scripts/render_pdf.js" <INPUT_HTML> <OUTPUT_PDF>
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `INPUT_HTML` | 是 | 输入 HTML 绝对或相对路径，须含 `<meta charset="utf-8">` |
| `OUTPUT_PDF` | 是 | 输出 PDF 路径 |

**环境**：优先 `PLAYWRIGHT_MODULE_PATH`，否则使用当前 Node 环境中的 `playwright`。

**输出**：成功 `OK <pdf路径>`；失败 `FAIL <message>`，exit 1；缺参 exit 2。

## `send_email.py`

**用途**：SMTP_SSL 发送邮件；正文为 `email_body` 文件；附件为 report TXT 与可选 PDF；`To` 为发件地址，目标用户只进入 SMTP envelope，不写入 `Bcc` 邮件头。

发送邮件是对外动作。只有在外部调用方或用户明确授权时才执行；不要输出 SMTP 密码、credentials 原文或完整异常堆栈。

**调用**：

```bash
python3 "{SKILL_ROOT}/scripts/send_email.py" [--date YYYY-MM-DD] [--report PATH] [--email-body PATH] [--pdf PATH] \
  [--reports-dir PATH] [--credentials PATH] [--recipients PATH]
```

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--date` | 否 | 从最新/报告名解析 | 在 reports 目录按日期找 `x_daily_analysis_<date>_*.txt` |
| `--report` | 否 | 见解析规则 | 完整 report TXT |
| `--email-body` | 否 | 与 report 同目录推导 | 邮件正文 TXT |
| `--pdf` | 否 | 与 report 同目录推导 | PDF 附件 |
| `--reports-dir` | 否 | `X_DAILY_REPORTS_DIR` | 报告目录 |
| `--credentials` | 否 | `X_DAILY_CREDENTIALS` | SMTP `credentials.env` |
| `--recipients` | 否 | `X_DAILY_RECIPIENTS` | 收件人列表文件 |

**路径解析**：若提供 `--report`，据此解析日期并推导 `_email_body.txt` / `_full.pdf`；若仅 `--date`，在 reports 目录按命名查找；若均未提供，取 reports 下最新的 `*_full.txt`。

**输出**：`EMAIL_OK <N>` 或 `EMAIL_FAILED <短原因>`；失败时会把邮件正文写入 reports 目录下 `email_failed_<date>.txt`。
