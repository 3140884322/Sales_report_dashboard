# Sales Reporting Summary

## Report Status
- Status: ready.
- Reason: All validations passed and no data quality warnings were found.

## Executive Summary
- Total final revenue was $2,382.00.
- Total orders were 6, with 156 units sold.
- Overall AOV was $397.00.
- Discounts reduced gross revenue by $98.00, a 4.0% discount impact.
- The strongest month was 2026-02 with $892.50 in revenue.
- The weakest month was 2026-01 with $702.00 in revenue.
- The highest month-over-month growth was 27.1% in 2026-02.

## Business Insights
- top category: 食品 ($712.50).
- top customer: 春山咖啡 ($1,054.50).
- top product: 蛋白棒 ($712.50).
- Detected anomalies: 0.

## Data Quality Notes
- Required order columns were present.
- Duplicate rows: 0.
- Repeated order_id rows: 0.
- Repeated order_id values may be normal for order-line-level data.
- Invalid date rows: 0.
- invalid_discount_policy: invalid or out-of-range discount_rate values are not used; affected discounted_revenue and final_revenue values are set to NA.
- Post-conversion checks found no issues.
- Expense post-conversion checks found no issues.

## Validation Results
- All 10 validation checks passed.
- invalid_date_excluded_revenue: $0.00.

## Finance Summary
- Total income was $2,382.00.
- Total expenses were $1,250.00.
- Net cash flow was $1,132.00.
- Profit margin was 47.5%.
- Largest expense category: 租金 ($750.00).
- Strongest cash flow month: 2026-02 ($562.50).
- Weakest cash flow month: 2026-01 ($152.00).
- Cash flow warning months: 0.
- 租金 was the largest expense category, representing 60.0% of expenses.

## Anomaly Notes
- No anomalies were detected with the current rules.

## Method
- This summary is generated from the monthly, category, customer, product, finance, cash flow, and anomaly tables. It is written in a business-friendly style so it can later be replaced or enhanced with an LLM.