# LP Data Pipeline and Reconciliation Monitor

A venture firm's investor data usually lives in more than one place. The CRM has LP commitments, the fund administrator has capital calls and distributions, and accounting books the same cash in the general ledger. When those systems disagree, someone finds out late, usually while building an LP report.

This project pulls all three sources into one SQL database, checks the data against 8 quality rules, reconciles the fund administrator against the ledger, and publishes a report of every problem it finds. GitHub Actions runs it every day.

All data is synthetic. `src/generate_data.py` creates it and plants a few errors on purpose so the checks have something to catch.

## What it does

1. **Extract** three CSV files, one per source system.
2. **Standardize** them. The systems use different ID casing, fund name formats, date formats and sign conventions (the ledger books distributions as negative numbers). The pipeline puts them in one shape.
3. **Validate** with 8 rules: required fields, duplicate commitments, duplicate transaction IDs, positive amounts, valid dates, valid transaction types, every transaction tied to a known commitment, and capital called never above commitment.
4. **Load** clean tables into SQLite.
5. **Reconcile** administrator vs ledger by transaction. Any amount difference above $1, or a transaction missing on either side, is a break.
6. **Report** to `output/run_report.md`, plus CSVs of issues, breaks, and an LP capital summary (committed, called, distributed, unfunded) built with SQL.

## Latest run

See [`output/run_report.md`](output/run_report.md). On the sample data it finds 4 data quality issues and 3 reconciliation breaks, which matches the errors planted in the generator.

## Run it yourself

```
pip install -r requirements.txt
python src/generate_data.py
python src/pipeline.py
python -m unittest discover tests -v
```

## Project layout

```
src/generate_data.py      creates the three mock source files
src/pipeline.py           extract, standardize, validate, load, reconcile, report
tests/test_pipeline.py    unit tests for each rule and the reconciliation
.github/workflows/        daily scheduled run on GitHub Actions
output/                   run report and CSV outputs
```

## Why I built it this way

I spent four years at Bitmatrix reconciling data from 8 enterprise sources, and most discrepancies came from the same few causes: formats that did not match, rows that landed twice, and records that existed in one system but not the other. Each rule here maps to one of those causes. Every issue in the report names the rule, the table and the exact record, so the person fixing it does not have to go hunting.

Next steps I would take with real systems: replace the CSV extract with API pulls, move from SQLite to a cloud warehouse, and send the daily break count to Slack.
