"""Create synthetic source files for the LP data pipeline.

Three mock systems hold the same LP activity in different formats:
  - CRM: LP commitments per fund
  - Fund administrator: capital calls and distributions
  - General ledger: the same cash movements as booked by accounting

A few errors are planted on purpose (a missing amount, a duplicate row,
a ledger amount that does not match the administrator, a bad date) so the
pipeline has real discrepancies to catch. All data is fake.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
random.seed(16)

LPS = [
    ("LP001", "Redwood State Pension"), ("LP002", "Harbor University Endowment"),
    ("LP003", "Summit Family Office"), ("LP004", "Prairie Health Foundation"),
    ("LP005", "Cascade Sovereign Fund"), ("LP006", "Lakeside Insurance Co"),
    ("LP007", "Northstar Fund of Funds"), ("LP008", "Mesa Teachers Retirement"),
]
FUNDS = ["Fund I", "Fund II", "Growth Fund I"]


def main():
    RAW.mkdir(parents=True, exist_ok=True)

    commitments = []
    for lp_id, name in LPS:
        for fund in random.sample(FUNDS, k=random.randint(1, 3)):
            commitments.append({
                "lp_id": lp_id,
                "lp_name": name,
                "fund": fund,
                "commitment_usd": random.choice([5, 10, 15, 25, 40, 50]) * 1_000_000,
            })

    admin_rows, gl_rows = [], []
    txn = 1000
    for c in commitments:
        start = date(2021, 1, 15)
        for i in range(random.randint(3, 6)):
            txn += 1
            kind = "capital_call" if i < 3 or random.random() < 0.6 else "distribution"
            pct = random.uniform(0.05, 0.15)
            amount = round(c["commitment_usd"] * pct, 2)
            when = start + timedelta(days=90 * i + random.randint(0, 20))
            admin_rows.append({
                "txn_id": f"T{txn}", "lp_id": c["lp_id"], "fund": c["fund"],
                "txn_type": kind, "txn_date": when.isoformat(), "amount_usd": amount,
            })
            # The ledger books calls as positive cash in, distributions as negative.
            signed = amount if kind == "capital_call" else -amount
            gl_rows.append({
                "journal_ref": f"JE-{txn}", "investor_code": c["lp_id"].lower(),
                "fund_name": c["fund"].upper(), "posting_date": when.strftime("%m/%d/%Y"),
                "amount": f"{signed:,.2f}",
            })

    # Planted problems
    commitments[2]["commitment_usd"] = ""                 # missing value
    commitments.append(dict(commitments[0]))              # duplicate row
    admin_rows[5]["amount_usd"] = -500.00                 # negative amount
    admin_rows[9]["txn_date"] = "2021-13-40"              # invalid date
    gl_rows[12]["amount"] = "{:,.2f}".format(float(gl_rows[12]["amount"].replace(",", "")) + 25_000)  # mismatch
    del gl_rows[20]                                       # missing from ledger

    write(RAW / "crm_lp_commitments.csv", commitments)
    write(RAW / "fund_admin_transactions.csv", admin_rows)
    write(RAW / "general_ledger.csv", gl_rows)
    print(f"Wrote {len(commitments)} commitments, {len(admin_rows)} admin rows, {len(gl_rows)} ledger rows")


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
