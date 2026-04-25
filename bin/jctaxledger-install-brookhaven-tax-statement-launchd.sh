#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOUR="${1:-8}"
MINUTE="${2:-30}"
LABEL="com.jctaxledger.brookhaven-tax-statement"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/JCTaxLedger"

mkdir -p "${PLIST_DIR}" "${LOG_DIR}"

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  printf '%s' "${value}"
}

write_env_var() {
  local key="$1"
  local value="${!key:-}"
  if [[ -n "${value}" ]]; then
    printf '      <key>%s</key>\n' "${key}"
    printf '      <string>%s</string>\n' "$(xml_escape "${value}")"
  fi
}

if [[ -z "${BROOKHAVEN_ITEM_NUMBERS:-}" ]]; then
  echo "BROOKHAVEN_ITEM_NUMBERS is required, for example: 12-34567,23-45678" >&2
  exit 1
fi

BROOKHAVEN_TAX_EMAIL_TO="$(
  printf '%s' "${BROOKHAVEN_TAX_EMAIL_TO:-${JCTAX_REPORT_FROM_EMAIL:-${SMTP_FROM_EMAIL:-${MAIL_FROM:-${EMAIL:-${YAHOO_EMAIL:-}}}}}}"
)"
export BROOKHAVEN_TAX_EMAIL_TO

if [[ -z "${BROOKHAVEN_TAX_EMAIL_TO}" ]]; then
  echo "Set BROOKHAVEN_TAX_EMAIL_TO, JCTAX_REPORT_FROM_EMAIL, SMTP_FROM_EMAIL, EMAIL, or YAHOO_EMAIL before installing the email scheduler." >&2
  exit 1
fi

ENV_SECTION="$(
  {
    printf '    <key>EnvironmentVariables</key>\n'
    printf '    <dict>\n'
    write_env_var "BROOKHAVEN_ITEM_NUMBERS"
    write_env_var "BROOKHAVEN_TAX_OUTPUT_DIR"
    write_env_var "BROOKHAVEN_TAX_EMAIL_TO"
    write_env_var "JCTAX_SMTP_HOST"
    write_env_var "JCTAX_SMTP_PORT"
    write_env_var "JCTAX_SMTP_USERNAME"
    write_env_var "JCTAX_SMTP_PASSWORD"
    write_env_var "JCTAX_REPORT_FROM_EMAIL"
    write_env_var "JCTAX_SMTP_USE_TLS"
    write_env_var "SMTP_HOST"
    write_env_var "SMTP_SERVER"
    write_env_var "SMTP_PORT"
    write_env_var "SMTP_USERNAME"
    write_env_var "SMTP_PASSWORD"
    write_env_var "SMTP_FROM_EMAIL"
    write_env_var "SMTP_TO_EMAIL"
    write_env_var "SMTP_USE_TLS"
    write_env_var "MAIL_USERNAME"
    write_env_var "MAIL_PASSWORD"
    write_env_var "MAIL_FROM"
    write_env_var "EMAIL_USERNAME"
    write_env_var "EMAIL_PASSWORD"
    write_env_var "EMAIL"
    write_env_var "YAHOO_EMAIL"
    write_env_var "YAHOO_APP_PASSWORD"
    write_env_var "APP_PASSWORD"
    write_env_var "PYTHON_BIN"
    printf '    </dict>\n'
  }
)"

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${REPO_ROOT}/bin/jctaxledger-download-brookhaven-tax-statement.sh</string>
      <string>--send</string>
      <string>--transport</string>
      <string>mailapp</string>
    </array>
${ENV_SECTION}
    <key>StartCalendarInterval</key>
    <array>
      <dict>
        <key>Month</key>
        <integer>4</integer>
        <key>Day</key>
        <integer>15</integer>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
      </dict>
      <dict>
        <key>Month</key>
        <integer>12</integer>
        <key>Day</key>
        <integer>15</integer>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
      </dict>
    </array>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/brookhaven-tax-statement.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/brookhaven-tax-statement.err.log</string>
    <key>RunAtLoad</key>
    <false/>
  </dict>
</plist>
PLIST

plutil -lint "${PLIST_PATH}"
launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl load "${PLIST_PATH}"

echo "Installed launchd job at ${PLIST_PATH}"
echo "Scheduled yearly on April 15 and December 15 at ${HOUR}:$(printf '%02d' "${MINUTE}") local time."
echo "Brookhaven item and email env values were captured from the current shell into the plist."
echo "If item numbers, output directory, or email credentials change, reinstall the job from a shell where the new env vars are set."
