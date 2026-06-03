#!/usr/bin/env python3
"""
Send X-daily report email: plain body + TXT attachment + optional PDF.

The sender receives one self-copy. Each target recipient receives a separate
message with its own To header, so recipients are not exposed to each other and
enterprise mail gateways see a normal point-to-point delivery shape.

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
from email.utils import formatdate, make_msgid
from email.message import EmailMessage
from pathlib import Path
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPRecipientsRefused,
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
    if isinstance(exc, SMTPRecipientsRefused):
        return "收件人被拒收"
    if isinstance(exc, FileNotFoundError):
        return "文件缺失"
    if isinstance(exc, KeyError):
        return "配置缺失"
    if isinstance(exc, SMTPException):
        return "SMTP失败"
    if isinstance(exc, RuntimeError) and "收件人被拒收" in str(exc):
        return "收件人被拒收"
    if isinstance(exc, RuntimeError) and "邮件正文过期" in str(exc):
        return "邮件正文过期"
    if isinstance(exc, RuntimeError) and "收件人" in str(exc):
        return "收件人为空"
    return "未知错误"


def normalize_refused_recipients(refused: dict | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for recipient, detail in (refused or {}).items():
        if isinstance(detail, tuple) and len(detail) >= 2:
            code, message = detail[0], detail[1]
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            normalized[str(recipient)] = f"{code} {message}"
        else:
            normalized[str(recipient)] = str(detail)
    return normalized


def format_delivery_attempts(attempts: list[dict[str, str]] | None) -> list[str]:
    if not attempts:
        return ["- none"]
    lines = []
    for attempt in attempts:
        role = attempt.get("role", "")
        recipient = attempt.get("recipient", "")
        status = attempt.get("status", "")
        detail = attempt.get("detail", "")
        message_id = attempt.get("message_id", "")
        parts = []
        if message_id:
            parts.append(f"message_id={message_id}")
        if detail:
            parts.append(detail)
        suffix = f" ({'; '.join(parts)})" if parts else ""
        lines.append(f"- {role}: {recipient}: {status}{suffix}")
    return lines


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
    envelope_recipients: list[str] | None = None,
    refused_recipients: dict | None = None,
    delivery_attempts: list[dict[str, str]] | None = None,
    missing_keys: list[str] | None = None,
    attach_pdf: bool | None = None,
    exc: BaseException | None = None,
) -> None:
    env = env or {}
    recipients = recipients or []
    envelope_recipients = envelope_recipients or []
    refused_recipients = normalize_refused_recipients(refused_recipients)
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

    lines.extend(
        [
            f"envelope_recipients_count: {len(envelope_recipients)}",
            "envelope_recipients:",
        ]
    )
    if envelope_recipients:
        lines.extend(f"- {recipient}" for recipient in envelope_recipients)
    else:
        lines.append("- none")

    lines.extend(["refused_recipients:"])
    if refused_recipients:
        lines.extend(f"- {recipient}: {detail}" for recipient, detail in refused_recipients.items())
    else:
        lines.append("- none")

    lines.extend(["delivery_attempts:"])
    lines.extend(format_delivery_attempts(delivery_attempts))

    lines.extend(["", "exception:"])
    if exc is not None:
        lines.extend(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_success_log(
    path: Path,
    *,
    date_str: str,
    paths: dict[str, Path],
    cred_path: Path,
    reci_path: Path,
    env: dict[str, str],
    recipients: list[str],
    envelope_recipients: list[str],
    refused_recipients: dict | None,
    delivery_attempts: list[dict[str, str]],
    attach_pdf: bool,
) -> None:
    refused_recipients = normalize_refused_recipients(refused_recipients)
    accepted_targets = [recipient for recipient in recipients if recipient not in refused_recipients]
    lines = [
        "status: EMAIL_OK",
        f"date: {date_str}",
        "",
        f"report: {paths.get('report', '')}",
        f"email_body: {paths.get('email_body', '')}",
        f"pdf: {paths.get('pdf', '')}",
        f"attach_pdf: {attach_pdf}",
        "",
        f"smtp_server: {env.get('smtp_server', '')}",
        f"smtp_port: {env.get('smtp_port', '')}",
        f"email_from: {env.get('email_from', '')}",
        f"credentials_file: {cred_path}",
        f"recipients_file: {reci_path}",
        "",
        f"target_recipients_count: {len(recipients)}",
        f"accepted_target_recipients_count: {len(accepted_targets)}",
        "target_recipients:",
    ]
    if recipients:
        lines.extend(f"- {recipient}" for recipient in recipients)
    else:
        lines.append("- none")
    lines.extend(
        [
            f"envelope_recipients_count: {len(envelope_recipients)}",
            "envelope_recipients:",
        ]
    )
    if envelope_recipients:
        lines.extend(f"- {recipient}" for recipient in envelope_recipients)
    else:
        lines.append("- none")
    lines.append("refused_recipients:")
    if refused_recipients:
        lines.extend(f"- {recipient}: {detail}" for recipient, detail in refused_recipients.items())
    else:
        lines.append("- none")
    lines.append("delivery_attempts:")
    lines.extend(format_delivery_attempts(delivery_attempts))
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


def build_message(
    *,
    subject: str,
    from_header: str,
    to_addr: str,
    email_body: str,
    report_path: Path,
    pdf_path: Path,
    attach_pdf: bool,
) -> tuple[EmailMessage, str]:
    message_id = make_msgid(domain="x-daily.local")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to_addr
    msg["Reply-To"] = from_header
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id
    msg["X-Mailer"] = "X-Daily Analyst"
    msg.set_content(email_body, charset="utf-8")

    add_attachment(msg, report_path)
    if attach_pdf:
        add_attachment(msg, pdf_path)
    return msg, message_id


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
    envelope_recipients: list[str] = []
    refused_recipients: dict = {}
    delivery_attempts: list[dict[str, str]] = []
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

        step = "smtp_send"
        with smtplib.SMTP_SSL(
            env["smtp_server"], int(env["smtp_port"]), timeout=30
        ) as s:
            s.login(env["smtp_username"], env["smtp_password"])
            self_msg, self_message_id = build_message(
                subject=subject,
                from_header=from_header,
                to_addr=from_addr,
                email_body=email_body,
                report_path=report_path,
                pdf_path=pdf_path,
                attach_pdf=bool(attach_pdf),
            )
            envelope_recipients = [from_addr]
            self_refused = s.send_message(
                self_msg, from_addr=from_addr, to_addrs=[from_addr]
            )
            refused_recipients.update(self_refused)
            if from_addr in self_refused:
                delivery_attempts.append(
                    {
                        "role": "self",
                        "recipient": from_addr,
                        "status": "refused",
                        "message_id": self_message_id,
                        "detail": normalize_refused_recipients(self_refused).get(from_addr, ""),
                    }
                )
            else:
                delivery_attempts.append(
                    {
                        "role": "self",
                        "recipient": from_addr,
                        "status": "accepted",
                        "message_id": self_message_id,
                    }
                )

            for recipient in recipients:
                target_msg, target_message_id = build_message(
                    subject=subject,
                    from_header=from_header,
                    to_addr=recipient,
                    email_body=email_body,
                    report_path=report_path,
                    pdf_path=pdf_path,
                    attach_pdf=bool(attach_pdf),
                )
                envelope_recipients.append(recipient)
                try:
                    refused = s.send_message(
                        target_msg,
                        from_addr=from_addr,
                        to_addrs=[recipient],
                    )
                except SMTPRecipientsRefused as exc:
                    refused = exc.recipients
                refused_recipients.update(refused)
                if recipient in refused:
                    delivery_attempts.append(
                        {
                            "role": "target",
                            "recipient": recipient,
                            "status": "refused",
                            "message_id": target_message_id,
                            "detail": normalize_refused_recipients(refused).get(recipient, ""),
                        }
                    )
                else:
                    delivery_attempts.append(
                        {
                            "role": "target",
                            "recipient": recipient,
                            "status": "accepted",
                            "message_id": target_message_id,
                        }
                    )

        accepted_target_count = sum(
            1
            for attempt in delivery_attempts
            if attempt.get("role") == "target" and attempt.get("status") == "accepted"
        )
        if accepted_target_count < len(recipients):
            failed_targets = [
                attempt.get("recipient", "")
                for attempt in delivery_attempts
                if attempt.get("role") == "target" and attempt.get("status") != "accepted"
            ]
            raise RuntimeError("目标收件人被拒收：" + ",".join(failed_targets))

        success_log_path = reports / f"email_sent_{date_str}.log"
        write_success_log(
            success_log_path,
            date_str=date_str,
            paths=paths,
            cred_path=cred_path,
            reci_path=reci_path,
            env=env,
            recipients=recipients,
            envelope_recipients=envelope_recipients,
            refused_recipients=refused_recipients,
            delivery_attempts=delivery_attempts,
            attach_pdf=bool(attach_pdf),
        )

        print("EMAIL_OK", accepted_target_count)

    except Exception as e:
        reason = short_reason(e)
        if isinstance(e, SMTPRecipientsRefused):
            refused_recipients = e.recipients
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
                envelope_recipients=envelope_recipients,
                refused_recipients=refused_recipients,
                delivery_attempts=delivery_attempts,
                missing_keys=missing_keys,
                attach_pdf=attach_pdf,
                exc=e,
            )
        except Exception:
            pass
        print("EMAIL_FAILED", reason)


if __name__ == "__main__":
    main()
