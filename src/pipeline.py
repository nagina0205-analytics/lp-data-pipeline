"""LP data pipeline: extract, standardize, validate, load, reconcile, report.

Run from the project folder:
    python src/generate_data.py
    python src/pipeline.py
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "output"
DB = OUT / "lp_warehouse.db"
TOLERANCE_USD = 1.00
VALID_TXN_TYPES = {"capital_call", "distribution"}


# ---------- Extract ----------
def extract():
    return {
        "commitments": pd.read_csv(RAW / "crm_lp_commitments.csv", dtype=str),
        "admin": pd.read_csv(RAW / "fund_admin_transactions.csv", dtype=str),
        "ledger": pd.read_csv(RAW / "general_ledger.csv", dtype=str),
    }


# ---------- Transform: put all three systems in one shape ----------
def standardize_commitments(df):
    out = df.copy()
    out["lp_id"] = out["lp_id"].str.strip().str.upper()
    out["fund"] = out["fund"].str.strip().str.upper()
    out["commitment_usd"] = pd.to_numeric(out["commitment_usd"], errors="coerce")
    return out


def standardize_admin(df):
    out = df.copy()
    out["lp_id"] = out["lp_id"].str.strip().str.upper()
    out["fund"] = out["fund"].str.strip().str.upper()
    out["txn_type"] = out["txn_type"].str.strip().str.lower()
    out["txn_date"] = pd.to_datetime(out["txn_date"], format="%Y-%m-%d", errors="coerce")
    out["amount_usd"] = pd.to_numeric(out["amount_usd"], errors="coerce")
    return out


def standardize_ledger(df):
    out = pd.DataFrame()
    out["txn_id"] = df["journal_ref"].str.replace("JE-", "T", regex=False)
    out["lp_id"] = df["investor_code"].str.strip().str.upper()
    out["fund"] = df["fund_name"].str.strip().str.upper()
    out["txn_date"] = pd.to_datetime(df["posting_date"], format="%m/%d/%Y", errors="coerce")
    signed = pd.to_numeric(df["amount"].str.replace(",", "", regex=False), errors="coerce")
    out["txn_type"] = signed.apply(lambda v: "capital_call" if v >= 0 else "distribution")
    out["amount_usd"] = signed.abs()
    return out


# ---------- Validate: data quality rules ----------
def run_quality_rules(commitments, admin):
    """Return a list of issues. Each issue names the rule, the table and the record."""
    issues = []

    def add(rule, table, key, detail):
        issues.append({"rule": rule, "table": table, "record": key, "detail": detail})

    # 1. Required fields present
    for col in ["lp_id", "fund", "commitment_usd"]:
        for _, r in commitments[commitments[col].isna()].iterrows():
            add("required_field", "commitments", f"{r['lp_id']} / {r['fund']}", f"{col} is missing")
    for col in ["txn_id", "lp_id", "fund", "amount_usd"]:
        for _, r in admin[admin[col].isna()].iterrows():
            add("required_field", "admin", r["txn_id"], f"{col} is missing")

    # 2. No duplicate commitments
    dup = commitments[commitments.duplicated(["lp_id", "fund"], keep="first")]
    for _, r in dup.iterrows():
        add("duplicate", "commitments", f"{r['lp_id']} / {r['fund']}", "same LP and fund appears twice")

    # 3. Unique transaction ids
    for t in admin[admin["txn_id"].duplicated()]["txn_id"]:
        add("duplicate", "admin", t, "transaction id repeated")

    # 4. Amounts must be positive
    for _, r in admin[admin["amount_usd"] <= 0].iterrows():
        add("positive_amount", "admin", r["txn_id"], f"amount is {r['amount_usd']}")

    # 5. Valid dates
    for _, r in admin[admin["txn_date"].isna()].iterrows():
        add("valid_date", "admin", r["txn_id"], "date could not be parsed")

    # 6. Valid transaction types
    for _, r in admin[~admin["txn_type"].isin(VALID_TXN_TYPES)].iterrows():
        add("valid_type", "admin", r["txn_id"], f"unknown type {r['txn_type']}")

    # 7. Every transaction belongs to a known commitment
    known = set(zip(commitments["lp_id"], commitments["fund"]))
    for _, r in admin.iterrows():
        if (r["lp_id"], r["fund"]) not in known:
            add("referential", "admin", r["txn_id"], "no matching LP commitment")

    # 8. Capital called cannot exceed commitment
    calls = admin[admin["txn_type"] == "capital_call"].groupby(["lp_id", "fund"])["amount_usd"].sum()
    commit = commitments.drop_duplicates(["lp_id", "fund"]).set_index(["lp_id", "fund"])["commitment_usd"]
    for key, called in calls.items():
        if key in commit.index and pd.notna(commit[key]) and called > commit[key]:
            add("over_called", "admin", " / ".join(key), f"called {called:,.0f} vs commitment {commit[key]:,.0f}")

    return issues


# ---------- Reconcile: fund administrator vs general ledger ----------
def reconcile(admin, ledger):
    merged = admin.merge(ledger, on="txn_id", how="outer", suffixes=("_admin", "_gl"), indicator=True)
    breaks = []
    for _, r in merged.iterrows():
        if r["_merge"] == "left_only":
            breaks.append((r["txn_id"], "missing_in_ledger", r["amount_usd_admin"], None))
        elif r["_merge"] == "right_only":
            breaks.append((r["txn_id"], "missing_in_admin", None, r["amount_usd_gl"]))
        else:
            a, g = r["amount_usd_admin"], r["amount_usd_gl"]
            if pd.isna(a) or pd.isna(g) or abs(abs(a) - g) > TOLERANCE_USD:
                breaks.append((r["txn_id"], "amount_mismatch", a, g))
    df = pd.DataFrame(breaks, columns=["txn_id", "break_type", "admin_amount_usd", "ledger_amount_usd"])
    df["difference_usd"] = (df["admin_amount_usd"].abs() - df["ledger_amount_usd"]).round(2)
    return df


# ---------- Load ----------
def load(tables):
    OUT.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as con:
        for name, df in tables.items():
            df.to_sql(name, con, if_exists="replace", index=False)


def lp_summary_sql():
    """Example of the SQL layer analysts query after the load."""
    query = """
        SELECT c.lp_id, c.lp_name, c.fund, c.commitment_usd,
               COALESCE(SUM(CASE WHEN a.txn_type='capital_call' THEN a.amount_usd END), 0) AS called_usd,
               COALESCE(SUM(CASE WHEN a.txn_type='distribution' THEN a.amount_usd END), 0) AS distributed_usd
        FROM commitments c
        LEFT JOIN admin_transactions a ON a.lp_id = c.lp_id AND a.fund = c.fund
        GROUP BY c.lp_id, c.lp_name, c.fund, c.commitment_usd
        ORDER BY c.lp_id, c.fund
    """
    with sqlite3.connect(DB) as con:
        df = pd.read_sql(query, con)
    df["unfunded_usd"] = df["commitment_usd"] - df["called_usd"]
    return df


# ---------- Report ----------
def write_report(issues, breaks, summary):
    pd.DataFrame(issues).to_csv(OUT / "data_quality_issues.csv", index=False)
    breaks.to_csv(OUT / "reconciliation_breaks.csv", index=False)
    summary.to_csv(OUT / "lp_capital_summary.csv", index=False)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# LP data pipeline run report", "",
        f"Run time: {now}", "",
        f"Data quality issues: **{len(issues)}**  ",
        f"Reconciliation breaks (admin vs ledger): **{len(breaks)}**", "",
        "## Data quality issues", "",
        "| Rule | Table | Record | Detail |", "| --- | --- | --- | --- |",
    ]
    lines += [f"| {i['rule']} | {i['table']} | {i['record']} | {i['detail']} |" for i in issues] or ["| none | | | |"]
    lines += ["", "## Reconciliation breaks", "",
              "| Transaction | Break | Admin USD | Ledger USD | Difference USD |", "| --- | --- | --- | --- | --- |"]
    for _, b in breaks.iterrows():
        lines.append(f"| {b.txn_id} | {b.break_type} | {fmt(b.admin_amount_usd)} | {fmt(b.ledger_amount_usd)} | {fmt(b.difference_usd)} |")
    (OUT / "run_report.md").write_text("\n".join(lines) + "\n")


def fmt(v):
    return "" if pd.isna(v) else f"{v:,.2f}"


def main():
    raw = extract()
    commitments = standardize_commitments(raw["commitments"])
    admin = standardize_admin(raw["admin"])
    ledger = standardize_ledger(raw["ledger"])

    issues = run_quality_rules(commitments, admin)
    breaks = reconcile(admin, ledger)

    load({
        "commitments": commitments.drop_duplicates(["lp_id", "fund"]),
        "admin_transactions": admin,
        "ledger_transactions": ledger,
    })
    summary = lp_summary_sql()
    write_report(issues, breaks, summary)

    print(f"Loaded {len(commitments)} commitments, {len(admin)} admin rows, {len(ledger)} ledger rows")
    print(f"Data quality issues: {len(issues)} | Reconciliation breaks: {len(breaks)}")
    print(f"Report: {OUT / 'run_report.md'}")


if __name__ == "__main__":
    main()
