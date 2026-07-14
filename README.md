# AI-assisted Sales Reporting Automation

## Project Purpose

This project builds a beginner-friendly Python reporting pipeline for small
business sales and cash flow analysis. It reads order and expense CSV files,
checks data quality, calculates sales and finance metrics, validates summary
totals, exports a multi-sheet Excel report, and generates a Markdown business
summary.

The project is designed as a GitHub-ready starter project for AI-assisted sales
reporting automation.

## Application Flow

The Streamlit app has one **Upload Sales Data** entry for one or more CSV/XLSX
files. It profiles the uploaded tables before choosing the next step.

When one table is detected, the app selects it as the main transaction table,
creates a valid zero-relationship plan, and continues directly to standard
field mapping. When multiple tables are detected, the app discovers candidate
relationships and waits for the user to approve, edit, or reject them before
performing safe many-to-one merges. Both paths then use the same field mapping,
preflight, dashboard, Excel, and Markdown report flow.

## Input Files

Default input files:

```text
input/orders.csv
input/expenses.csv
```

Sample input files included in this repo draft:

```text
input/sample_orders.csv
input/sample_expenses.csv
input/sample_orders_zh.csv
input/sample_expenses_zh.csv
config/sample_column_mapping_zh.json
sample_data/clean_case/input/orders.csv
sample_data/clean_case/input/expenses.csv
sample_data/quality_issues_case/input/orders.csv
sample_data/quality_issues_case/input/expenses.csv
sample_data/mapped_columns_case/input/orders_chinese.csv
sample_data/mapped_columns_case/input/expenses_chinese.csv
sample_data/mapped_columns_case/config.json
```

The `_zh` files use Chinese column names and are intended to demonstrate the
optional column mapping config.

## Required Columns

These are the system standard column names after optional config mapping.

Orders file:

- `order_id`
- `date`
- `customer_id`
- `product_id`
- `unit_price`
- `quantity`
- `discount_rate`
- `returned`

In the Streamlit upload flow, `customer_id` is optional. When it is unavailable
or only partially provided, customer analysis is skipped without generating a
temporary customer identifier.

Optional order columns:

- `customer_name`
- `product_name`
- `category`

Expenses file:

- `expense_id`
- `date`
- `expense_category`
- `amount`

Optional expense columns:

- `vendor`
- `description`

## Column Mapping

Different customers often export sales and expense data from different systems.
One customer might use `order_id`, while another uses `订单编号`. The analysis
logic needs stable system standard fields, so `config.json` acts as a small
translation layer before the core calculations run.

If a user's CSV already uses the system standard column names, no config is
needed. If a user's CSV uses different column names, pass a JSON config with
`--config`. The config maps each system standard field to the column name found
in the user's CSV.

Config format:

```json
{
  "orders_columns": {
    "order_id": "订单编号",
    "date": "下单日期",
    "customer_id": "客户ID",
    "product_id": "商品编号",
    "unit_price": "单价",
    "quantity": "数量",
    "discount_rate": "折扣率",
    "returned": "是否退货",
    "category": "品类",
    "customer_name": "客户名称",
    "product_name": "商品名称"
  },
  "expenses_columns": {
    "expense_id": "费用编号",
    "date": "费用日期",
    "expense_category": "费用类别",
    "amount": "金额",
    "vendor": "供应商",
    "description": "描述"
  }
}
```

If a column listed in the config is not found in the CSV, the script stops with
a clear column mapping error. For optional fields that do not exist in a user's
file, remove that mapping from the config or leave its value blank.

Order standard fields:

- `order_id`: order or transaction identifier
- `date`: order date
- `customer_id`: customer identifier
- `product_id`: product identifier
- `unit_price`: price per unit before discount
- `quantity`: number of units sold
- `discount_rate`: discount as a decimal from `0` to `1`
- `returned`: whether the order line was returned
- `category`: product category
- `customer_name`: readable customer name
- `product_name`: readable product name

Expense standard fields:

- `expense_id`: expense transaction identifier
- `date`: expense date
- `expense_category`: expense category
- `amount`: expense amount
- `vendor`: supplier or payee name
- `description`: expense description

Run the mapped-column demo:

```bash
python analysis.py \
  --input sample_data/mapped_columns_case/input/orders_chinese.csv \
  --expenses sample_data/mapped_columns_case/input/expenses_chinese.csv \
  --config sample_data/mapped_columns_case/config.json \
  --excel sample_data/mapped_columns_case/output/sales_report.xlsx \
  --summary sample_data/mapped_columns_case/output/summary.md
```

## Generated Outputs

Sample generated outputs:

```text
output/sample_sales_report.xlsx
output/summary.md
```

The Excel report includes:

- `report_status`
- `data_quality`
- `duplicate_rows_detail`
- `repeated_order_id_detail`
- `post_conversion_quality`
- `validation_report`
- `enriched_orders`
- `monthly_summary`
- `category_summary`
- `customer_summary`
- `top_products`
- `anomalies`
- `finance_status`
- `expense_quality`
- `finance_kpis`
- `cash_flow_summary`
- `expense_categories`
- `largest_expenses`
- `cash_flow_warnings`
- `expenses_enriched`

## Metric Definitions

- `gross_revenue`: `unit_price * quantity`
- `discounted_revenue`: `gross_revenue * (1 - discount_rate)`
- `discount_amount`: `gross_revenue - discounted_revenue`
- `final_revenue`: discounted revenue after returns; returned rows become `0`
- `AOV`: revenue divided by order count
- `return_rate`: returned rows divided by total rows in a group
- `discount_impact_rate`: discount amount divided by gross revenue
- `revenue_growth_rate`: month-over-month revenue growth
- `monthly_income`: monthly sales revenue after returns
- `monthly_expenses`: total monthly expenses
- `net_cash_flow`: monthly income minus monthly expenses
- `profit_margin`: net cash flow divided by monthly income

## Data Quality Checks

Pre-conversion checks:

- required order columns
- missing values by column
- duplicate rows
- repeated `order_id` rows

Post-conversion order checks:

- invalid dates
- invalid prices, quantities, and discount rates
- discount rates outside `0` to `1`
- negative unit prices
- non-positive quantities
- invalid returned values
- missing revenue outputs
- invalid revenue rows

Expense quality checks:

- invalid expense dates
- invalid expense amounts
- negative expense amounts
- missing expense amounts

Data policies:

- Repeated `order_id` rows are informational only because order-line-level data
  may naturally repeat an order ID.
- Fully duplicated rows are not removed automatically. They are listed in
  `duplicate_rows_detail` because accidental duplicates may inflate revenue.
- Invalid dates are excluded from monthly trend tables.
- Invalid returned values are treated as not returned for revenue calculation,
  and are flagged in the data quality notes.
- Invalid or out-of-range `discount_rate` values are not used; affected
  `discounted_revenue`, `discount_amount`, and `final_revenue` are set to blank
  values.

## Validation Checks

The `validation_report` reconciles summary tables back to `enriched_orders`.

Monthly checks use only rows where `year_month` is not blank. Category and
customer checks use all enriched order rows.

Validation checks include:

- monthly final revenue equals valid-month enriched order final revenue
- monthly discounted revenue equals valid-month enriched order discounted revenue
- monthly gross revenue equals valid-month enriched order gross revenue
- monthly units equal valid-month enriched order units
- category final revenue equals enriched order final revenue
- category gross revenue equals enriched order gross revenue
- category units equal enriched order units
- customer final revenue equals enriched order final revenue
- customer gross revenue equals enriched order gross revenue
- customer units equal enriched order units
- `invalid_date_excluded_revenue` is reported as an informational item

## Report Status

The `report_status` sheet gives the overall readiness of the report:

- `ready`: validations passed and no data quality warnings exist
- `review_required`: warnings exist and should be reviewed
- `failed`: required columns are missing, validation fails, or critical revenue
  data quality issues exist

## How To Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run with default input paths:

```bash
python analysis.py
```

Run the included demo:

```bash
python analysis.py --input input/sample_orders.csv --expenses input/sample_expenses.csv --excel output/sample_sales_report.xlsx --summary output/summary.md
```

Run the Chinese-column demo with config mapping:

```bash
python analysis.py --input input/sample_orders_zh.csv --expenses input/sample_expenses_zh.csv --config config/sample_column_mapping_zh.json --excel output/sample_zh_sales_report.xlsx --summary output/summary_zh.md
```

Generate all demo outputs:

```bash
python generate_demo_outputs.py
```

Run the Streamlit report dashboard:

```bash
streamlit run app.py
```

The Streamlit app saves uploaded files in a temporary directory, calls the
existing `run_pipeline()` function, and shows the report directly in the page.
The dashboard is the recommended place to review the report before opening the
Excel file.

After clicking `Generate Report`, the page displays:

- Report Status with the reason: green for `ready`, yellow for
  `review_required`, and red for `failed`.
- KPI cards for total final revenue, order count, units, AOV, top category,
  top product, top customer, and anomaly count.
- `What happened?`, a plain-language processing summary showing uploaded rows,
  duplicate handling, final calculation rows, required-column status,
  validation status, and whether expenses were uploaded.
- `Action Required`, a review table for duplicate rows, skipped expense
  analysis, failed checks, and detected anomalies.
- `Business Insights`, including strongest month, weakest month, top category,
  top product, top customer, and anomaly count.
- Collapsed detail tables for monthly summary, category summary, top products,
  top customers, duplicate rows, anomalies, validation, and data quality checks.
- Download buttons for `sales_report.xlsx` and `summary.md`.

Excel output is still generated for audit, storage, and deeper analysis. The
dashboard is intended to prevent users from having to open many Excel sheets
just to understand the report.

When uploaded order columns do not match the system standard names, the app
shows the uploaded CSV columns and a `Column Mapping` section. Users can map
missing required fields, such as `date` or `product_id`, by selecting the real
CSV column from dropdowns. Uploading `config.json` is still available as an
advanced option, but it is no longer required for ordinary column mapping.

If fully duplicated order rows are found, the app shows a `Duplicate Row Review`
section before report generation. It shows duplicate group count, involved row
count, `source_row_number`, and the full original uploaded row data. Users can
keep all rows or select specific `source_row_number` values to remove from the
temporary report input. The uploaded file itself is not changed, and
`duplicate_rows_detail` keeps the original duplicate details for traceability.

## Demo Output Description

The project includes three demo cases:

- `clean_case`: clean standard-column data; expected to produce a `ready`
  report.
- `quality_issues_case`: standard-column data with invalid dates, invalid
  amounts, invalid discount rate, non-positive quantity, and invalid returned
  values; expected to produce a report that requires review or fails depending
  on the severity of the issues.
- `mapped_columns_case`: Chinese-column input files plus `config.json`; expected
  to produce the same style of output as standard-column data after mapping.

The original sample report uses 20 sample order rows and 24 sample expense rows.
It produces a `ready` report status, monthly revenue and cash flow summaries,
category/customer/product analysis, anomaly notes, finance KPIs, and validation
results.

In the sample output:

- total final revenue is `$6,434.75`
- total expenses are `$5,390.00`
- net cash flow is `$1,044.75`
- all 10 validation checks pass
- post-conversion order and expense quality checks pass

## AI Usage

The current `summary.md` is generated from structured report tables using
rule-based text. The project is designed so this step can later be replaced or
enhanced with an LLM call while keeping the same tables and validation logic.

## Limitations And Next Steps

Limitations:

- The summary is rule-based and not yet connected to an external LLM API.
- Return rate is row-based.
- Column mapping currently maps column names only; value normalization is still
  handled by the analysis rules.
- Expense logic is cash-based, not accrual accounting.
- The project does not yet include balance sheet items, receivables, or payables.
- The Streamlit interface is intentionally minimal and does not include user
  accounts, payments, persistent storage, or dashboard charts.

Next steps:

- Add richer Streamlit previews and charts
- Add charts to the Excel workbook
- Add LLM-generated executive summaries
- Add product margin and profit analysis
- Add accounts receivable and accounts payable aging
- Add cash runway and burn rate analysis
