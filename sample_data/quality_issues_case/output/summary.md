# Sales Reporting Summary

## Report Status
- Status: failed.
- Reason: Critical data quality issues affect revenue calculations.

## Critical Data Quality Warning
- This report failed critical data quality checks. The business summary below is for diagnostic review only and should not be used for decision-making until the data issues are fixed.

## Executive Summary
- Total final revenue was $702.00.
- Total orders were 5, with 86 units sold.
- Overall AOV was $140.40.
- Discounts reduced gross revenue by $18.00, a 1.5% discount impact.
- The strongest month was 2026-03 with $360.00 in revenue.
- The weakest month was 2026-02 with $0.00 in revenue.
- The highest month-over-month growth was -100.0% in 2026-02.
- Revenue changed from $0.00 to $360.00 in 2026-03, so percentage growth is not meaningful.

## Diagnostic Business Summary
- Results in this section may be affected by data quality issues.
- Based on currently usable rows, top category: Beverage ($702.00).
- Based on currently usable rows, top customer: River Market ($360.00).
- Based on currently usable rows, top product: Green Tea ($360.00).
- Detected anomalies: 2.

## Data Quality Notes
- Required order columns were present.
- Duplicate rows: 0.
- Repeated order_id rows: 0.
- Repeated order_id values may be normal for order-line-level data.
- Invalid date rows: 1.
- Invalid date rows were excluded from monthly trend tables.
- Invalid returned values were treated as not returned for revenue calculation.
- invalid_discount_policy: invalid or out-of-range discount_rate values are not used; affected discounted_revenue and final_revenue values are set to NA.
- invalid_date_count: 1.
- invalid_unit_price_count: 1.
- discount_rate_out_of_range_count: 1.
- non_positive_quantity_count: 1.
- invalid_returned_count: 1.
- gross_revenue_isna_count: 2.
- discounted_revenue_isna_count: 3.
- final_revenue_isna_count: 3.
- invalid_revenue_row_count: 3.
- Invalid expense rows were excluded from finance summary and expense category breakdown.
- invalid_expense_date_count: 1.
- invalid_expense_amount_count: 1.
- negative_expense_amount_count: 1.
- expense_amount_isna_count: 1.

## Validation Results
- All 10 validation checks passed.
- invalid_date_excluded_revenue: $360.00.

## Finance Summary
- Total income was $702.00.
- Total expenses were $250.00.
- Net cash flow was $452.00.
- Profit margin was 64.4%.
- Largest expense category: Rent ($250.00).
- Strongest cash flow month: 2026-03 ($360.00).
- Weakest cash flow month: 2026-02 ($0.00).
- Cash flow warning months: 0.
- Rent was the largest expense category, representing 100.0% of expenses.

## Anomaly Notes
- sales_drop_over_20_percent: Revenue dropped from 342.00 to 0.00.
- discount_rate_over_30_percent: Product P005 had a 125.0% discount.

## Method
- This summary is generated from the monthly, category, customer, product, finance, cash flow, and anomaly tables. It is written in a business-friendly style so it can later be replaced or enhanced with an LLM.