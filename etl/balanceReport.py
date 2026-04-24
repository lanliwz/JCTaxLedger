import argparse
import os
import smtplib
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage

from neo4j import GraphDatabase

try:
    from etl.jcTaxEtl import load2neo4j
except ImportError:
    from jcTaxEtl import load2neo4j


DEFAULT_DATABASE = "taxjc"
DEFAULT_SUBJECT = "JCTaxLedger balance report"
NEO4J_ENV_ALIASES = {
    "url": ("Neo4jFinDBUrl", "NEO4J_URI", "NEO4J_URL", "NEO4J_BOLT_URL"),
    "username": ("Neo4jFinDBUserName", "NEO4J_USERNAME", "NEO4J_USER"),
    "password": ("Neo4jFinDBPassword", "NEO4J_PASSWORD"),
}
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
    "use_tls": ("JCTAX_SMTP_USE_TLS", "SMTP_USE_TLS"),
}


def _parse_account_list(raw_accounts):
    if not raw_accounts:
        return None

    parsed_accounts = []
    for value in raw_accounts.split(","):
        account = value.strip()
        if not account:
            continue
        parsed_accounts.append(int(account))

    return parsed_accounts or None


def _first_env(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _ensure_legacy_neo4j_envs():
    legacy_mappings = {
        "Neo4jFinDBUrl": _first_env(*NEO4J_ENV_ALIASES["url"]),
        "Neo4jFinDBUserName": _first_env(*NEO4J_ENV_ALIASES["username"]),
        "Neo4jFinDBPassword": _first_env(*NEO4J_ENV_ALIASES["password"]),
    }

    for env_name, value in legacy_mappings.items():
        if value and not os.getenv(env_name):
            os.environ[env_name] = value


def _build_driver():
    _ensure_legacy_neo4j_envs()
    neo4j_url = _first_env(*NEO4J_ENV_ALIASES["url"])
    username = _first_env(*NEO4J_ENV_ALIASES["username"])
    password = _first_env(*NEO4J_ENV_ALIASES["password"])

    if not neo4j_url or not username or not password:
        raise RuntimeError(
            "Missing Neo4j connection env vars. Looked for "
            f"url={NEO4J_ENV_ALIASES['url']}, "
            f"username={NEO4J_ENV_ALIASES['username']}, "
            f"password={NEO4J_ENV_ALIASES['password']}."
        )

    return GraphDatabase.driver(neo4j_url, auth=(username, password))


def _load_account_report_rows(database, year, accounts=None):
    query = """
    MATCH (a:Account)
    WHERE a.email IS NOT NULL
      AND ($accounts IS NULL OR a.Account IN $accounts)
    CALL (a) {
      OPTIONAL MATCH (b:TaxBilling)-[:BILL_FOR]->(a)
      WHERE b.Year = $year
      RETURN round(coalesce(sum(b.Billed), 0.0) * 100) / 100.0 AS billed
    }
    CALL (a) {
      OPTIONAL MATCH (p:TaxPayment)-[:PAYMENT_FOR]->(a)
      WHERE p.Year = $year
      RETURN round(coalesce(sum(p.Paid), 0.0) * 100) / 100.0 AS paid
    }
    RETURN a.Account AS account,
           a.address AS address,
           a.email AS email,
           billed,
           paid,
           round((billed + paid) * 100) / 100.0 AS balance
    ORDER BY email, account
    """

    driver = _build_driver()
    try:
        with driver.session(database=database) as session:
            return [record.data() for record in session.run(query, year=str(year), accounts=accounts)]
    finally:
        driver.close()


def _group_rows_by_email(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["email"]].append(row)
    return grouped


def _format_money(value):
    return f"{value:,.2f}"


def _build_report_body(database, year, rows, refreshed):
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "JCTaxLedger balance report",
        f"Generated: {generated_at}",
        f"Database: {database}",
        f"Report year: {year}",
        f"ETL refresh: {'yes' if refreshed else 'no'}",
        "",
    ]

    total_billed = 0.0
    total_paid = 0.0
    total_balance = 0.0

    for row in rows:
        total_billed += row["billed"]
        total_paid += row["paid"]
        total_balance += row["balance"]
        lines.extend(
            [
                f"Account: {row['account']}",
                f"Address: {row['address'] or 'address unavailable'}",
                f"Billed: {_format_money(row['billed'])}",
                f"Paid: {_format_money(row['paid'])}",
                f"Balance: {_format_money(row['balance'])}",
                "",
            ]
        )

    lines.extend(
        [
            "Portfolio totals",
            f"Billed: {_format_money(total_billed)}",
            f"Paid: {_format_money(total_paid)}",
            f"Balance: {_format_money(total_balance)}",
        ]
    )
    return "\n".join(lines)


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
        return None, {
            "host": SMTP_ENV_ALIASES["host"],
            "port": SMTP_ENV_ALIASES["port"],
            "username": SMTP_ENV_ALIASES["username"],
            "password": SMTP_ENV_ALIASES["password"],
            "from_email": SMTP_ENV_ALIASES["from_email"],
        }

    return {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "from_email": from_email,
        "use_tls": (_first_env(*SMTP_ENV_ALIASES["use_tls"]) or "true").lower() != "false",
    }, None


def _send_via_smtp(recipient, subject, body):
    config, missing_help = _smtp_config()
    if config is None:
        raise RuntimeError(
            "SMTP config is incomplete. Looked for these env vars: "
            f"host={missing_help['host']}, "
            f"port={missing_help['port']}, "
            f"username={missing_help['username']}, "
            f"password={missing_help['password']}, "
            f"from_email={missing_help['from_email']}."
        )

    message = EmailMessage()
    message["From"] = config["from_email"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(config["host"], config["port"]) as server:
        if config["use_tls"]:
            server.starttls()
        server.login(config["username"], config["password"])
        server.send_message(message)


def _osascript_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _send_via_mail_app(recipient, subject, body):
    script = f'''
tell application "Mail"
  set newMessage to make new outgoing message with properties {{subject:"{_osascript_escape(subject)}", content:"{_osascript_escape(body)}", visible:false}}
  tell newMessage
    make new to recipient at end of to recipients with properties {{address:"{_osascript_escape(recipient)}"}}
    send
  end tell
end tell
'''
    subprocess.run(["osascript", "-e", script], check=True)


def _send_report(recipient, subject, body, transport):
    if transport == "smtp":
        _send_via_smtp(recipient, subject, body)
        return "smtp"

    if transport == "mailapp":
        _send_via_mail_app(recipient, subject, body)
        return "mailapp"

    config, _ = _smtp_config()
    if config is not None:
        _send_via_smtp(recipient, subject, body)
        return "smtp"

    if sys.platform == "darwin":
        _send_via_mail_app(recipient, subject, body)
        return "mailapp"

    raise RuntimeError(
        "No email transport available. Configure SMTP env vars or run on macOS "
        "with Mail.app configured."
    )


def run_balance_report(database, year, accounts=None, refresh=False, send=False, transport="auto"):
    _ensure_legacy_neo4j_envs()

    if refresh:
        load2neo4j(accounts=accounts, database=database)

    rows = _load_account_report_rows(database=database, year=year, accounts=accounts)
    if not rows:
        raise RuntimeError("No Account rows with email were found for the requested scope.")

    grouped = _group_rows_by_email(rows)
    deliveries = []

    for recipient, recipient_rows in sorted(grouped.items()):
        subject = f"{DEFAULT_SUBJECT} ({year})"
        body = _build_report_body(
            database=database,
            year=year,
            rows=recipient_rows,
            refreshed=refresh,
        )
        delivery = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
        }
        if send:
            delivery["transport"] = _send_report(recipient, subject, body, transport)
        deliveries.append(delivery)

    return deliveries


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Refresh tax data, build a balance report, and optionally email it "
            "from this Mac."
        )
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Neo4j database to query. Default: {DEFAULT_DATABASE}.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Report year. Default: current year.",
    )
    parser.add_argument(
        "--accounts",
        help="Comma-separated account numbers to scope the ETL/report.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Run ETL before building the report.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the report by email instead of only printing it.",
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "smtp", "mailapp"),
        default="auto",
        help="Email transport. Default: auto.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    deliveries = run_balance_report(
        database=args.database,
        year=args.year,
        accounts=_parse_account_list(args.accounts),
        refresh=args.refresh,
        send=args.send,
        transport=args.transport,
    )

    for delivery in deliveries:
        print(f"Recipient: {delivery['recipient']}")
        if args.send:
            print(f"Transport: {delivery['transport']}")
        print(delivery["body"])
        print("")


if __name__ == "__main__":
    main()
