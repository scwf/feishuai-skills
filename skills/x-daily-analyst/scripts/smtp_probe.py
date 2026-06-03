#!/usr/bin/env python3
"""Probe SMTP deliverability with controlled message variants.

Examples:
    python3 smtp_probe.py --to user@example.com --text "hello"
    python3 smtp_probe.py --to user@example.com --text "hello" --attach report.txt
    python3 smtp_probe.py --to user@example.com --body-file body.txt --attach report.txt --attach report.pdf
"""

from __future__ import annotations

import argparse
import mimetypes
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from x_daily_paths import credentials_path


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


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


def normalize_refused(refused: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for recipient, detail in (refused or {}).items():
        if isinstance(detail, tuple) and len(detail) >= 2:
            code, message = detail[0], detail[1]
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            out[str(recipient)] = f"{code} {message}"
        else:
            out[str(recipient)] = str(detail)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Send one controlled SMTP test email to one target recipient.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--to", required=True, help="Target recipient email")
    p.add_argument(
        "--credentials",
        type=Path,
        default=None,
        help="SMTP credentials.env (env X_DAILY_CREDENTIALS, else ~/data/x-daily/email-conf/credentials.env)",
    )
    p.add_argument("--subject", default=None, help="Subject line")
    p.add_argument("--text", default=None, help="Plain text body")
    p.add_argument("--body-file", type=Path, help="Plain text body file")
    p.add_argument("--attach", type=Path, action="append", default=[], help="Attachment path; repeatable")
    p.add_argument("--no-message-id", action="store_true", help="Do not set Message-ID explicitly")
    p.add_argument("--message-id-domain", default=None, help="Domain for generated Message-ID")
    p.add_argument("--no-date", action="store_true", help="Do not set Date explicitly")
    p.add_argument("--no-reply-to", action="store_true", help="Do not set Reply-To")
    p.add_argument("--x-mailer", default="", help="Optional X-Mailer header")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cred_path = (args.credentials or credentials_path()).expanduser().resolve()
    env = load_env(cred_path)
    required = ("smtp_server", "smtp_port", "smtp_username", "smtp_password", "email_from")
    missing = [key for key in required if not env.get(key)]
    if missing:
        print("SMTP_PROBE_FAILED 配置缺失", ",".join(missing))
        return

    if args.body_file:
        body = args.body_file.expanduser().resolve().read_text(encoding="utf-8")
    elif args.text is not None:
        body = args.text
    else:
        body = "SMTP probe plain text message."

    from_name = env.get("email_from_name", "").strip()
    from_addr = env["email_from"]
    from_header = f"{from_name} <{from_addr}>" if from_name else from_addr
    subject = args.subject or "SMTP probe"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = args.to
    if not args.no_reply_to:
        msg["Reply-To"] = from_header
    if not args.no_date:
        msg["Date"] = formatdate(localtime=True)
    message_id = ""
    if not args.no_message_id:
        message_id = make_msgid(domain=args.message_id_domain)
        msg["Message-ID"] = message_id
    if args.x_mailer:
        msg["X-Mailer"] = args.x_mailer
    msg.set_content(body, charset="utf-8")

    attachments = [path.expanduser().resolve() for path in args.attach]
    for path in attachments:
        if not path.exists() or path.stat().st_size <= 0:
            print("SMTP_PROBE_FAILED 附件缺失", path)
            return
        add_attachment(msg, path)

    try:
        with smtplib.SMTP_SSL(env["smtp_server"], int(env["smtp_port"]), timeout=30) as smtp:
            smtp.login(env["smtp_username"], env["smtp_password"])
            refused = smtp.send_message(msg, from_addr=from_addr, to_addrs=[args.to])
    except Exception as exc:
        print("SMTP_PROBE_FAILED SMTP异常", type(exc).__name__, str(exc))
        return

    refused = normalize_refused(refused)
    if args.to in refused:
        print("SMTP_PROBE_FAILED 收件人被拒收", refused[args.to])
        return

    print("SMTP_PROBE_OK")
    print(f"to: {args.to}")
    print(f"from: {from_addr}")
    print(f"subject: {subject}")
    print(f"message_id: {message_id or 'not-set'}")
    print(f"date_header: {'set' if not args.no_date else 'not-set'}")
    print(f"reply_to: {'set' if not args.no_reply_to else 'not-set'}")
    print(f"x_mailer: {args.x_mailer or 'not-set'}")
    print(f"attachments_count: {len(attachments)}")
    for path in attachments:
        print(f"attachment: {path} ({path.stat().st_size} bytes)")
    print("refused_recipients: none")


if __name__ == "__main__":
    main()
