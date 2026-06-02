#!/usr/bin/env python3
"""
Send X-daily report email: plain body + TXT attachment + optional PDF.

Recipient users are sent through the SMTP envelope only; no Bcc header is
written, so recipients are not exposed in the message headers.

成功：EMAIL_OK <N>
失败：EMAIL_FAILED <short_reason>，并将邮件正文写入 reports 目录下 email_failed_<date>.txt
"""
from __future__ import annotations

import argparse
import mimetypes
import re
import smtplib
import socket
import sys
import traceback
from email.message import EmailMessage
from pathlib import Path
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPServerDisconnected,
    SMTPException,
)

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from x_daily_paths import credentials_path, recipients_path, reports_dir


def short_reason(exc: BaseException) -> str:
    if isinstance(exc, SMTPAuthenticationError):
        return "认证失败"
    if isinstance(
        exc,
        (SMTPConnectError, SMTPServerDisconnected, socket.timeout, TimeoutError),
    ):
        return "连接超时"
    if isinstance(exc, FileNotFoundError):
        return "文件缺失"
    if isinstance(exc, KeyError):
        return "配置缺失"
    if isinstance(exc, SMTPException):
        return "SMTP失败"
    if isinstance(exc, RuntimeError) and "邮件正文过期" in str(exc):
        return "邮件正文过期"
    if isinstance(exc, RuntimeError) and "收件人" in str(exc):
        return "收件人为空"
    return "未知错误"


def write_failure_log(
    path: Path,
    *,
    reason: str,
    step: str,
    date_str: str,
    paths: dict[str, Path] | None = None,
    cred_path: Path | None = None,
    reci_path: Path | None = None,
    env: dict[str, str] | None = None,
    recipients: list[str] | None = None,
    missing_keys: list[str] | None = None,
    attach_pdf: bool | None = None,
    exc: BaseException | None = None,
) -> None:
    env = env or {}
    recipients = recipients or []
    missing_keys = missing_keys or []
    paths = paths or {}

    lines = [
        "status: EMAIL_FAILED",
        f"reason: {reason}",
        f"step: {step}",
        f"date: {date_str}",
        "",
        f"report: {paths.get('report', '')}",
        f"email_body: {paths.get('email_body', '')}",
        f"pdf: {paths.get('pdf', '')}",
        f"attach_pdf: {attach_pdf if attach_pdf is not None else ''}",
        "",
        f"smtp_server: {env.get('smtp_server', '')}",
        f"smtp_port: {env.get('smtp_port', '')}",
        f"email_from: {env.get('email_from', '')}",
        f"credentials_file: {cred_path or ''}",
        f"recipients_file: {reci_path or ''}",
        f"credentials_loaded: {bool(env)}",
        "missing_keys:",
    ]
    if missing_keys:
        lines.extend(f"- {key}" for key in missing_keys)
    else:
        lines.append("- none")

    lines.extend(
        [
            f"recipients_count: {len(recipients)}",
            "recipients:",
        ]
    )
    if recipients:
        lines.extend(f"- {recipient}" for recipient in recipients)
    else:
        lines.append("- none")

    lines.extend(["", "exception:"])
    if exc is not None:
        lines.extend(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def extract_date_from_name(path: Path) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not m:
        raise RuntimeError("无法解析报告日期")
    return m.group(1)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def load_recipients(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip() and not x.strip().startswith("#")]


def add_attachment(msg: EmailMessage, path: Path) -> None:
    ctype, encoding = mimetypes.guess_type(str(path))
    if ctype is None or encoding is not None:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    with open(path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )


def ensure_fresh_email_body(email_body_path: Path, report_path: Path) -> None:
    email_mtime = email_body_path.stat().st_mtime
    stale_sources = []
    if email_mtime < report_path.stat().st_mtime:
        stale_sources.append("report")

    generator_path = _SCRIPT_DIR / "email_body.py"
    if generator_path.exists() and email_mtime < generator_path.stat().st_mtime:
        stale_sources.append("email_body.py")

    if stale_sources:
        raise RuntimeError("邮件正文过期：" + ",".join(stale_sources))


def paths_for_date(reports: Path, date_str: str) -> dict[str, Path]:
    base = f"x_daily_analysis_{date_str}"
    return {
        "report": reports / f"{base}_full.txt",
        "email_body": reports / f"{base}_email_body.txt",
        "pdf": reports / f"{base}_full.pdf",
        "date": date_str,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Send X-daily email (envelope Bcc, TXT + optional PDF).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--date", help="Report date YYYY-MM-DD")
    p.add_argument("--report", type=Path, help="Full report TXT path")
    p.add_argument("--email-body", type=Path, help="Email body TXT path")
    p.add_argument("--pdf", type=Path, help="PDF attachment path (default: derive from date/report)")
    p.add_argument(
        "--reports-dir",
        type=Path,
        default=None,
        help="Reports directory (env X_DAILY_REPORTS_DIR, else ~/data/x-daily/reports)",
    )
    p.add_argument(
        "--credentials",
        type=Path,
        default=None,
        help="SMTP credentials.env (env X_DAILY_CREDENTIALS)",
    )
    p.add_argument(
        "--recipients",
        type=Path,
        default=None,
        help="Recipients list file (env X_DAILY_RECIPIENTS)",
    )
    return p.parse_args()


def resolve_paths(args: argparse.Namespace) -> dict[str, Path]:
    reports = (args.reports_dir or reports_dir()).expanduser().resolve()

    if args.report:
        report = args.report.expanduser().resolve()
        date_str = args.date or extract_date_from_name(report)
        email_body = (
            args.email_body.expanduser().resolve()
            if args.email_body
            else report.parent / f"x_daily_analysis_{date_str}_email_body.txt"
        )
        pdf = (
            args.pdf.expanduser().resolve()
            if args.pdf
            else report.parent / f"x_daily_analysis_{date_str}_full.pdf"
        )
        return {
            "report": report,
            "email_body": email_body,
            "pdf": pdf,
            "date": date_str,
            "reports": reports,
        }

    if args.date:
        paths = paths_for_date(reports, args.date)
        paths["reports"] = reports
        if args.email_body:
            paths["email_body"] = args.email_body.expanduser().resolve()
        if args.pdf:
            paths["pdf"] = args.pdf.expanduser().resolve()
        return paths

    candidates = sorted(reports.glob("x_daily_analysis_*_full.txt"))
    if not candidates:
        raise FileNotFoundError(f"{reports} 下没有 x_daily_analysis_*_full.txt")
    report = candidates[-1]
    date_str = extract_date_from_name(report)
    paths = paths_for_date(reports, date_str)
    paths["reports"] = reports
    if args.email_body:
        paths["email_body"] = args.email_body.expanduser().resolve()
    if args.pdf:
        paths["pdf"] = args.pdf.expanduser().resolve()
    return paths


def main() -> None:
    args = parse_args()
    cred_path = (args.credentials or credentials_path()).expanduser().resolve()
    reci_path = (args.recipients or recipients_path()).expanduser().resolve()
    paths: dict[str, Path] | None = None
    env: dict[str, str] = {}
    recipients: list[str] = []
    missing_keys: list[str] = []
    attach_pdf: bool | None = None
    step = "resolve_paths"

    try:
        step = "resolve_paths"
        paths = resolve_paths(args)
        reports = paths["reports"]
        reports.mkdir(parents=True, exist_ok=True)

        report_path = paths["report"]
        email_body_path = paths["email_body"]
        pdf_path = paths["pdf"]
        date_str = paths["date"]
        attach_pdf = pdf_path.exists() and pdf_path.stat().st_size > 0

        step = "load_recipients"
        recipients = load_recipients(reci_path)
        step = "load_credentials"
        env = load_env(cred_path)
        missing_keys = [
            key
            for key in ("smtp_server", "smtp_port", "smtp_username", "smtp_password", "email_from")
            if not env.get(key)
        ]

        if not report_path.exists() or report_path.stat().st_size <= 0:
            step = "validate_report"
            raise RuntimeError("报告文件为空或不存在")
        if not email_body_path.exists() or email_body_path.stat().st_size <= 0:
            step = "validate_email_body"
            raise RuntimeError("邮件正文为空或不存在")
        step = "validate_email_body"
        ensure_fresh_email_body(email_body_path, report_path)

        step = "validate_recipients"
        if not recipients:
            raise RuntimeError("收件人为空")

        step = "validate_config"
        if missing_keys:
            raise KeyError(",".join(missing_keys))

        step = "read_email_body"
        email_body = email_body_path.read_text(encoding="utf-8")
        subject = f"X 每日情报 · {date_str}"

        from_name = env.get("email_from_name", "").strip()
        from_addr = env["email_from"]
        from_header = f"{from_name} <{from_addr}>" if from_name else from_addr

        step = "build_message"
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = from_addr
        msg.set_content(email_body, charset="utf-8")

        add_attachment(msg, report_path)
        if attach_pdf:
            add_attachment(msg, pdf_path)

        step = "smtp_send"
        with smtplib.SMTP_SSL(
            env["smtp_server"], int(env["smtp_port"]), timeout=30
        ) as s:
            s.login(env["smtp_username"], env["smtp_password"])
            envelope_recipients = list(dict.fromkeys([from_addr, *recipients]))
            s.send_message(
                msg,
                from_addr=from_addr,
                to_addrs=envelope_recipients,
            )

        print("EMAIL_OK", len(recipients))

    except Exception as e:
        reason = short_reason(e)
        try:
            if paths is None:
                paths = resolve_paths(args)
            date_str = paths.get("date", "unknown-date")
            body = ""
            if paths["email_body"].exists():
                body = paths["email_body"].read_text(encoding="utf-8")
            failed_path = paths["reports"] / f"email_failed_{date_str}.txt"
            failed_path.write_text(body, encoding="utf-8")
            log_path = paths["reports"] / f"email_failed_{date_str}.log"
            write_failure_log(
                log_path,
                reason=reason,
                step=step,
                date_str=date_str,
                paths=paths,
                cred_path=cred_path,
                reci_path=reci_path,
                env=env,
                recipients=recipients,
                missing_keys=missing_keys,
                attach_pdf=attach_pdf,
                exc=e,
            )
        except Exception:
            pass
        print("EMAIL_FAILED", reason)


if __name__ == "__main__":
    main()
