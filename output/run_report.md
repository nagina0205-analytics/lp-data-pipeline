# LP data pipeline run report

Run time: 2026-10-23 13:53 UTC

Data quality issues: **4**  
Reconciliation breaks (admin vs ledger): **3**

## Data quality issues

| Rule | Table | Record | Detail |
| --- | --- | --- | --- |
| required_field | commitments | LP002 / FUND II | commitment_usd is missing |
| duplicate | commitments | LP001 / FUND II | same LP and fund appears twice |
| positive_amount | admin | T1006 | amount is -500.0 |
| valid_date | admin | T1010 | date could not be parsed |

## Reconciliation breaks

| Transaction | Break | Admin USD | Ledger USD | Difference USD |
| --- | --- | --- | --- | --- |
| T1006 | amount_mismatch | -500.00 | 3,684,710.94 | -3,684,210.94 |
| T1013 | amount_mismatch | 599,499.91 | 624,499.91 | -25,000.00 |
| T1021 | missing_in_ledger | 6,037,877.21 |  |  |
