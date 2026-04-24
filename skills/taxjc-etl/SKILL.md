---
name: taxjc-etl
description: Use when refreshing, rewriting, or validating the Jersey City tax ETL for the `taxjc` Neo4j database, especially for the HLS PropertyTaxInquiry source, account metadata updates, run-based `LedgerBlock`/`LedgerEntry` loads, `TaxBilling`/`TaxPayment` projections, ledger verification, or tax graph cleanup.
---

# TaxJC ETL

## When to use
- Refresh `taxjc` from the Jersey City HLS tax source.
- Change how tax source rows map into Neo4j.
- Validate or repair `TaxBilling`, `TaxPayment`, `BILL_FOR`, or `PAYMENT_FOR` data.
- Validate or repair `LedgerBlock`, `LedgerEntry`, `LEDGER_FOR`, `CONTAINS`, `PREVIOUS_BLOCK`, or `FOR_ACCOUNT` data.
- Clean stale labels, relationships, constraints, or indexes from `taxjc` after ETL changes.

## Workflow
1. Confirm the target database and current model before making changes.
   - Expected target is usually `taxjc`.
   - Current tax model includes `(:Account)`, `(:TaxBilling)`, `(:TaxPayment)`, `(:LedgerBlock)`, `(:LedgerEntry)`, `[:BILL_FOR]`, `[:PAYMENT_FOR]`, `[:LEDGER_FOR]`, `[:CONTAINS]`, `[:PREVIOUS_BLOCK]`, and `[:FOR_ACCOUNT]`.
2. Inspect the live source contract before changing parsing logic.
   - The current source is the HLS endpoint described in `references/etl-runbook.md`.
   - Prefer checking the actual response shape with a real account over assuming fields are stable.
3. Read only the files you need:
   - `etl/balanceReport.py`
   - `etl/jcTaxEtl.py`
   - `etl/diffLedgerSnapshots.py`
   - `etl/jcTaxJson2node.py`
   - `etl/verifyLedgerChain.py`
   - `neo4j_storage/dataService.py`
4. Make ETL changes with these constraints:
   - Keep `Account` metadata upserts separate from immutable ledger history.
   - Append one `LedgerBlock` per ETL run and account, keyed by run metadata rather than source snapshot alone.
   - Preserve `sourceHash` so unchanged HLS snapshots can still be detected across runs.
   - Continue projecting current-source rows into `TaxBilling` and `TaxPayment` for compatibility until reporting is fully ledger-native.
   - Keep `TaxBilling` and `TaxPayment` classification explicit and easy to audit.
   - Ledger entry identity must preserve duplicate-looking source rows within the same run.
   - If the ETL architecture or major business logic changes, update `README.md` and `README4ETL.md` in the same change.
   - In `README.md`, `README4ETL.md`, release notes, skills, and other public repo docs, use placeholder examples only. Do not include real account numbers, addresses, owner names, or other live sensitive data.
   - When cleaning schema objects, verify the label is no longer in use first.
5. Validate locally before the live run.
   - Run `python -m py_compile` on touched Python files.
   - Run `bin/jctaxledger-verify-ledger.sh --database <db>` after ETL changes that affect ledger writes.
   - Use `bin/jctaxledger-diff-ledger.sh --database <db>` when the task is to explain what changed between two snapshots.
   - Use `bin/jctaxledger-balance-report.sh --database <db>` when the task is to produce a local balance report or email it from this Mac.
   - For local scheduled report/email work, remember that launchd does not inherit the interactive shell env. Ensure the installer or plist carries the required Neo4j and SMTP env values.
   - If you add or change a packaged CLI command, rebuild/install the package or use the repo wrapper script when testing it.
6. Run the ETL against `taxjc` explicitly.
   - Prefer overriding `Neo4jFinDBName=taxjc` for safety.
7. Verify the graph after load.
   - Check node counts, relationship counts, year coverage, 1-2 account totals, and ledger chain integrity.
8. When packaging matters:
   - Prefer `python -m build --no-isolation` in restricted environments where isolated builds cannot download dependencies.
   - Reinstall with `python -m pip install --upgrade .` or the built wheel so new console entry points are available in the shell.

## Guardrails
- Do not assume the shell environment is pointing at `taxjc`; verify or override it.
- Treat external HLS responses as unstable. Recheck the response shape when the ETL breaks.
- If a user asks to clean the database, remove only objects unrelated to the active tax model.
- If constraints or indexes mention labels that are no longer present, verify they are stale before dropping them.
- Do not interpret repeated ETL runs as source changes automatically; compare `sourceHash`, not just block count.
- Do not leave architecture docs stale after a model change. `README.md` and `README4ETL.md` are part of the required deliverable for major ETL or ledger changes.
- Do not assume a new CLI is immediately available by name after editing `pyproject.toml`; reinstall the package or use `bin/` wrappers.
- Do not put real account examples into public-facing repo content, even if they already exist in a local database.

## References
- Read `references/etl-runbook.md` for concrete commands, source endpoints, and verification queries.
