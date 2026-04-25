# JCTaxLedger

JCTaxLedger is a Jersey City property tax ETL, reporting, and blockchain-style ledger project backed by Neo4j.

![JCTaxLedger front page](frontpage.svg)

It is designed as a publication-friendly visual for the project's blockchain-style ledger theme and can be reused for:

- article covers
- LinkedIn posts
- presentation front pages
- project overview visuals

The SVG emphasizes:

- a foreground-first title treatment for article-cover readability
- append-only `LedgerBlock` and `LedgerEntry` structure
- Neo4j-style graph relationships
- verification and snapshot diff workflow
- the `JCTaxLedger` branding and `v1.0.0` milestone

## Purpose

The purpose of JCTaxLedger is to extract Jersey City, New Jersey property tax billing and payment data for individual accounts, load that history into Neo4j as an append-only ledger, and make it easy for the account owner to track and manage the account over time.

The intended workflow is:

1. Pull billing and payment history for one or more Jersey City property tax accounts from the public HLS tax system.
2. Write each ETL refresh into Neo4j as immutable `LedgerBlock` and `LedgerEntry` records linked to the account.
3. Project the latest source snapshot into `TaxBilling` and `TaxPayment` nodes for compatibility with current reporting.
4. Let the account owner query the graph in natural language to:
   - track billing and payment activity
   - check current and historical balance
   - monitor year-over-year tax increases
   - investigate changes after a refresh
   - verify the integrity of the ledger chain over time
5. Use project skills so an agent can help the account owner perform ETL, reporting, ledger verification, and follow-up workflows consistently.

This repository currently contains these active pieces:

- An ETL script that pulls Jersey City tax bill and payment history from the public HLS tax inquiry site, appends immutable ledger blocks and entries into Neo4j, and refreshes compatibility projections for current reporting.

## What the project does

The active application logic in this repository is the ETL flow in [`etl/jcTaxEtl.py`](etl/jcTaxEtl.py). It fetches structured JSON from the Jersey City HLS property tax inquiry endpoint, normalizes account metadata and tax history through [`etl/jcTaxJson2node.py`](etl/jcTaxJson2node.py), appends run-based `LedgerBlock` and `LedgerEntry` history, and refreshes the `TaxBilling` and `TaxPayment` compatibility projection in Neo4j.

The project is designed so the account owner can then use an agent and the repo skills to work with that graph in higher-level ways, such as producing ledger reports, checking balances, analyzing tax increases, explaining what changed between ETL runs, and verifying the chain itself.

## Why the Blockchain Model Matters

JCTaxLedger uses the useful parts of blockchain design without requiring a distributed network or cryptocurrency.

Each ETL run appends a new `LedgerBlock` for each account. Each block stores:

- `runId` and `createdAt` so every refresh is preserved as a historical event
- `sourceHash` so unchanged versus changed source snapshots can be detected
- `blockHash`, `prevHash`, and `blockHeight` so the chain can be verified
- `LedgerEntry` records for the underlying bill and payment events included in that run

This matters because property tax data is not only about the latest balance. It is also about proving what the source said at a given time, understanding what changed between refreshes, and detecting accidental or unauthorized data drift.

The blockchain-style model is important here for four reasons:

- Auditability: every ETL run is preserved instead of overwritten
- Change detection: `sourceHash` shows whether a new run actually changed source content
- Integrity: `blockHash` and `prevHash` make the chain tamper-evident
- Replayability: balances and reports can be reconstructed from historical ledger entries

The `TaxBilling` and `TaxPayment` nodes remain in the graph as compatibility projections for reporting. They are not the system of record. The append-only ledger is the system of record.

## Project layout

```text
.
├── neo4j_storage/                       # Neo4j write/read helper
└── etl/                                 # Jersey City tax scraping + graph load
```

## Prerequisites

- Python 3.10+ recommended
- A running Neo4j database populated with `Account` nodes

Install from a local checkout:

```bash
python -m pip install .
```

Install from the rebuilt `v1.0.0` wheel:

```bash
python -m pip install --upgrade dist/jctaxledger-1.0.0-py3-none-any.whl
```

If a newly added CLI command is not found in your shell, reinstall the package so the new console script entry points are registered:

```bash
python -m pip install --upgrade .
```

If you want dependency-only installation without packaging:

```bash
python -m pip install -r requirements.txt
```

## Configuration

Set these environment variables before running the ETL:

```bash
export Neo4jFinDBUrl="bolt://localhost:7687"
export Neo4jFinDBUserName="neo4j"
export Neo4jFinDBPassword="password"
export Neo4jFinDBName="taxjc"
```

## Loading Jersey City tax data into Neo4j

The ETL script expects `Account` nodes to already exist in Neo4j. It reads each `Account.Account` value, calls the HLS property tax inquiry endpoint, updates account metadata, appends one new `LedgerBlock` per ETL run and account, stores immutable `LedgerEntry` rows for the underlying source events, and refreshes the `TaxBilling`/`TaxPayment` projection for current reporting.

Run it with:

```bash
jctaxledger-etl
```

from the repo checkout without installing:

```bash
bin/jctaxledger-etl.sh
```

or directly:

```bash
python etl/jcTaxEtl.py
```

Behavior to be aware of:

- The script now runs only when executed as the main module.
- It loads data from `https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry/GetAccountDetails`.
- The request is keyed by account number and includes an `interestThruDate` parameter.
- Every ETL run generates a `runId` and appends a distinct `LedgerBlock` per account.
- `LedgerBlock.sourceHash` captures whether the HLS source snapshot changed between runs.
- `LedgerBlock.blockHash` and `LedgerBlock.prevHash` support chain verification.
- `LedgerEntry` stores immutable bill and payment events for each block.
- The ETL still writes the latest bill rows into `TaxBilling` and payment rows into `TaxPayment` for compatibility.
- The ETL refreshes account metadata such as `accountId`, `address`, `ownerName`, `propertyLocation`, `principal`, `interest`, and `totalDue`.
- The split between `TaxBilling` and `TaxPayment` is classification-based, so the billing/payment rule in the ETL should be kept in sync with the HLS source semantics.
- The append-only ledger is the system of record; `TaxBilling` and `TaxPayment` are derived projections.
- The packaged CLI supports `--accounts` for comma-separated partial refreshes and `--database` to override the target database.

## Ledger Verification

Use the verifier after ETL runs to confirm that the blockchain-style ledger chain is still consistent:

```bash
jctaxledger-verify-ledger --database taxjc
```

from the repo checkout without installing:

```bash
bin/jctaxledger-verify-ledger.sh --database taxjc
```

The verifier checks:

- contiguous `blockHeight` values per account
- `PREVIOUS_BLOCK` links to the expected prior block
- `prevHash` matches the prior block's `blockHash`
- `entryCount` matches the actual number of `LedgerEntry` links
- stored `blockHash` matches the recomputed value

## Snapshot Diff

Use the diff CLI to compare two ledger snapshots and identify what changed between runs.

Latest two blocks per account:

```bash
jctaxledger-diff-ledger --database taxjc
```

Repo wrapper:

```bash
bin/jctaxledger-diff-ledger.sh --database taxjc
```

Specific accounts:

```bash
jctaxledger-diff-ledger --database taxjc --accounts 123456,234567
```

Specific block pair:

```bash
jctaxledger-diff-ledger --database taxjc --old-block-id <oldBlockId> --new-block-id <newBlockId>
```

JSON output:

```bash
jctaxledger-diff-ledger --database taxjc --format json
```

The diff report highlights:

- whether `sourceHash` changed
- rows added in the newer snapshot
- rows removed in the newer snapshot
- rows present in both snapshots but with changed fields

## Local Balance Report

The repository includes a local reporting script for this Mac:

- [`etl/balanceReport.py`](etl/balanceReport.py)
- [`bin/jctaxledger-balance-report.sh`](bin/jctaxledger-balance-report.sh)
- [`bin/jctaxledger-install-launchd.sh`](bin/jctaxledger-install-launchd.sh)

Use it to refresh tax data, compute balances, and email a report to the `email` stored on each `Account`.

Print the report locally:

```bash
bin/jctaxledger-balance-report.sh --database taxjc
```

Refresh first, then print:

```bash
bin/jctaxledger-balance-report.sh --database taxjc --refresh
```

Refresh and send email:

```bash
bin/jctaxledger-balance-report.sh --database taxjc --refresh --send
```

The email transport works like this:

- if SMTP env vars are configured, it uses SMTP
- otherwise, on macOS it falls back to Mail.app via AppleScript
- the script accepts both project-specific env vars such as `JCTAX_SMTP_*` and common local aliases such as `SMTP_*`, `MAIL_*`, `EMAIL`, `YAHOO_EMAIL`, and `YAHOO_APP_PASSWORD`
- the script also accepts Neo4j aliases such as `NEO4J_URI`, `NEO4J_URL`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` and maps them to the ETL's legacy `Neo4jFinDB*` names when needed

To install a local daily scheduler on this Mac with `launchd`:

```bash
bin/jctaxledger-install-launchd.sh 8 0
```

That example schedules the report for `8:00` local time each day.
The installer captures the current shell's Neo4j and SMTP-related env vars into the generated plist because `launchd` does not inherit your interactive shell environment automatically. Reinstall the job after credential changes.

## Brookhaven Tax Statement Downloads

Download Brookhaven tax statements from the public Town of Brookhaven tax map UI by item number:

```bash
bin/jctaxledger-download-brookhaven-tax-statement.sh --item 12-34567
```

The downloader also accepts 7 digits without the dash:

```bash
bin/jctaxledger-download-brookhaven-tax-statement.sh --item 1234567
```

For recurring downloads, set item numbers in the current shell and install the monthly `launchd` job:

```bash
export BROOKHAVEN_ITEM_NUMBERS="12-34567,23-45678"
export BROOKHAVEN_TAX_OUTPUT_DIR="var/brookhaven-tax-statements"
export BROOKHAVEN_TAX_EMAIL_TO="you@example.com"
bin/jctaxledger-install-brookhaven-tax-statement-launchd.sh 8 30
```

That schedules the downloader for April 15 and December 15 every year at `8:30` local time, then emails the downloaded statement. The installer captures the current shell's `BROOKHAVEN_*` and SMTP/email env vars into the generated plist because `launchd` does not inherit your interactive shell environment automatically.

## Packaging

Build release artifacts locally with:

```bash
python -m build
```

If isolated builds cannot download dependencies in a restricted environment, use the local toolchain instead:

```bash
python -m build --no-isolation
```

This produces:

- `dist/jctaxledger-1.0.0.tar.gz`
- `dist/jctaxledger-1.0.0-py3-none-any.whl`

Release notes for this milestone are in [`RELEASE_NOTES_v1.0.0.md`](RELEASE_NOTES_v1.0.0.md).

## Skills

The repo includes local skills under [`skills/`](skills/):

- [`skills/taxjc-etl/SKILL.md`](skills/taxjc-etl/SKILL.md)
- [`skills/taxjc-reporting/SKILL.md`](skills/taxjc-reporting/SKILL.md)

These skills are meant to be used by an agent on behalf of the account owner.

- Use `taxjc-etl` when the owner wants to refresh or validate tax history in Neo4j.
- Use `taxjc-reporting` when the owner wants account-level summaries, balances, year-over-year comparisons, tax ledger reports, or run-to-run blockchain-style ledger comparisons built from `Account`, `TaxBilling`, `TaxPayment`, `LedgerBlock`, and `LedgerEntry`.

As the project grows, additional skills can cover reminders, alerts, owner-facing summaries, and recurring tax monitoring workflows.

Supporting query examples live in:

- [`skills/taxjc-reporting/references/report-queries.md`](skills/taxjc-reporting/references/report-queries.md)

That reference now includes ledger-oriented queries for comparing consecutive `LedgerBlock` runs by account and checking whether the latest ETL run changed the underlying source snapshot.

## Documentation Workflow

For this project, architecture and major logic changes are not complete until the docs are updated too.

At minimum:

- update `README.md` when the top-level architecture, ledger model, CLI surface, or workflow changes
- update `README4ETL.md` when the ETL flow, data model, verification process, or operational behavior changes
- do not use real account numbers, addresses, owner names, or other sensitive live examples in public-facing repo documents; use placeholders instead

This rule is especially important for ledger, blockchain-style, schema, and reporting-model changes, because stale documentation makes verification and maintenance much harder.

## Tax Ledger Report

To create a tax ledger report with the reporting skill:

1. Refresh the data first if needed:

```bash
bin/jctaxledger-etl.sh
```

2. Use the reporting skill and ask for the report you want.

Example prompts:

```text
Use $taxjc-reporting to create a tax ledger report for account 123456 for 2025, showing total billed, total paid, net balance, and the underlying billing and payment rows.
```

```text
Use $taxjc-reporting to create a yearly tax ledger report for all accounts in taxjc, grouped by account and year, with billed, paid, balance, and year-over-year billing increase.
```

```text
Use $taxjc-reporting to create a property tax ledger report grouped by address for 2024 and 2025, and call out any balance differences after the latest ETL refresh.
```

Recommended report sections:

- account or address
- reporting period
- ledger run or block context where relevant
- total billed
- total paid
- net balance
- year-over-year increase where applicable
- detailed billing rows
- detailed payment rows
- source-change status between consecutive ledger runs where applicable

## Current limitations

- There are no automated tests in the repository.
- The repository currently includes generated `__pycache__` content in the working tree.
- Current financial reporting still reads mainly from `TaxBilling` and `TaxPayment`; the ledger is the system of record, but not all reports are ledger-native yet.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
