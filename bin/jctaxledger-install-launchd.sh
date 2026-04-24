#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOUR="${1:-8}"
MINUTE="${2:-0}"
LABEL="com.jctaxledger.balance-report"
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

ENV_SECTION="$(
  {
    printf '    <key>EnvironmentVariables</key>\n'
    printf '    <dict>\n'
    write_env_var "Neo4jFinDBUrl"
    write_env_var "Neo4jFinDBUserName"
    write_env_var "Neo4jFinDBPassword"
    write_env_var "NEO4J_URI"
    write_env_var "NEO4J_URL"
    write_env_var "NEO4J_BOLT_URL"
    write_env_var "NEO4J_USERNAME"
    write_env_var "NEO4J_USER"
    write_env_var "NEO4J_PASSWORD"
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
      <string>${REPO_ROOT}/bin/jctaxledger-balance-report.sh</string>
      <string>--database</string>
      <string>taxjc</string>
      <string>--refresh</string>
      <string>--send</string>
    </array>
${ENV_SECTION}
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>${HOUR}</integer>
      <key>Minute</key>
      <integer>${MINUTE}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/balance-report.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/balance-report.err.log</string>
    <key>RunAtLoad</key>
    <false/>
  </dict>
</plist>
PLIST

launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl load "${PLIST_PATH}"

echo "Installed launchd job at ${PLIST_PATH}"
echo "Scheduled daily at ${HOUR}:$(printf '%02d' "${MINUTE}") local time."
echo "SMTP/Neo4j env values were captured from the current shell into the plist."
echo "If your credentials change, reinstall the job from a shell where the new env vars are set."
