import argparse
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser
import mimetypes
import os
from pathlib import Path
import re
import smtplib
import subprocess
import sys
from urllib.parse import urljoin

import requests


BASE_URL = "https://onlinepayment.brookhavenny.gov"
INDEX_URL = f"{BASE_URL}/taxmap/index"
POST_URL = f"{BASE_URL}/TaxMap"
PDF_URL = f"{BASE_URL}/TaxMap/GeneratePdf"
DEFAULT_OUTPUT_DIR = "var/brookhaven-tax-statements"
REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_SUBJECT = "Brookhaven tax statement"
SMTP_ENV_ALIASES = {
    "host": ("JCTAX_SMTP_HOST", "SMTP_HOST", "SMTP_SERVER"),
    "port": ("JCTAX_SMTP_PORT", "SMTP_PORT"),
    "username": (
        "JCTAX_SMTP_USERNAME",
        "SMTP_USERNAME",
        "MAIL_USERNAME",
        "EMAIL_USERNAME",
        "YAHOO_EMAIL",
        "EMAIL",
    ),
    "password": (
        "JCTAX_SMTP_PASSWORD",
        "SMTP_PASSWORD",
        "MAIL_PASSWORD",
        "EMAIL_PASSWORD",
        "YAHOO_APP_PASSWORD",
        "APP_PASSWORD",
    ),
    "from_email": (
        "JCTAX_REPORT_FROM_EMAIL",
        "SMTP_FROM_EMAIL",
        "MAIL_FROM",
        "YAHOO_EMAIL",
        "EMAIL",
    ),
    "recipient": (
        "BROOKHAVEN_TAX_EMAIL_TO",
        "JCTAX_REPORT_TO_EMAIL",
        "SMTP_TO_EMAIL",
        "JCTAX_REPORT_FROM_EMAIL",
        "SMTP_FROM_EMAIL",
        "MAIL_FROM",
        "EMAIL",
        "YAHOO_EMAIL",
        "JCTAX_SMTP_USERNAME",
        "SMTP_USERNAME",
        "MAIL_USERNAME",
        "EMAIL_USERNAME",
    ),
    "use_tls": ("JCTAX_SMTP_USE_TLS", "SMTP_USE_TLS"),
}


class TaxMapPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tokens = []
        self.links = []
        self.error_labels = []
        self._current_link = None
        self._capture_error_label = False
        self._error_text = []
        self.verification_token = None

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "input":
            if (
                attr_map.get("name") == "__RequestVerificationToken"
                and self.verification_token is None
            ):
                self.verification_token = attr_map.get("value")
        elif tag == "a":
            self._current_link = {
                "href": attr_map.get("href", ""),
                "text": "",
            }
        elif tag in {"label", "span"}:
            classes = set((attr_map.get("class") or "").split())
            if "error-label" in classes:
                self._capture_error_label = True
                self._error_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._current_link is not None:
            self.links.append(self._current_link)
            self._current_link = None
        elif tag in {"label", "span"} and self._capture_error_label:
            text = " ".join("".join(self._error_text).split())
            if text:
                self.error_labels.append(text)
            self._capture_error_label = False
            self._error_text = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.tokens.append(text)
        if self._current_link is not None:
            self._current_link["text"] += data
        if self._capture_error_label:
            self._error_text.append(data)


def _parse_page(html):
    parser = TaxMapPageParser()
    parser.feed(html)
    return parser


def _normalize_item_number(raw_item):
    digits = re.sub(r"\D", "", str(raw_item or ""))
    if len(digits) != 7:
        raise ValueError(
            f"Brookhaven item number must contain exactly 7 digits: {raw_item!r}"
        )
    return digits, f"{digits[:2]}-{digits[2:]}"


def _parse_item_values(raw_values):
    items = []
    for raw_value in raw_values:
        if not raw_value:
            continue
        for value in str(raw_value).split(","):
            value = value.strip()
            if value:
                items.append(value)
    return items


def _read_item_file(path):
    if not path:
        return []
    values = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            values.append(value)
    return values


def _safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def _write_download(output_dir, item_digits, content, suffix):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    datestamp = datetime.now().strftime("%Y%m%d")
    filename = f"brookhaven-tax-statement-{item_digits}-{datestamp}.{suffix}"
    destination = output_path / _safe_filename(filename)
    destination.write_bytes(content)
    return destination


def _is_pdf(response):
    content_type = response.headers.get("content-type", "").lower()
    return "application/pdf" in content_type or response.content.startswith(b"%PDF")


def _candidate_statement_links(page):
    candidates = []
    keywords = ("pdf", "bill", "statement", "tax", "print")
    for link in page.links:
        href = link.get("href") or ""
        text = " ".join((link.get("text") or "").split())
        haystack = f"{href} {text}".lower()
        if href and any(keyword in haystack for keyword in keywords):
            candidates.append((href, text))
    return candidates


def _extract_error_message(page):
    errors = [text for text in page.error_labels if text and text.upper() != "NEW"]
    if errors:
        return " ".join(errors)
    visible_text = " ".join(page.tokens)
    for marker in ("No value found", "Invalid", "not found"):
        if marker.lower() in visible_text.lower():
            return visible_text
    return None


def _first_env(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _smtp_config():
    username = _first_env(*SMTP_ENV_ALIASES["username"])
    host = _first_env(*SMTP_ENV_ALIASES["host"])
    if host is None and username and username.lower().endswith("@yahoo.com"):
        host = "smtp.mail.yahoo.com"

    port = _first_env(*SMTP_ENV_ALIASES["port"])
    if port is None and host:
        port = "587"

    password = _first_env(*SMTP_ENV_ALIASES["password"])
    from_email = _first_env(*SMTP_ENV_ALIASES["from_email"]) or username

    if not all([host, port, username, password, from_email]):
        return None

    return {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "from_email": from_email,
        "use_tls": (_first_env(*SMTP_ENV_ALIASES["use_tls"]) or "true").lower() != "false",
    }


def _build_email_body(downloaded_paths):
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "Brookhaven tax statement download complete.",
        f"Generated: {generated_at}",
        "",
        "Attached statements:",
    ]
    lines.extend(f"- {path.name}" for path in downloaded_paths)
    return "\n".join(lines)


def _attach_file(message, path):
    content_type, _encoding = mimetypes.guess_type(path)
    if content_type:
        maintype, subtype = content_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    message.add_attachment(
        path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=path.name,
    )


def _send_via_smtp(recipient, subject, body, attachment_paths):
    config = _smtp_config()
    if config is None:
        raise RuntimeError(
            "SMTP config is incomplete. Configure JCTAX_SMTP_HOST, "
            "JCTAX_SMTP_PORT, JCTAX_SMTP_USERNAME, JCTAX_SMTP_PASSWORD, "
            "and JCTAX_REPORT_FROM_EMAIL or equivalent SMTP aliases."
        )

    message = EmailMessage()
    message["From"] = config["from_email"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    for path in attachment_paths:
        _attach_file(message, path)

    with smtplib.SMTP(config["host"], config["port"]) as server:
        if config["use_tls"]:
            server.starttls()
        server.login(config["username"], config["password"])
        server.send_message(message)


def _osascript_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _send_via_mail_app(recipient, subject, body, attachment_paths):
    attachment_lines = []
    for path in attachment_paths:
        attachment_lines.append(
            f'make new attachment with properties {{file name:POSIX file "{_osascript_escape(str(path.resolve()))}"}} at after the last paragraph'
        )
    attachments_script = "\n    ".join(attachment_lines)
    script = f'''
tell application "Mail"
  set newMessage to make new outgoing message with properties {{subject:"{_osascript_escape(subject)}", content:"{_osascript_escape(body)}", visible:false}}
  tell newMessage
    make new to recipient at end of to recipients with properties {{address:"{_osascript_escape(recipient)}"}}
    {attachments_script}
    send
  end tell
end tell
'''
    subprocess.run(["osascript", "-e", script], check=True)


def _send_statement_email(recipient, subject, downloaded_paths, transport):
    body = _build_email_body(downloaded_paths)
    if transport == "smtp":
        _send_via_smtp(recipient, subject, body, downloaded_paths)
        return "smtp"

    if transport == "mailapp":
        _send_via_mail_app(recipient, subject, body, downloaded_paths)
        return "mailapp"

    if _smtp_config() is not None:
        _send_via_smtp(recipient, subject, body, downloaded_paths)
        return "smtp"

    if sys.platform == "darwin":
        _send_via_mail_app(recipient, subject, body, downloaded_paths)
        return "mailapp"

    raise RuntimeError(
        "No email transport available. Configure SMTP env vars or run on macOS "
        "with Mail.app configured."
    )


def download_statement(item_number, output_dir, timeout=REQUEST_TIMEOUT_SECONDS):
    item_digits, formatted_item = _normalize_item_number(item_number)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "JCTaxLedger Brookhaven Tax Statement Downloader/1.0",
            "Accept": "text/html,application/pdf",
        }
    )

    index_response = session.get(INDEX_URL, timeout=timeout)
    index_response.raise_for_status()
    index_page = _parse_page(index_response.text)
    if not index_page.verification_token:
        raise RuntimeError("Could not find Brookhaven request verification token.")

    response = session.post(
        POST_URL,
        data={
            "__RequestVerificationToken": index_page.verification_token,
            "address": "",
            "id": formatted_item,
            "sctm": "",
        },
        headers={"Referer": INDEX_URL},
        timeout=timeout,
    )
    response.raise_for_status()

    if _is_pdf(response):
        return _write_download(output_dir, item_digits, response.content, "pdf")

    page = _parse_page(response.text)
    error_message = _extract_error_message(page)
    if error_message:
        raise RuntimeError(f"Brookhaven lookup failed for {formatted_item}: {error_message}")

    pdf_response = session.get(
        PDF_URL,
        headers={"Referer": response.url},
        timeout=timeout,
    )
    pdf_response.raise_for_status()
    if _is_pdf(pdf_response):
        return _write_download(output_dir, item_digits, pdf_response.content, "pdf")

    for href, _text in _candidate_statement_links(page):
        linked_response = session.get(
            urljoin(response.url, href),
            headers={"Referer": response.url},
            timeout=timeout,
        )
        linked_response.raise_for_status()
        if _is_pdf(linked_response):
            return _write_download(output_dir, item_digits, linked_response.content, "pdf")

    return _write_download(output_dir, item_digits, response.content, "html")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download Brookhaven tax statements from the public tax map UI by "
            "7-digit item number."
        )
    )
    parser.add_argument(
        "--item",
        action="append",
        help="Brookhaven item number. Accepts 7 digits or the 99-99999 display format. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--items-file",
        help="File containing one item number per line. Comments after # are ignored.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("BROOKHAVEN_TAX_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
        help=f"Directory for downloaded statements. Default: {DEFAULT_OUTPUT_DIR}.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=REQUEST_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Default: {REQUEST_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Email downloaded statements after a successful download.",
    )
    parser.add_argument(
        "--recipient",
        default=_first_env(*SMTP_ENV_ALIASES["recipient"]),
        help="Recipient email. Defaults to BROOKHAVEN_TAX_EMAIL_TO, then common email aliases.",
    )
    parser.add_argument(
        "--subject",
        default=DEFAULT_SUBJECT,
        help=f"Email subject when --send is used. Default: {DEFAULT_SUBJECT}.",
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "smtp", "mailapp"),
        default="auto",
        help="Email transport when --send is used. Default: auto.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    item_values = []
    item_values.extend(_parse_item_values(args.item or []))
    item_values.extend(_read_item_file(args.items_file))
    item_values.extend(_parse_item_values([os.getenv("BROOKHAVEN_ITEM_NUMBERS")]))

    if not item_values:
        raise SystemExit(
            "No Brookhaven item numbers provided. Use --item, --items-file, or BROOKHAVEN_ITEM_NUMBERS."
        )

    failures = []
    downloaded_paths = []
    for item_value in item_values:
        try:
            destination = download_statement(
                item_value,
                output_dir=args.output_dir,
                timeout=args.timeout,
            )
            downloaded_paths.append(destination)
            print(f"Downloaded {item_value}: {destination}")
        except Exception as exc:
            failures.append((item_value, exc))
            print(f"Failed {item_value}: {exc}")

    if failures:
        raise SystemExit(1)

    if args.send:
        if not args.recipient:
            raise SystemExit(
                "No email recipient configured. Use --recipient or BROOKHAVEN_TAX_EMAIL_TO."
            )
        transport = _send_statement_email(
            recipient=args.recipient,
            subject=args.subject,
            downloaded_paths=downloaded_paths,
            transport=args.transport,
        )
        print(f"Emailed {len(downloaded_paths)} statement(s) to {args.recipient} via {transport}.")


if __name__ == "__main__":
    main()
