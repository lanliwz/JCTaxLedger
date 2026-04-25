# JCTaxLedger ETL README

This document describes the current Jersey City tax ETL implemented in this repository.

This file is part of the required workflow for ETL maintenance. If the ETL architecture or major logic changes, update this document together with `README.md` in the same change.
Do not use real account numbers, addresses, owner names, or other live sensitive examples in this document. Use placeholders in all public-facing examples.

## Scope

The ETL code lives in:

- [`etl/jcTaxEtl.py`](etl/jcTaxEtl.py)
- [`etl/balanceReport.py`](etl/balanceReport.py)
- [`etl/diffLedgerSnapshots.py`](etl/diffLedgerSnapshots.py)
- [`etl/jcTaxJson2node.py`](etl/jcTaxJson2node.py)
- [`etl/verifyLedgerChain.py`](etl/verifyLedgerChain.py)
- [`neo4j_storage/dataService.py`](neo4j_storage/dataService.py)

Its job is to fetch property tax account details from the Jersey City HLS site, normalize the source into an append-only blockchain-style ledger, update `Account` metadata, and refresh the compatibility projection in `TaxBilling` and `TaxPayment`.

## ETL Architecture

The ETL has two outputs:

1. The system of record:
   - `LedgerBlock`
   - `LedgerEntry`
2. The reporting projection:
   - `TaxBilling`
   - `TaxPayment`

The ledger is append-only. Each ETL run creates one `LedgerBlock` per account and links it to the prior block for that same account through `PREVIOUS_BLOCK`.

The projection is refresh-oriented. `TaxBilling` and `TaxPayment` are rebuilt from the latest source snapshot so existing reporting continues to work.

This split exists for a reason:

- the ledger preserves every ETL run as historical evidence
- the projection keeps simple billing and payment reports fast and familiar
- `sourceHash` lets you tell whether a new ETL run actually changed the source payload
- `blockHash` and `prevHash` let you verify the ledger chain over time

## Source System

The ETL no longer scrapes the old HTML table site.

It now uses:

- landing page:
  - [https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry](https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry)
- data endpoint:
  - [https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry/GetAccountDetails](https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry/GetAccountDetails)

The endpoint is called with:

- `accountNumber`
- `interestThruDate`

Example request shape:

```text
GET /JerseyCity/PropertyTaxInquiry/GetAccountDetails?accountNumber=123456&interestThruDate=Tue%20Mar%2003%202026
```

The response contains:

- `accountInquiryVM`
- `notesVM`
- `validAccountNumber`
- `genericTextVM`

The ETL uses `accountInquiryVM`, especially:

- account-level metadata such as `AccountId`, `AccountNumber`, `Address`, `OwnerName`, `PropertyLocation`, `Principal`, `Interest`, `TotalDue`
- `Details`, which contains bill and payment history rows

## End-to-End Flow

The ETL executes this sequence:

1. Open a Neo4j connection using `Neo4jFinDB*` environment variables.
2. Read all account numbers with:

```cypher
MATCH (n:Account) RETURN n.Account as account_num
```

3. Generate one ETL-level `runId` and `loadedAt` timestamp.
4. For each account number, call the HLS detail endpoint.
5. Normalize account metadata into a single `Account` property map.
6. Normalize each source detail row into a tax history property map.
7. Classify normalized rows into billing-like and payment-like sets.
8. Compute `sourceHash` for the full source payload.
9. Build one run-based `LedgerBlock` for that account.
10. Build immutable `LedgerEntry` rows for the block.
11. Upsert the `Account` node.
12. Append the `LedgerBlock`, `LedgerEntry`, `LEDGER_FOR`, `CONTAINS`, `FOR_ACCOUNT`, and `PREVIOUS_BLOCK` relationships.
13. Replace that account's `TaxBilling` and `TaxPayment` projection rows.

The ledger is append-only. The projection is replace-on-refresh.

## How the Code Is Structured

### `etl/jcTaxEtl.py`

Main responsibilities:

- build the `interestThruDate` request parameter
- fetch `accountInquiryVM` JSON for each account number
- generate run metadata
- normalize data through helper functions
- write ledger history and projection rows to Neo4j

Current source endpoint constant:

```python
PROPERTY_TAX_INQUIRY_URL = "https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry/GetAccountDetails"
```

Important behavior:

- the module runs only under `if __name__ == "__main__":`
- it exposes a CLI
- default CLI behavior refreshes all `Account` nodes from the `taxjc` database
- `--accounts` accepts a comma-separated list for partial refreshes
- `--database` overrides the target Neo4j database
- one ETL invocation generates one `runId`, reused across all accounts loaded in that run

### `etl/jcTaxJson2node.py`

Main responsibilities:

- normalize account-level source fields
- build a normalized `taxAccountId`
- normalize source detail rows into graph property maps
- build `sourceHash`
- build run-based `LedgerBlock` properties
- build immutable `LedgerEntry` properties

Account properties currently written include:

- `Account`
- `accountId`
- `taxAccountId`
- `address`
- `ownerName`
- `propertyLocation`
- `block`
- `lot`
- `qualifier`
- `bankName`
- `principal`
- `interest`
- `totalDue`
- `updatedFromSource`

Ledger block properties currently written include:

- `blockId`
- `Account`
- `accountId`
- `chainScope`
- `sourceSystem`
- `runId`
- `sourceHash`
- `entryCount`
- `createdAt`
- `ledgerVersion`
- `prevHash`
- `blockHeight`
- `blockHash`

Ledger entry properties currently written include:

- `entryId`
- `entryHash`
- `blockId`
- `eventType`
- `ordinal`
- `createdAt`
- `ledgerVersion`
- plus the normalized source row fields such as:
  - `sourceId`
  - `Account`
  - `AccountId`
  - `Year`
  - `Qtr`
  - `DueDate`
  - `TransactionDate`
  - `Description`
  - `Type`
  - `Billed`
  - `Paid`
  - `Adjusted`
  - `OpenBalance`
  - `InterestDue`
  - `Days`
  - `BillSequence`
  - `TransactionId`
  - `TransCode`
  - `DepositNumber`
  - `SortCode`
  - `PaymentSourceDescription`
  - `CheckNumber`
  - `CreatedBy`
  - `PaidBy` when present

Projection row properties currently written include the same normalized tax row fields in `TaxBilling` and `TaxPayment`.

### `etl/verifyLedgerChain.py`

Main responsibilities:

- read ledger blocks by account from Neo4j
- recompute expected `blockHash`
- verify `blockHeight`
- verify `prevHash`
- verify `PREVIOUS_BLOCK`
- verify `entryCount` against the actual `CONTAINS` relationships

It exits non-zero when the chain is inconsistent.

### `etl/diffLedgerSnapshots.py`

Main responsibilities:

- choose two blocks to compare per account
- default to the latest two blocks when block IDs are not provided
- compare `sourceHash` between snapshots
- report rows added in the newer snapshot
- report rows removed in the newer snapshot
- report rows with the same `sourceId` but changed fields

It supports both text and JSON output.

### `etl/balanceReport.py`

Main responsibilities:

- optionally refresh ETL before reporting
- query billed, paid, and balance totals by account and year
- group report output by account email
- send email through SMTP or Mail.app on macOS

This script is the local reporting entry point for scheduled balance emails on this Mac.

### `neo4j_storage/dataService.py`

Main responsibilities:

- manage the Neo4j driver
- read account numbers
- upsert `Account` metadata
- append ledger history for one account at a time
- replace projection rows for one account at a time

The write path is split into separate concerns:

1. upsert `Account`
2. append `LedgerBlock` and `LedgerEntry`
3. link the block to the prior block when one exists
4. replace projection rows in `TaxBilling` and `TaxPayment`

## Current Graph Model

The ETL writes this shape:

```text
(:Account {
  Account,
  accountId,
  taxAccountId,
  address,
  ownerName,
  propertyLocation,
  principal,
  interest,
  totalDue,
  ...
})

(:LedgerBlock {
  blockId,
  Account,
  accountId,
  runId,
  sourceHash,
  createdAt,
  entryCount,
  blockHeight,
  prevHash,
  blockHash,
  ...
})

(:LedgerEntry {
  entryId,
  entryHash,
  blockId,
  eventType,
  ordinal,
  Account,
  AccountId,
  Year,
  Qtr,
  DueDate,
  TransactionDate,
  Description,
  Type,
  Billed,
  Paid,
  Adjusted,
  OpenBalance,
  InterestDue,
  ...
})

(:TaxBilling {
  Account,
  AccountId,
  Year,
  Qtr,
  DueDate,
  TransactionDate,
  Description,
  Type,
  Billed,
  Paid,
  Adjusted,
  OpenBalance,
  InterestDue,
  ...
})

(:TaxPayment {
  Account,
  AccountId,
  Year,
  Qtr,
  DueDate,
  TransactionDate,
  Description,
  Type,
  Billed,
  Paid,
  Adjusted,
  OpenBalance,
  InterestDue,
  ...
})

(:LedgerBlock)-[:LEDGER_FOR]->(:Account)
(:LedgerBlock)-[:CONTAINS]->(:LedgerEntry)
(:LedgerBlock)-[:PREVIOUS_BLOCK]->(:LedgerBlock)
(:LedgerEntry)-[:FOR_ACCOUNT]->(:Account)
(:TaxBilling)-[:BILL_FOR]->(:Account)
(:TaxPayment)-[:PAYMENT_FOR]->(:Account)
```

Join key:

- `Account.Account = LedgerBlock.Account`
- `Account.Account = LedgerEntry.Account`
- `Account.Account = TaxBilling.Account`
- `Account.Account = TaxPayment.Account`

## Important Constraint Behavior

The old `JerseyCityTaxBilling` constraint and related stale indexes were removed after the model was split into `TaxBilling` and `TaxPayment`.

The active model now also depends on ledger labels and relationships:

- `LedgerBlock`
- `LedgerEntry`
- `LEDGER_FOR`
- `CONTAINS`
- `PREVIOUS_BLOCK`
- `FOR_ACCOUNT`

If you clean schema objects, confirm they are stale before removing them.

## Runtime Prerequisites

The ETL assumes all of the following are true:

- Neo4j is running and reachable
- `Account` nodes already exist
- each `Account` node has an `Account` property with the Jersey City account number
- the HLS site is reachable

Required environment variables:

```bash
export Neo4jFinDBUrl="bolt://localhost:7687"
export Neo4jFinDBUserName="neo4j"
export Neo4jFinDBPassword="your-password"
export Neo4jFinDBName="taxjc"
```

Python packages used by ETL:

```bash
pip install neo4j requests
```

## How To Run

From the repository root:

```bash
python etl/jcTaxEtl.py
```

Or use the repo wrapper script:

```bash
bin/jctaxledger-etl.sh
```

This default command:

- targets Neo4j database `taxjc`
- queries `Account` nodes from that database
- appends one ledger block per account for the current ETL run
- refreshes the billing and payment projection for every returned account

To refresh only selected accounts:

```bash
python etl/jcTaxEtl.py --accounts 123456,234567
```

Wrapper equivalent:

```bash
bin/jctaxledger-etl.sh --accounts 123456,234567
```

To override the database explicitly:

```bash
python etl/jcTaxEtl.py --database taxjc
```

Wrapper equivalent:

```bash
bin/jctaxledger-etl.sh --database taxjc
```

To print a local balance report:

```bash
bin/jctaxledger-balance-report.sh --database taxjc
```

To refresh and email the report:

```bash
bin/jctaxledger-balance-report.sh --database taxjc --refresh --send
```

The local balance report accepts:

- Neo4j env vars in either legacy `Neo4jFinDB*` form or common aliases such as `NEO4J_URI`, `NEO4J_URL`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`
- SMTP env vars in either `JCTAX_SMTP_*` form or common aliases such as `SMTP_*`, `MAIL_*`, `EMAIL`, `YAHOO_EMAIL`, and `YAHOO_APP_PASSWORD`

To install a local macOS scheduler:

```bash
bin/jctaxledger-install-launchd.sh 8 0
```

The installer writes the current shell's Neo4j and SMTP-related env vars into the generated launchd plist because launchd does not inherit your interactive shell environment automatically. Reinstall the job after credential changes.

## Brookhaven Tax Statement Downloader

The Brookhaven statement downloader uses the public tax map form at:

- [https://onlinepayment.brookhavenny.gov/taxmap/index](https://onlinepayment.brookhavenny.gov/taxmap/index)

It fetches the request verification token from the form, submits the `Item Number` lookup, and saves the returned PDF or statement HTML under `var/brookhaven-tax-statements` by default.

Run manually:

```bash
bin/jctaxledger-download-brookhaven-tax-statement.sh --item 12-34567
```

Run for multiple item numbers:

```bash
bin/jctaxledger-download-brookhaven-tax-statement.sh --item 12-34567 --item 23-45678
```

Install the monthly scheduler:

```bash
export BROOKHAVEN_ITEM_NUMBERS="12-34567,23-45678"
export BROOKHAVEN_TAX_OUTPUT_DIR="var/brookhaven-tax-statements"
export BROOKHAVEN_TAX_EMAIL_TO="you@example.com"
bin/jctaxledger-install-brookhaven-tax-statement-launchd.sh 8 30
```

The scheduler runs on April 15 and December 15 every year, then emails the downloaded statement. The scheduler installer writes the current shell's `BROOKHAVEN_ITEM_NUMBERS`, optional `BROOKHAVEN_TAX_OUTPUT_DIR`, `BROOKHAVEN_TAX_EMAIL_TO`, SMTP/email env vars, and optional `PYTHON_BIN` into the generated launchd plist.

To diff the latest two snapshots per account:

```bash
python etl/diffLedgerSnapshots.py --database taxjc
```

Wrapper equivalent:

```bash
bin/jctaxledger-diff-ledger.sh --database taxjc
```

If your interpreter does not resolve local imports from the repo root, run with explicit `PYTHONPATH`:

```bash
PYTHONPATH=. python etl/jcTaxEtl.py
```

To force the target database:

```bash
Neo4jFinDBName=taxjc PYTHONPATH=. python etl/jcTaxEtl.py
```

To combine both:

```bash
PYTHONPATH=. python etl/jcTaxEtl.py --database taxjc --accounts 123456,234567
```

## How To Verify

Run the ledger verifier after ETL:

```bash
python etl/verifyLedgerChain.py --database taxjc
```

Wrapper equivalent:

```bash
bin/jctaxledger-verify-ledger.sh --database taxjc
```

The verifier checks:

- block heights are contiguous per account
- `PREVIOUS_BLOCK` points to the expected prior block
- `prevHash` matches the prior block hash
- `entryCount` equals the actual linked entry count
- stored `blockHash` equals the recomputed hash

Useful chain inspection query:

```cypher
MATCH (b:LedgerBlock)-[:LEDGER_FOR]->(a:Account)
OPTIONAL MATCH (b)-[:PREVIOUS_BLOCK]->(prev:LedgerBlock)
RETURN a.Account AS account,
       b.blockHeight AS blockHeight,
       b.runId AS runId,
       b.blockId AS blockId,
       b.sourceHash AS sourceHash,
       prev.blockId AS previousBlockId
ORDER BY account, blockHeight
```

Useful run-to-run source change query:

```cypher
MATCH (b:LedgerBlock)-[:LEDGER_FOR]->(a:Account)
OPTIONAL MATCH (b)-[:PREVIOUS_BLOCK]->(prev:LedgerBlock)
RETURN a.Account AS account,
       b.blockHeight AS blockHeight,
       b.runId AS runId,
       b.sourceHash AS sourceHash,
       prev.sourceHash AS previousSourceHash,
       CASE
         WHEN prev IS NULL THEN null
         WHEN b.sourceHash = prev.sourceHash THEN 'UNCHANGED'
         ELSE 'CHANGED'
       END AS sourceChangeStatus
ORDER BY account, blockHeight
```

The snapshot diff CLI gives the same workflow without requiring manual Cypher:

```bash
bin/jctaxledger-diff-ledger.sh --database taxjc --accounts 123456,234567
```

To compare a specific block pair:

```bash
bin/jctaxledger-diff-ledger.sh --database taxjc --old-block-id <oldBlockId> --new-block-id <newBlockId>
```

## Inputs and Outputs

Input from Neo4j:

- existing `Account` nodes
- specifically the `Account` property returned by `MATCH (n:Account)`

Input from the remote site:

- one JSON response per account from `GetAccountDetails`

Output written to Neo4j:

- refreshed `Account` metadata
- appended `LedgerBlock` rows for each account-run
- appended `LedgerEntry` rows for each account-run
- appended `LEDGER_FOR`, `CONTAINS`, `PREVIOUS_BLOCK`, and `FOR_ACCOUNT` relationships
- refreshed `TaxBilling` rows for each account
- refreshed `TaxPayment` rows for each account
- refreshed `BILL_FOR` and `PAYMENT_FOR` relationships

## Idempotency Characteristics

The ETL is now split into two different behaviors.

Append-only behavior:

- each ETL run appends a new ledger block per account
- repeated runs are preserved even if the underlying source payload is unchanged
- the same `sourceHash` across consecutive blocks means the source snapshot did not change

Refresh behavior:

- `TaxBilling` and `TaxPayment` are replaced per account on each refresh
- rerunning the ETL for the same source state should converge on the same projection rows

What is not fully lossless:

- the billing/payment split is classification-based and depends on current HLS row semantics
- current reporting still depends heavily on the projection, not only the ledger

## Operational Risks

These are the main ETL risks in the current implementation:

- the ETL depends on an external site with no retry or backoff policy yet
- it refreshes one account at a time and does not checkpoint progress
- if the HLS response shape changes, normalization code will need to be updated
- if HLS changes the meaning of row descriptions or `Type`, the billing/payment split rule may need to be updated
- repeated ETL runs increase ledger history size, which is intended but requires monitoring over time

## Verified Current Load Shape

The current observed test load shape includes:

- `Account`
- `LedgerBlock`
- `LedgerEntry`
- `TaxBilling`
- `TaxPayment`

For command examples in this document, account numbers such as `123456` and `234567` are fake placeholders.

## Recommended Next Improvements

If this ETL is going to be used repeatedly, these changes should come first:

1. Add retries, logging, and partial-failure reporting around the HLS requests.
2. Add tests for source normalization using captured endpoint payloads.
3. Add tests for ledger verification and multi-run chain progression.
4. Move more reporting from `TaxBilling`/`TaxPayment` onto ledger-native queries and projections.
