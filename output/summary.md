# Sales Reporting Summary

## Report Status
- Status: ready.
- Reason: All validations passed and no data quality warnings were found.

## Executive Summary
- Total final revenue was $27,275.55.
- Total orders were 250, with 755 units sold.
- Overall AOV was $109.10.
- Discounts reduced gross revenue by $1,736.30, a 5.5% discount impact.
- The strongest month was 2025-08 with $3,676.16 in revenue.
- The weakest month was 2025-03 with $1,214.95 in revenue.
- The highest month-over-month growth was 146.3% in 2025-04.

## Business Insights
- Electronics was the leading category, generating $17,776.35 in revenue.
- C004 was the highest-revenue customer, contributing $968.43.
- Noise-Canceling Headphones was the highest-revenue product, contributing $7,396.43.
- Detected anomalies: 5.

## Data Quality Notes
- Original uploaded data contained 3 duplicate groups involving 6 rows.
- 3 selected duplicate row(s) were removed from the temporary report input before calculation. The original uploaded file was not changed.
- Required order columns were present.
- Duplicate rows: 0.
- Repeated order_id rows: 0.
- Repeated order_id values may be normal for order-line-level data. Review the repeated_order_id_detail sheet to confirm whether repeated IDs are expected line items or fully duplicated rows.
- Invalid date rows: 0.
- invalid_discount_policy: invalid or out-of-range discount_rate values are not used; affected discounted_revenue and final_revenue values are set to NA.
- Post-conversion checks found no issues.
- Expense post-conversion checks were skipped.

## Validation Results
- All 10 validation checks passed.
- invalid_date_excluded_revenue: $0.00.

## Finance Summary
- Expense data was not provided, so cash flow analysis was skipped.

## Anomaly Notes
- sales_drop_over_20_percent: Revenue dropped from $2,275.96 to $1,468.36.
- sales_drop_over_20_percent: Revenue dropped from $3,022.09 to $1,920.60.
- return_rate_over_15_percent: Monthly return rate was 20.0%.
- sales_drop_over_20_percent: Revenue dropped from $3,676.16 to $1,622.06.
- sales_drop_over_20_percent: Revenue dropped from $2,167.02 to $1,469.83.

## Method
- This summary is generated from the monthly, category, customer, product, finance, cash flow, and anomaly tables. It is written in a business-friendly style so it can later be replaced or enhanced with an LLM.