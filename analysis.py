import json
from argparse import ArgumentParser
from pathlib import Path

import pandas as pd
from openpyxl.utils import get_column_letter


PROJECT_DIR = Path(__file__).parent
DEFAULT_INPUT = "input/orders.csv"
DEFAULT_EXPENSES_INPUT = "input/expenses.csv"
DEFAULT_EXCEL_OUTPUT = "output/sales_report.xlsx"
DEFAULT_SUMMARY_OUTPUT = "output/summary.md"

REQUIRED_COLUMNS = [
    "order_id",
    "date",
    "customer_id",
    "product_id",
    "unit_price",
    "quantity",
    "discount_rate",
    "returned",
]

EXPENSE_REQUIRED_COLUMNS = [
    "expense_id",
    "date",
    "expense_category",
    "amount",
]

VALIDATION_TOLERANCE = 0.01

DUPLICATE_ROWS_DETAIL_COLUMNS = [
    "duplicate_group_id",
    "source_row_number",
    "duplicate_group_count",
    "duplicate_row_count",
]

REPEATED_ORDER_ID_DETAIL_COLUMNS = [
    "order_id",
    "occurrence_count",
    "source_row_numbers",
    "rows_are_fully_identical",
    "note",
]


def get_file_path(file_path):
    """Return an absolute path inside this project when a relative path is given."""
    path = Path(file_path)

    if not path.is_absolute():
        path = PROJECT_DIR / path

    return path


def load_column_mapping(config_path=None):
    """Load an optional JSON config that maps user CSV columns to standard names."""
    empty_mapping = {"orders_columns": {}, "expenses_columns": {}}

    if not config_path:
        return empty_mapping

    file_path = get_file_path(config_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Could not find the config file: {file_path}")

    if file_path.suffix.lower() != ".json":
        raise ValueError(
            "Column mapping config currently supports JSON files. "
            "Please provide a .json config file."
        )

    with file_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    if not isinstance(config, dict):
        raise ValueError("Column mapping config must be a JSON object.")

    orders_mapping = config.get("orders_columns", {}) or {}
    expenses_mapping = config.get("expenses_columns", {}) or {}

    if not isinstance(orders_mapping, dict):
        raise ValueError("orders_columns in the config must be a JSON object.")

    if not isinstance(expenses_mapping, dict):
        raise ValueError("expenses_columns in the config must be a JSON object.")

    return {
        "orders_columns": orders_mapping,
        "expenses_columns": expenses_mapping,
    }


def apply_column_mapping(df, mapping):
    """Rename user CSV columns to the system's standard column names."""
    if not mapping:
        return df.copy()

    if not isinstance(mapping, dict):
        raise ValueError("Column mapping must be a dictionary.")

    rename_columns = {}
    mapped_source_columns = []
    missing_mappings = []
    target_conflicts = []

    for standard_column, source_column in mapping.items():
        if source_column is None or source_column == "":
            continue

        source_column = str(source_column)
        mapped_source_columns.append(source_column)

        if source_column not in df.columns:
            missing_mappings.append(f"{source_column} -> {standard_column}")
            continue

        if source_column != standard_column and standard_column in df.columns:
            target_conflicts.append(f"{source_column} -> {standard_column}")
            continue

        rename_columns[source_column] = standard_column

    duplicate_source_columns = sorted(
        {
            column
            for column in mapped_source_columns
            if mapped_source_columns.count(column) > 1
        }
    )

    if duplicate_source_columns:
        raise ValueError(
            "Column mapping error: one CSV column is mapped to multiple "
            f"standard fields: {', '.join(duplicate_source_columns)}"
        )

    if missing_mappings:
        found_text = ", ".join(df.columns)
        missing_text = ", ".join(missing_mappings)
        raise ValueError(
            "Column mapping error: configured CSV column(s) were not found.\n"
            f"Missing mappings: {missing_text}\n"
            f"Columns found in file: {found_text}"
        )

    if target_conflicts:
        conflicts_text = ", ".join(target_conflicts)
        raise ValueError(
            "Column mapping error: the target standard column already exists "
            f"while another CSV column is mapped to it: {conflicts_text}"
        )

    return df.rename(columns=rename_columns)


def divide_safely(numerator, denominator):
    """Divide values and return 0 when the denominator is 0."""
    if hasattr(denominator, "where"):
        safe_denominator = denominator.where(denominator != 0)

        return (numerator / safe_denominator).fillna(0)

    if pd.isna(denominator) or denominator == 0:
        return 0

    return numerator / denominator


def read_orders_csv(csv_path=DEFAULT_INPUT):
    """Read the orders CSV file with pandas."""
    file_path = get_file_path(csv_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Could not find the file: {file_path}\n"
            "Please make sure input/orders.csv exists before running this script."
        )

    return pd.read_csv(file_path)


def check_required_columns(orders):
    """Return a list of required columns that are missing."""
    missing_columns = []

    for column in REQUIRED_COLUMNS:
        if column not in orders.columns:
            missing_columns.append(column)

    return missing_columns


def make_column_error_message(missing_columns, found_columns):
    """Create a clear error message for missing columns."""
    missing_text = ", ".join(missing_columns)
    required_text = ", ".join(REQUIRED_COLUMNS)
    found_text = ", ".join(found_columns)

    return (
        f"orders.csv is missing required column(s): {missing_text}\n"
        f"Required columns: {required_text}\n"
        f"Columns found in file: {found_text}"
    )


def load_orders(csv_path=DEFAULT_INPUT, column_mapping=None):
    """Read the orders CSV file and stop if required columns are missing."""
    orders = read_orders_csv(csv_path)
    orders_mapping = (column_mapping or {}).get("orders_columns", {})
    orders = apply_column_mapping(orders, orders_mapping)
    missing_columns = check_required_columns(orders)

    if missing_columns:
        raise ValueError(make_column_error_message(missing_columns, orders.columns))

    return orders


def add_source_row_number(orders):
    """Add the original CSV row number without changing calculation columns."""
    prepared = orders.copy()

    if "source_row_number" not in prepared.columns:
        prepared.insert(0, "source_row_number", prepared.index + 2)

    return prepared


def create_data_quality_report(csv_path=DEFAULT_INPUT, column_mapping=None):
    """Read the CSV file and return a simple data quality report."""
    file_path = get_file_path(csv_path)
    orders = read_orders_csv(csv_path)
    orders_mapping = (column_mapping or {}).get("orders_columns", {})
    orders = apply_column_mapping(orders, orders_mapping)
    missing_columns = check_required_columns(orders)

    data_quality_report = {
        "file_path": str(file_path),
        "row_count": len(orders),
        "column_count": len(orders.columns),
        "columns_found": list(orders.columns),
        "missing_required_columns": missing_columns,
        "missing_values_by_column": orders.isna().sum().to_dict(),
        "duplicate_rows": int(orders.duplicated().sum()),
        "duplicate_order_ids": None,
        "repeated_order_id_rows": None,
    }

    if "order_id" in orders.columns:
        repeated_order_id_rows = int(
            orders["order_id"].duplicated().sum()
        )
        data_quality_report["duplicate_order_ids"] = repeated_order_id_rows
        data_quality_report["repeated_order_id_rows"] = repeated_order_id_rows

    if missing_columns:
        data_quality_report["status"] = "failed"
        data_quality_report["error_message"] = make_column_error_message(
            missing_columns,
            orders.columns,
        )
    else:
        data_quality_report["status"] = "passed"
        data_quality_report["error_message"] = ""

    return data_quality_report


def normalize_returned(value):
    """Convert known returned values to True or False, and unknown values to NA."""
    if pd.isna(value):
        return pd.NA

    text = str(value).strip().lower()

    if text in ["true", "yes", "y", "1", "returned"]:
        return True

    if text in ["false", "no", "n", "0", "", "not_returned"]:
        return False

    return pd.NA


def calculate_revenue_metrics(orders):
    """Add revenue columns and year_month to the orders table."""
    prepared = orders.copy()

    prepared["date"] = pd.to_datetime(
        prepared["date"],
        errors="coerce",
        format="mixed",
    )
    prepared["unit_price"] = pd.to_numeric(prepared["unit_price"], errors="coerce")
    prepared["quantity"] = pd.to_numeric(prepared["quantity"], errors="coerce")
    prepared["discount_rate"] = pd.to_numeric(
        prepared["discount_rate"],
        errors="coerce",
    )
    prepared["returned"] = prepared["returned"].apply(normalize_returned).astype(
        "boolean"
    )

    if "category" not in prepared.columns:
        prepared["category"] = "Unknown"

    if "customer_name" not in prepared.columns:
        prepared["customer_name"] = prepared["customer_id"]

    if "product_name" not in prepared.columns:
        prepared["product_name"] = prepared["product_id"]

    invalid_price_or_quantity = (
        prepared["unit_price"].isna()
        | prepared["quantity"].isna()
        | (prepared["unit_price"] < 0)
        | (prepared["quantity"] <= 0)
    )
    invalid_discount_rate = (
        prepared["discount_rate"].isna()
        | (prepared["discount_rate"] < 0)
        | (prepared["discount_rate"] > 1)
    )

    prepared["gross_revenue"] = prepared["unit_price"] * prepared["quantity"]
    prepared.loc[invalid_price_or_quantity, "gross_revenue"] = pd.NA

    prepared["discounted_revenue"] = prepared["gross_revenue"] * (
        1 - prepared["discount_rate"]
    )
    prepared["discount_amount"] = (
        prepared["gross_revenue"] - prepared["discounted_revenue"]
    )
    prepared["final_revenue"] = prepared["discounted_revenue"]
    returned_mask = prepared["returned"].fillna(False).astype(bool)
    prepared.loc[returned_mask, "final_revenue"] = 0
    prepared.loc[
        invalid_price_or_quantity | invalid_discount_rate,
        ["discounted_revenue", "discount_amount", "final_revenue"],
    ] = pd.NA
    prepared["year_month"] = prepared["date"].dt.to_period("M").astype("string")
    prepared.loc[prepared["date"].isna(), "year_month"] = pd.NA

    return prepared


def count_true(condition):
    """Count True values in a pandas boolean Series."""
    return int(condition.fillna(False).sum())


def make_post_conversion_data_quality_report(enriched_orders):
    """Check data quality after type conversion and revenue calculations."""
    checks = [
        {
            "check_name": "invalid_date_count",
            "issue_count": int(enriched_orders["date"].isna().sum()),
        },
        {
            "check_name": "invalid_unit_price_count",
            "issue_count": int(enriched_orders["unit_price"].isna().sum()),
        },
        {
            "check_name": "invalid_quantity_count",
            "issue_count": int(enriched_orders["quantity"].isna().sum()),
        },
        {
            "check_name": "invalid_discount_rate_count",
            "issue_count": int(enriched_orders["discount_rate"].isna().sum()),
        },
        {
            "check_name": "discount_rate_out_of_range_count",
            "issue_count": count_true(
                (enriched_orders["discount_rate"] < 0)
                | (enriched_orders["discount_rate"] > 1)
            ),
        },
        {
            "check_name": "negative_unit_price_count",
            "issue_count": count_true(enriched_orders["unit_price"] < 0),
        },
        {
            "check_name": "non_positive_quantity_count",
            "issue_count": count_true(enriched_orders["quantity"] <= 0),
        },
        {
            "check_name": "invalid_returned_count",
            "issue_count": int(enriched_orders["returned"].isna().sum()),
        },
        {
            "check_name": "gross_revenue_isna_count",
            "issue_count": int(enriched_orders["gross_revenue"].isna().sum()),
        },
        {
            "check_name": "discounted_revenue_isna_count",
            "issue_count": int(enriched_orders["discounted_revenue"].isna().sum()),
        },
        {
            "check_name": "final_revenue_isna_count",
            "issue_count": int(enriched_orders["final_revenue"].isna().sum()),
        },
        {
            "check_name": "invalid_revenue_row_count",
            "issue_count": int(
                enriched_orders[
                    [
                        "gross_revenue",
                        "discounted_revenue",
                        "final_revenue",
                    ]
                ]
                .isna()
                .any(axis=1)
                .sum()
            ),
        },
    ]

    for check in checks:
        check["status"] = "passed" if check["issue_count"] == 0 else "warning"

    return pd.DataFrame(checks)


def make_summary_table(orders, group_columns):
    """Create a reusable revenue summary table."""
    summary = (
        orders.groupby(group_columns)
        .agg(
            gross_revenue=("gross_revenue", "sum"),
            discount_amount=("discount_amount", "sum"),
            discounted_revenue=("discounted_revenue", "sum"),
            revenue=("final_revenue", "sum"),
            orders=("order_id", "nunique"),
            units=("quantity", "sum"),
            return_rate=("returned", "mean"),
            average_discount_rate=("discount_rate", "mean"),
        )
        .reset_index()
    )

    summary["AOV"] = divide_safely(summary["revenue"], summary["orders"])
    summary["discount_impact_rate"] = divide_safely(
        summary["discount_amount"],
        summary["gross_revenue"],
    )
    summary = summary.sort_values("revenue", ascending=False)

    return summary


def make_monthly_summary(orders):
    """Group by month and calculate sales metrics and revenue growth."""
    valid_month_orders = orders[orders["year_month"].notna()].copy()
    monthly_summary = make_summary_table(valid_month_orders, ["year_month"])
    monthly_summary = monthly_summary.sort_values("year_month")
    monthly_summary["previous_revenue"] = monthly_summary["revenue"].shift(1)
    monthly_summary["revenue_growth_amount"] = (
        monthly_summary["revenue"] - monthly_summary["previous_revenue"]
    )
    monthly_summary["revenue_growth_rate"] = monthly_summary["revenue"].pct_change()

    return monthly_summary[
        [
            "year_month",
            "gross_revenue",
            "discount_amount",
            "discounted_revenue",
            "revenue",
            "orders",
            "units",
            "AOV",
            "return_rate",
            "average_discount_rate",
            "discount_impact_rate",
            "previous_revenue",
            "revenue_growth_amount",
            "revenue_growth_rate",
        ]
    ]


def make_category_summary(orders):
    """Group by category and calculate core sales metrics."""
    return make_summary_table(orders, ["category"])


def make_customer_summary(orders):
    """Group by customer and calculate core sales metrics."""
    return make_summary_table(orders, ["customer_id", "customer_name"])


def find_top_products(orders, top_n=10):
    """Find the top products by final revenue."""
    product_summary = make_summary_table(
        orders,
        ["product_id", "product_name", "category"],
    )

    return product_summary.head(top_n)


def make_validation_row(check_name, expected_value, actual_value):
    """Create one validation row with a pass/fail status."""
    difference = actual_value - expected_value
    status = "passed" if abs(difference) <= VALIDATION_TOLERANCE else "failed"

    return {
        "check_name": check_name,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "difference": difference,
        "status": status,
    }


def make_validation_report(
    enriched_orders,
    monthly_summary,
    category_summary,
    customer_summary,
):
    """Check that summary tables reconcile back to enriched order details."""
    valid_month_orders = enriched_orders[enriched_orders["year_month"].notna()]
    expected_monthly_final_revenue = valid_month_orders["final_revenue"].sum()
    expected_monthly_gross_revenue = valid_month_orders["gross_revenue"].sum()
    expected_monthly_discounted_revenue = valid_month_orders[
        "discounted_revenue"
    ].sum()
    expected_monthly_units = valid_month_orders["quantity"].sum()
    expected_final_revenue = enriched_orders["final_revenue"].sum()
    expected_gross_revenue = enriched_orders["gross_revenue"].sum()
    expected_units = enriched_orders["quantity"].sum()
    invalid_date_excluded_revenue = enriched_orders.loc[
        enriched_orders["year_month"].isna(),
        "final_revenue",
    ].sum()

    rows = [
        make_validation_row(
            "monthly_summary_revenue_equals_enriched_orders_final_revenue",
            expected_monthly_final_revenue,
            monthly_summary["revenue"].sum(),
        ),
        make_validation_row(
            "monthly_discounted_revenue_equals_enriched_orders_discounted_revenue",
            expected_monthly_discounted_revenue,
            monthly_summary["discounted_revenue"].sum(),
        ),
        make_validation_row(
            "category_summary_revenue_equals_enriched_orders_final_revenue",
            expected_final_revenue,
            category_summary["revenue"].sum(),
        ),
        make_validation_row(
            "customer_summary_revenue_equals_enriched_orders_final_revenue",
            expected_final_revenue,
            customer_summary["revenue"].sum(),
        ),
        make_validation_row(
            "monthly_gross_revenue_equals_enriched_orders_gross_revenue",
            expected_monthly_gross_revenue,
            monthly_summary["gross_revenue"].sum(),
        ),
        make_validation_row(
            "category_gross_revenue_equals_enriched_orders_gross_revenue",
            expected_gross_revenue,
            category_summary["gross_revenue"].sum(),
        ),
        make_validation_row(
            "customer_gross_revenue_equals_enriched_orders_gross_revenue",
            expected_gross_revenue,
            customer_summary["gross_revenue"].sum(),
        ),
        make_validation_row(
            "monthly_units_equals_enriched_orders_units",
            expected_monthly_units,
            monthly_summary["units"].sum(),
        ),
        make_validation_row(
            "category_units_equals_enriched_orders_units",
            expected_units,
            category_summary["units"].sum(),
        ),
        make_validation_row(
            "customer_units_equals_enriched_orders_units",
            expected_units,
            customer_summary["units"].sum(),
        ),
        {
            "check_name": "invalid_date_excluded_revenue",
            "expected_value": 0,
            "actual_value": invalid_date_excluded_revenue,
            "difference": invalid_date_excluded_revenue,
            "status": "info",
        },
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "check_name",
            "expected_value",
            "actual_value",
            "difference",
            "status",
        ],
    )


def get_quality_issue_count(post_conversion_quality, check_name):
    """Return the issue count for one post-conversion quality check."""
    matches = post_conversion_quality[
        post_conversion_quality["check_name"] == check_name
    ]

    if matches.empty:
        return 0

    return int(matches.iloc[0]["issue_count"])


def make_report_status_table(
    data_quality_report,
    post_conversion_quality,
    validation_report,
    expense_post_conversion_quality=None,
):
    """Create the overall report status table."""
    critical_check_names = [
        "invalid_unit_price_count",
        "invalid_quantity_count",
        "invalid_discount_rate_count",
        "discount_rate_out_of_range_count",
        "negative_unit_price_count",
        "non_positive_quantity_count",
        "gross_revenue_isna_count",
        "discounted_revenue_isna_count",
        "final_revenue_isna_count",
        "invalid_revenue_row_count",
    ]
    warning_check_names = [
        "invalid_date_count",
        "invalid_returned_count",
    ]

    missing_required_columns = len(data_quality_report["missing_required_columns"])
    validation_failed_count = int((validation_report["status"] == "failed").sum())
    critical_issue_count = 0

    for check_name in critical_check_names:
        critical_issue_count += get_quality_issue_count(
            post_conversion_quality,
            check_name,
        )

    warning_count = 0

    for check_name in warning_check_names:
        warning_count += get_quality_issue_count(post_conversion_quality, check_name)

    if expense_post_conversion_quality is not None:
        warning_count += int(expense_post_conversion_quality["issue_count"].sum())

    if data_quality_report["duplicate_rows"]:
        warning_count += int(data_quality_report["duplicate_rows"])

    if missing_required_columns:
        status = "failed"
        reason = "Required columns are missing."
    elif validation_failed_count:
        status = "failed"
        reason = "One or more validation checks failed."
    elif critical_issue_count:
        status = "failed"
        reason = "Critical data quality issues affect revenue calculations."
    elif warning_count:
        status = "review_required"
        reason = "Warnings exist and should be reviewed."
    else:
        status = "ready"
        reason = "All validations passed and no data quality warnings were found."

    return pd.DataFrame(
        [
            {
                "status": status,
                "reason": reason,
                "missing_required_columns": missing_required_columns,
                "validation_failed_count": validation_failed_count,
                "critical_issue_count": critical_issue_count,
                "warning_count": warning_count,
            }
        ]
    )


def read_expenses_csv(expenses_path=DEFAULT_EXPENSES_INPUT):
    """Read the expenses CSV file if it exists."""
    file_path = get_file_path(expenses_path)

    if not file_path.exists():
        return None

    return pd.read_csv(file_path)


def check_expense_required_columns(expenses):
    """Return a list of required expense columns that are missing."""
    missing_columns = []

    for column in EXPENSE_REQUIRED_COLUMNS:
        if column not in expenses.columns:
            missing_columns.append(column)

    return missing_columns


def make_expense_column_error_message(missing_columns, found_columns):
    """Create a clear error message for missing expense columns."""
    missing_text = ", ".join(missing_columns)
    required_text = ", ".join(EXPENSE_REQUIRED_COLUMNS)
    found_text = ", ".join(found_columns)

    return (
        f"expenses.csv is missing required column(s): {missing_text}\n"
        f"Required columns: {required_text}\n"
        f"Columns found in file: {found_text}"
    )


def load_expenses(expenses_path=DEFAULT_EXPENSES_INPUT, column_mapping=None):
    """Read the expenses CSV file and stop if required columns are missing."""
    expenses = read_expenses_csv(expenses_path)

    if expenses is None:
        return None

    expenses_mapping = (column_mapping or {}).get("expenses_columns", {})
    expenses = apply_column_mapping(expenses, expenses_mapping)
    missing_columns = check_expense_required_columns(expenses)

    if missing_columns:
        raise ValueError(
            make_expense_column_error_message(missing_columns, expenses.columns)
        )

    return expenses


def prepare_expenses(expenses):
    """Clean expense data and add year_month."""
    prepared = expenses.copy()

    prepared["date"] = pd.to_datetime(
        prepared["date"],
        errors="coerce",
        format="mixed",
    )
    prepared["amount"] = pd.to_numeric(prepared["amount"], errors="coerce")
    prepared["expense_category"] = prepared["expense_category"].fillna("Unknown")
    prepared["year_month"] = prepared["date"].dt.to_period("M").astype("string")
    prepared.loc[prepared["date"].isna(), "year_month"] = pd.NA

    if "vendor" not in prepared.columns:
        prepared["vendor"] = ""

    if "description" not in prepared.columns:
        prepared["description"] = ""

    return prepared


def make_expense_post_conversion_quality_report(expenses):
    """Check expense data quality after type conversion."""
    checks = [
        {
            "check_name": "invalid_expense_date_count",
            "issue_count": int(expenses["date"].isna().sum()),
        },
        {
            "check_name": "invalid_expense_amount_count",
            "issue_count": int(expenses["amount"].isna().sum()),
        },
        {
            "check_name": "negative_expense_amount_count",
            "issue_count": count_true(expenses["amount"] < 0),
        },
        {
            "check_name": "expense_amount_isna_count",
            "issue_count": int(expenses["amount"].isna().sum()),
        },
    ]

    for check in checks:
        check["status"] = "passed" if check["issue_count"] == 0 else "warning"

    return pd.DataFrame(checks)


def make_finance_status_table(expenses_path, status, message, expenses=None):
    """Create a small table that explains whether finance data was usable."""
    rows = [
        {"metric": "expenses_file", "value": str(get_file_path(expenses_path))},
        {"metric": "finance_module_status", "value": status},
        {"metric": "message", "value": message},
    ]

    if expenses is not None:
        rows.extend(
            [
                {"metric": "expense_rows", "value": len(expenses)},
                {"metric": "expense_columns", "value": len(expenses.columns)},
                {
                    "metric": "expense_missing_values",
                    "value": int(expenses.isna().sum().sum()),
                },
                {
                    "metric": "duplicate_expense_ids",
                    "value": int(expenses["expense_id"].duplicated().sum()),
                },
            ]
        )

    return pd.DataFrame(rows)


def make_empty_finance_tables(expenses_path):
    """Return empty finance tables when no expense file is provided."""
    finance_status = make_finance_status_table(
        expenses_path,
        "skipped",
        "No expenses CSV file was found, so cash flow analysis was skipped.",
    )

    return {
        "finance_status": finance_status,
        "expense_post_conversion_quality": pd.DataFrame(
            columns=["check_name", "issue_count", "status"]
        ),
        "finance_kpis": pd.DataFrame(columns=["metric", "value"]),
        "expenses_enriched": pd.DataFrame(
            columns=[
                "expense_id",
                "date",
                "expense_category",
                "amount",
                "vendor",
                "description",
                "year_month",
            ]
        ),
        "cash_flow_summary": pd.DataFrame(
            columns=[
                "year_month",
                "monthly_income",
                "monthly_expenses",
                "net_cash_flow",
                "profit_margin",
                "previous_net_cash_flow",
                "net_cash_flow_change_amount",
                "net_cash_flow_change_rate",
                "income_change_rate",
                "expense_change_rate",
                "cash_flow_warning",
            ]
        ),
        "expense_category_breakdown": pd.DataFrame(
            columns=[
                "expense_category",
                "total_expense",
                "expense_count",
                "average_expense_amount",
                "share_of_expenses",
            ]
        ),
        "largest_expense_categories": pd.DataFrame(
            columns=[
                "expense_category",
                "total_expense",
                "expense_count",
                "average_expense_amount",
                "share_of_expenses",
            ]
        ),
        "cash_flow_warnings": pd.DataFrame(
            columns=["year_month", "warning_type", "details"]
        ),
    }


def make_cash_flow_warning(row):
    """Create a readable warning label for a monthly cash flow row."""
    warnings = []

    if row["monthly_income"] <= 0 and row["monthly_expenses"] > 0:
        warnings.append("no_income_with_expenses")

    if row["net_cash_flow"] < 0:
        warnings.append("negative_cash_flow")

    if row["monthly_income"] > 0 and row["profit_margin"] < 0.10:
        warnings.append("low_profit_margin")

    if (
        row["previous_monthly_expenses"] > 0
        and row["expense_change_rate"] > 0.20
    ):
        warnings.append("expenses_up_over_20_percent")

    if not warnings:
        return "ok"

    return "; ".join(warnings)


def make_cash_flow_warnings(cash_flow_summary):
    """Create one row per cash flow warning."""
    warning_rows = []

    for _, row in cash_flow_summary.iterrows():
        if row["cash_flow_warning"] == "ok":
            continue

        for warning_type in row["cash_flow_warning"].split("; "):
            warning_rows.append(
                {
                    "year_month": row["year_month"],
                    "warning_type": warning_type,
                    "details": (
                        f"Income {format_money(row['monthly_income'])}, expenses "
                        f"{format_money(row['monthly_expenses'])}, net cash flow "
                        f"{format_money(row['net_cash_flow'])}."
                    ),
                }
            )

    return pd.DataFrame(
        warning_rows,
        columns=["year_month", "warning_type", "details"],
    )


def get_valid_expenses_for_finance(expenses):
    """Return expense rows that are safe to include in finance summaries."""
    return expenses[
        expenses["year_month"].notna()
        & expenses["amount"].notna()
        & (expenses["amount"] >= 0)
    ].copy()


def make_expense_category_breakdown(expenses):
    """Summarize expenses by category."""
    valid_expenses = get_valid_expenses_for_finance(expenses)
    category_summary = (
        valid_expenses.groupby("expense_category")
        .agg(
            total_expense=("amount", "sum"),
            expense_count=("expense_id", "nunique"),
            average_expense_amount=("amount", "mean"),
        )
        .reset_index()
    )
    total_expense = category_summary["total_expense"].sum()

    if total_expense:
        category_summary["share_of_expenses"] = (
            category_summary["total_expense"] / total_expense
        )
    else:
        category_summary["share_of_expenses"] = 0

    return category_summary.sort_values("total_expense", ascending=False)


def make_cash_flow_summary(monthly_summary, expenses):
    """Combine monthly income and monthly expenses into a cash flow table."""
    monthly_income = monthly_summary[["year_month", "revenue"]].rename(
        columns={"revenue": "monthly_income"}
    )
    valid_expenses = get_valid_expenses_for_finance(expenses)
    monthly_expenses = (
        valid_expenses.groupby("year_month")
        .agg(monthly_expenses=("amount", "sum"))
        .reset_index()
    )

    cash_flow = monthly_income.merge(monthly_expenses, on="year_month", how="outer")
    cash_flow = cash_flow.sort_values("year_month")
    cash_flow["monthly_income"] = cash_flow["monthly_income"].fillna(0)
    cash_flow["monthly_expenses"] = cash_flow["monthly_expenses"].fillna(0)
    cash_flow["net_cash_flow"] = (
        cash_flow["monthly_income"] - cash_flow["monthly_expenses"]
    )
    cash_flow["profit_margin"] = divide_safely(
        cash_flow["net_cash_flow"],
        cash_flow["monthly_income"],
    )
    cash_flow["previous_net_cash_flow"] = cash_flow["net_cash_flow"].shift(1)
    cash_flow["net_cash_flow_change_amount"] = (
        cash_flow["net_cash_flow"] - cash_flow["previous_net_cash_flow"]
    )
    cash_flow["net_cash_flow_change_rate"] = divide_safely(
        cash_flow["net_cash_flow_change_amount"],
        cash_flow["previous_net_cash_flow"],
    )
    cash_flow["previous_monthly_income"] = cash_flow["monthly_income"].shift(1)
    cash_flow["income_change_rate"] = divide_safely(
        cash_flow["monthly_income"] - cash_flow["previous_monthly_income"],
        cash_flow["previous_monthly_income"],
    )
    cash_flow["previous_monthly_expenses"] = cash_flow["monthly_expenses"].shift(1)
    cash_flow["expense_change_rate"] = divide_safely(
        cash_flow["monthly_expenses"] - cash_flow["previous_monthly_expenses"],
        cash_flow["previous_monthly_expenses"],
    )
    cash_flow["cash_flow_warning"] = cash_flow.apply(make_cash_flow_warning, axis=1)

    return cash_flow[
        [
            "year_month",
            "monthly_income",
            "monthly_expenses",
            "net_cash_flow",
            "profit_margin",
            "previous_net_cash_flow",
            "net_cash_flow_change_amount",
            "net_cash_flow_change_rate",
            "income_change_rate",
            "expense_change_rate",
            "cash_flow_warning",
        ]
    ]


def make_finance_kpis(cash_flow_summary, expense_category_breakdown):
    """Create a compact KPI table for finance summary metrics."""
    total_income = cash_flow_summary["monthly_income"].sum()
    total_expenses = cash_flow_summary["monthly_expenses"].sum()
    net_cash_flow = total_income - total_expenses
    profit_margin = net_cash_flow / total_income if total_income else 0
    warning_months = int((cash_flow_summary["cash_flow_warning"] != "ok").sum())

    if expense_category_breakdown.empty:
        largest_category = ""
        largest_category_expense = 0
    else:
        largest_category = expense_category_breakdown.iloc[0]["expense_category"]
        largest_category_expense = expense_category_breakdown.iloc[0]["total_expense"]

    rows = [
        {"metric": "total_income", "value": total_income},
        {"metric": "total_expenses", "value": total_expenses},
        {"metric": "net_cash_flow", "value": net_cash_flow},
        {"metric": "profit_margin", "value": profit_margin},
        {"metric": "warning_months", "value": warning_months},
        {"metric": "largest_expense_category", "value": largest_category},
        {"metric": "largest_expense_category_amount", "value": largest_category_expense},
    ]

    return pd.DataFrame(rows)


def build_finance_report(
    monthly_summary,
    expenses_path=DEFAULT_EXPENSES_INPUT,
    column_mapping=None,
):
    """Build the cash flow and finance summary module."""
    expenses = load_expenses(expenses_path, column_mapping)

    if expenses is None:
        return make_empty_finance_tables(expenses_path)

    expenses_enriched = prepare_expenses(expenses)
    expense_post_conversion_quality = make_expense_post_conversion_quality_report(
        expenses_enriched
    )
    finance_status = make_finance_status_table(
        expenses_path,
        "passed",
        "Expenses CSV file loaded successfully.",
        expenses,
    )
    cash_flow_summary = make_cash_flow_summary(monthly_summary, expenses_enriched)
    expense_category_breakdown = make_expense_category_breakdown(expenses_enriched)
    largest_expense_categories = expense_category_breakdown.head(5)
    cash_flow_warnings = make_cash_flow_warnings(cash_flow_summary)
    finance_kpis = make_finance_kpis(
        cash_flow_summary,
        expense_category_breakdown,
    )

    return {
        "finance_status": finance_status,
        "expense_post_conversion_quality": expense_post_conversion_quality,
        "finance_kpis": finance_kpis,
        "expenses_enriched": expenses_enriched,
        "cash_flow_summary": cash_flow_summary,
        "expense_category_breakdown": expense_category_breakdown,
        "largest_expense_categories": largest_expense_categories,
        "cash_flow_warnings": cash_flow_warnings,
    }


def detect_anomalies(orders, monthly_summary):
    """Find sales drops, high return rates, and high discount rates."""
    anomaly_rows = []
    monthly = monthly_summary.sort_values("year_month").copy()

    if "previous_revenue" not in monthly.columns:
        monthly["previous_revenue"] = monthly["revenue"].shift(1)

    if "revenue_growth_rate" not in monthly.columns:
        monthly["revenue_growth_rate"] = monthly["revenue"].pct_change()

    for _, row in monthly.iterrows():
        change_rate = row["revenue_growth_rate"]

        if pd.notna(change_rate) and change_rate <= -0.20:
            anomaly_rows.append(
                {
                    "anomaly_type": "sales_drop_over_20_percent",
                    "level": "month",
                    "period": row["year_month"],
                    "order_id": "",
                    "metric_value": change_rate,
                    "threshold": -0.20,
                    "details": (
                        f"Revenue dropped from "
                        f"{format_money(row['previous_revenue'])} to "
                        f"{format_money(row['revenue'])}."
                    ),
                }
            )

        if row["return_rate"] > 0.15:
            anomaly_rows.append(
                {
                    "anomaly_type": "return_rate_over_15_percent",
                    "level": "month",
                    "period": row["year_month"],
                    "order_id": "",
                    "metric_value": row["return_rate"],
                    "threshold": 0.15,
                    "details": f"Monthly return rate was {row['return_rate']:.1%}.",
                }
            )

    high_discount_orders = orders[orders["discount_rate"] > 0.30]

    for _, row in high_discount_orders.iterrows():
        anomaly_rows.append(
            {
                "anomaly_type": "discount_rate_over_30_percent",
                "level": "order",
                "period": row["year_month"],
                "order_id": row["order_id"],
                "metric_value": row["discount_rate"],
                "threshold": 0.30,
                "details": (
                    f"Product {row['product_id']} had a "
                    f"{row['discount_rate']:.1%} discount."
                ),
            }
        )

    return pd.DataFrame(
        anomaly_rows,
        columns=[
            "anomaly_type",
            "level",
            "period",
            "order_id",
            "metric_value",
            "threshold",
            "details",
        ],
    )


def make_duplicate_rows_detail(enriched_orders):
    """List fully duplicated order rows for manual review."""
    if enriched_orders.empty:
        return pd.DataFrame(columns=DUPLICATE_ROWS_DETAIL_COLUMNS)

    comparison_columns = [
        column
        for column in enriched_orders.columns
        if column != "source_row_number"
    ]
    duplicate_mask = enriched_orders.duplicated(
        subset=comparison_columns,
        keep=False,
    )
    duplicate_rows = enriched_orders.loc[duplicate_mask].copy()

    if duplicate_rows.empty:
        return pd.DataFrame(columns=DUPLICATE_ROWS_DETAIL_COLUMNS)

    duplicate_rows["duplicate_group_id"] = (
        duplicate_rows.groupby(comparison_columns, dropna=False).ngroup() + 1
    )
    duplicate_group_count = duplicate_rows["duplicate_group_id"].nunique()
    duplicate_row_count = len(duplicate_rows)
    duplicate_rows["duplicate_group_count"] = duplicate_group_count
    duplicate_rows["duplicate_row_count"] = duplicate_row_count
    full_row_columns = [
        column
        for column in duplicate_rows.columns
        if column not in DUPLICATE_ROWS_DETAIL_COLUMNS
    ]
    detail_columns = [
        column
        for column in DUPLICATE_ROWS_DETAIL_COLUMNS
        if column in duplicate_rows.columns
    ] + full_row_columns

    return duplicate_rows[detail_columns].sort_values(
        ["duplicate_group_id", "source_row_number"]
    )


def make_repeated_order_id_detail(enriched_orders):
    """Summarize repeated order_id values and whether their rows are identical."""
    if enriched_orders.empty or "order_id" not in enriched_orders.columns:
        return pd.DataFrame(columns=REPEATED_ORDER_ID_DETAIL_COLUMNS)

    comparison_columns = [
        column
        for column in enriched_orders.columns
        if column != "source_row_number"
    ]
    order_id_counts = enriched_orders["order_id"].value_counts(dropna=False)
    repeated_order_ids = order_id_counts[order_id_counts > 1]
    rows = []

    for order_id, occurrence_count in repeated_order_ids.items():
        if pd.isna(order_id):
            order_rows = enriched_orders[enriched_orders["order_id"].isna()]
        else:
            order_rows = enriched_orders[enriched_orders["order_id"] == order_id]

        rows_are_fully_identical = (
            order_rows[comparison_columns].drop_duplicates().shape[0] == 1
        )
        source_row_numbers = ", ".join(
            order_rows["source_row_number"].astype(str).tolist()
        )

        rows.append(
            {
                "order_id": order_id,
                "occurrence_count": int(occurrence_count),
                "source_row_numbers": source_row_numbers,
                "rows_are_fully_identical": rows_are_fully_identical,
                "note": (
                    "Repeated order_id values may be normal for "
                    "order-line-level data, but fully identical rows should be "
                    "reviewed because they may duplicate revenue."
                ),
            }
        )

    return pd.DataFrame(rows, columns=REPEATED_ORDER_ID_DETAIL_COLUMNS)


def data_quality_report_to_table(data_quality_report):
    """Convert the data quality report dictionary into a table for Excel."""
    rows = [
        {"section": "file", "metric": "file_path", "value": data_quality_report["file_path"]},
        {"section": "file", "metric": "status", "value": data_quality_report["status"]},
        {"section": "file", "metric": "row_count", "value": data_quality_report["row_count"]},
        {
            "section": "file",
            "metric": "column_count",
            "value": data_quality_report["column_count"],
        },
        {
            "section": "duplicates",
            "metric": "duplicate_rows",
            "value": data_quality_report["duplicate_rows"],
        },
        {
            "section": "duplicates",
            "metric": "repeated_order_id_rows",
            "value": data_quality_report["repeated_order_id_rows"],
        },
    ]

    for column in data_quality_report["missing_required_columns"]:
        rows.append(
            {
                "section": "missing_required_columns",
                "metric": column,
                "value": "missing",
            }
        )

    for column, missing_count in data_quality_report["missing_values_by_column"].items():
        rows.append(
            {
                "section": "missing_values",
                "metric": column,
                "value": missing_count,
            }
        )

    return pd.DataFrame(rows)


def build_sales_report(
    csv_path=DEFAULT_INPUT,
    expenses_path=DEFAULT_EXPENSES_INPUT,
    column_mapping=None,
):
    """Run all analysis steps and return every report table."""
    data_quality_report = create_data_quality_report(csv_path, column_mapping)

    if data_quality_report["missing_required_columns"]:
        post_conversion_data_quality = pd.DataFrame(
            columns=["check_name", "issue_count", "status"]
        )
        validation_report = pd.DataFrame(
            columns=[
                "check_name",
                "expected_value",
                "actual_value",
                "difference",
                "status",
            ]
        )
        report_status = make_report_status_table(
            data_quality_report,
            post_conversion_data_quality,
            validation_report,
        )
        report_tables = {
            "data_quality_report": data_quality_report,
            "report_status": report_status,
            "data_quality": data_quality_report_to_table(data_quality_report),
            "duplicate_rows_detail": pd.DataFrame(
                columns=DUPLICATE_ROWS_DETAIL_COLUMNS
            ),
            "repeated_order_id_detail": pd.DataFrame(
                columns=REPEATED_ORDER_ID_DETAIL_COLUMNS
            ),
            "post_conversion_data_quality": post_conversion_data_quality,
            "validation_report": validation_report,
            "enriched_orders": pd.DataFrame(),
            "monthly_summary": pd.DataFrame(),
            "category_summary": pd.DataFrame(),
            "customer_summary": pd.DataFrame(),
            "top_products": pd.DataFrame(),
            "anomalies": pd.DataFrame(
                columns=[
                    "anomaly_type",
                    "level",
                    "period",
                    "order_id",
                    "metric_value",
                    "threshold",
                    "details",
                ]
            ),
        }
        report_tables.update(make_empty_finance_tables(expenses_path))

        return report_tables

    orders = add_source_row_number(load_orders(csv_path, column_mapping))
    enriched_orders = calculate_revenue_metrics(orders)
    duplicate_rows_detail = make_duplicate_rows_detail(enriched_orders)
    repeated_order_id_detail = make_repeated_order_id_detail(enriched_orders)
    post_conversion_data_quality = make_post_conversion_data_quality_report(
        enriched_orders
    )
    monthly_summary = make_monthly_summary(enriched_orders)
    category_summary = make_category_summary(enriched_orders)
    customer_summary = make_customer_summary(enriched_orders)
    top_products = find_top_products(enriched_orders)
    anomalies = detect_anomalies(enriched_orders, monthly_summary)
    validation_report = make_validation_report(
        enriched_orders,
        monthly_summary,
        category_summary,
        customer_summary,
    )
    finance_tables = build_finance_report(
        monthly_summary,
        expenses_path,
        column_mapping,
    )
    report_status = make_report_status_table(
        data_quality_report,
        post_conversion_data_quality,
        validation_report,
        finance_tables["expense_post_conversion_quality"],
    )

    report_tables = {
        "data_quality_report": data_quality_report,
        "report_status": report_status,
        "data_quality": data_quality_report_to_table(data_quality_report),
        "duplicate_rows_detail": duplicate_rows_detail,
        "repeated_order_id_detail": repeated_order_id_detail,
        "post_conversion_data_quality": post_conversion_data_quality,
        "validation_report": validation_report,
        "enriched_orders": enriched_orders,
        "monthly_summary": monthly_summary,
        "category_summary": category_summary,
        "customer_summary": customer_summary,
        "top_products": top_products,
        "anomalies": anomalies,
    }
    report_tables.update(finance_tables)

    return report_tables


def adjust_excel_column_widths(writer):
    """Make the Excel sheets easier to read."""
    for worksheet in writer.book.worksheets:
        worksheet.freeze_panes = "A2"

        for column_cells in worksheet.columns:
            column_letter = get_column_letter(column_cells[0].column)
            longest_value = 0

            for cell in column_cells:
                if cell.value is not None:
                    longest_value = max(longest_value, len(str(cell.value)))

            worksheet.column_dimensions[column_letter].width = min(longest_value + 2, 45)


def export_excel(report_tables, excel_path=DEFAULT_EXCEL_OUTPUT):
    """Export the analysis results to one Excel file with multiple sheets."""
    output_path = get_file_path(excel_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        report_tables["report_status"].to_excel(
            writer,
            sheet_name="report_status",
            index=False,
        )
        report_tables["data_quality"].to_excel(
            writer,
            sheet_name="data_quality",
            index=False,
        )
        report_tables["duplicate_rows_detail"].to_excel(
            writer,
            sheet_name="duplicate_rows_detail",
            index=False,
        )
        report_tables["repeated_order_id_detail"].to_excel(
            writer,
            sheet_name="repeated_order_id_detail",
            index=False,
        )
        report_tables["post_conversion_data_quality"].to_excel(
            writer,
            sheet_name="post_conversion_quality",
            index=False,
        )
        report_tables["validation_report"].to_excel(
            writer,
            sheet_name="validation_report",
            index=False,
        )
        report_tables["enriched_orders"].to_excel(
            writer,
            sheet_name="enriched_orders",
            index=False,
        )
        report_tables["monthly_summary"].to_excel(
            writer,
            sheet_name="monthly_summary",
            index=False,
        )
        report_tables["category_summary"].to_excel(
            writer,
            sheet_name="category_summary",
            index=False,
        )
        report_tables["customer_summary"].to_excel(
            writer,
            sheet_name="customer_summary",
            index=False,
        )
        report_tables["top_products"].to_excel(
            writer,
            sheet_name="top_products",
            index=False,
        )
        report_tables["anomalies"].to_excel(
            writer,
            sheet_name="anomalies",
            index=False,
        )
        report_tables["finance_status"].to_excel(
            writer,
            sheet_name="finance_status",
            index=False,
        )
        report_tables["expense_post_conversion_quality"].to_excel(
            writer,
            sheet_name="expense_quality",
            index=False,
        )
        report_tables["finance_kpis"].to_excel(
            writer,
            sheet_name="finance_kpis",
            index=False,
        )
        report_tables["cash_flow_summary"].to_excel(
            writer,
            sheet_name="cash_flow_summary",
            index=False,
        )
        report_tables["expense_category_breakdown"].to_excel(
            writer,
            sheet_name="expense_categories",
            index=False,
        )
        report_tables["largest_expense_categories"].to_excel(
            writer,
            sheet_name="largest_expenses",
            index=False,
        )
        report_tables["cash_flow_warnings"].to_excel(
            writer,
            sheet_name="cash_flow_warnings",
            index=False,
        )
        report_tables["expenses_enriched"].to_excel(
            writer,
            sheet_name="expenses_enriched",
            index=False,
        )
        adjust_excel_column_widths(writer)

    return output_path


def get_kpi_value(finance_kpis, metric, default=0):
    """Read one value from the finance KPI table."""
    if finance_kpis.empty:
        return default

    matches = finance_kpis[finance_kpis["metric"] == metric]

    if matches.empty:
        return default

    return matches.iloc[0]["value"]


def format_money(value):
    """Format a number as a readable dollar amount."""
    amount = float(value)

    if amount < 0:
        return f"-${abs(amount):,.2f}"

    return f"${amount:,.2f}"


def is_finite_number(value):
    """Return True when a value is a real finite number."""
    return (
        pd.notna(value)
        and value != float("inf")
        and value != float("-inf")
    )


def generate_summary_markdown(report_tables, summary_path=DEFAULT_SUMMARY_OUTPUT):
    """Turn summary tables into a business-friendly Markdown summary."""
    monthly = report_tables["monthly_summary"]
    categories = report_tables["category_summary"]
    customers = report_tables["customer_summary"]
    products = report_tables["top_products"]
    anomalies = report_tables["anomalies"]
    data_quality_report = report_tables["data_quality_report"]
    report_status = report_tables["report_status"]
    post_conversion_quality = report_tables["post_conversion_data_quality"]
    validation_report = report_tables["validation_report"]
    finance_status = report_tables["finance_status"]
    expense_quality = report_tables["expense_post_conversion_quality"]
    finance_kpis = report_tables["finance_kpis"]
    cash_flow = report_tables["cash_flow_summary"]
    expense_categories = report_tables["expense_category_breakdown"]
    cash_flow_warnings = report_tables["cash_flow_warnings"]

    output_path = get_file_path(summary_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_status_value = report_status.iloc[0]["status"]
    report_status_reason = report_status.iloc[0]["reason"]
    report_failed = report_status_value == "failed"

    if monthly.empty:
        lines = [
            "# Sales Reporting Summary",
            "",
            "## Report Status",
            f"- Status: {report_status_value}.",
            f"- Reason: {report_status_reason}",
            "",
            "## Data Quality Notes",
        ]

        if data_quality_report["missing_required_columns"]:
            missing_text = ", ".join(data_quality_report["missing_required_columns"])
            lines.append(f"- Missing required columns: {missing_text}.")
        else:
            lines.append("- No monthly summary was generated.")

        lines.extend(
            [
                "",
                "## Validation Results",
                "- Validation checks were not run.",
            ]
        )
        output_path.write_text("\n".join(lines), encoding="utf-8")

        return output_path

    total_revenue = monthly["revenue"].sum()
    total_gross_revenue = monthly["gross_revenue"].sum()
    total_discount = monthly["discount_amount"].sum()
    total_orders = monthly["orders"].sum()
    total_units = monthly["units"].sum()
    overall_aov = divide_safely(total_revenue, total_orders)
    discount_impact_rate = divide_safely(total_discount, total_gross_revenue)
    best_month = monthly.loc[monthly["revenue"].idxmax()]
    weakest_month = monthly.loc[monthly["revenue"].idxmin()]
    finite_growth_mask = monthly["revenue_growth_rate"].apply(is_finite_number)
    finite_growth_months = monthly[finite_growth_mask]
    non_finite_growth_months = monthly[
        monthly["revenue_growth_rate"].notna() & ~finite_growth_mask
    ]
    top_category = categories.iloc[0]
    top_customer = customers.iloc[0]
    top_product = products.iloc[0]

    lines = [
        "# Sales Reporting Summary",
        "",
        "## Report Status",
        f"- Status: {report_status_value}.",
        f"- Reason: {report_status_reason}",
        "",
    ]

    if report_failed:
        lines.extend(
            [
                "## Critical Data Quality Warning",
                (
                    "- This report failed critical data quality checks. The "
                    "business summary below is for diagnostic review only and "
                    "should not be used for decision-making until the data "
                    "issues are fixed."
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Executive Summary",
            f"- Total final revenue was {format_money(total_revenue)}.",
            (
                f"- Total orders were {int(total_orders):,}, with "
                f"{int(total_units):,} units sold."
            ),
            f"- Overall AOV was {format_money(overall_aov)}.",
            (
                f"- Discounts reduced gross revenue by {format_money(total_discount)}, "
                f"a {discount_impact_rate:.1%} discount impact."
            ),
            (
                f"- The strongest month was {best_month['year_month']} "
                f"with {format_money(best_month['revenue'])} in revenue."
            ),
            (
                f"- The weakest month was {weakest_month['year_month']} "
                f"with {format_money(weakest_month['revenue'])} in revenue."
            ),
        ]
    )

    if not finite_growth_months.empty:
        best_growth_month = finite_growth_months.loc[
            finite_growth_months["revenue_growth_rate"].idxmax()
        ]
        lines.append(
            f"- The highest month-over-month growth was "
            f"{best_growth_month['revenue_growth_rate']:.1%} "
            f"in {best_growth_month['year_month']}."
        )

    for _, row in non_finite_growth_months.iterrows():
        lines.append(
            f"- Revenue changed from {format_money(row['previous_revenue'])} "
            f"to {format_money(row['revenue'])} in {row['year_month']}, so "
            "percentage growth is not meaningful."
        )

    business_summary_title = (
        "Diagnostic Business Summary" if report_failed else "Business Insights"
    )

    lines.extend(
        [
            "",
            f"## {business_summary_title}",
        ]
    )

    if report_failed:
        lines.append(
            "- Results in this section may be affected by data quality issues."
        )

    insight_prefix = "Based on currently usable rows, " if report_failed else ""

    lines.extend(
        [
            (
                f"- {insight_prefix}{top_category['category']} was the leading "
                f"category, generating {format_money(top_category['revenue'])} "
                "in revenue."
            ),
            (
                f"- {insight_prefix}{top_customer['customer_name']} was the "
                f"highest-revenue customer, contributing "
                f"{format_money(top_customer['revenue'])}."
            ),
            (
                f"- {insight_prefix}{top_product['product_name']} was the "
                f"highest-revenue product, contributing "
                f"{format_money(top_product['revenue'])}."
            ),
            f"- Detected anomalies: {len(anomalies)}.",
            "",
            "## Data Quality Notes",
        ]
    )

    if data_quality_report["status"] == "passed":
        lines.append("- Required order columns were present.")
    else:
        lines.append(f"- {data_quality_report['error_message']}")

    if data_quality_report["duplicate_rows"]:
        lines.append(f"- Duplicate rows: {data_quality_report['duplicate_rows']}.")
        lines.append(
            "- Duplicate rows may inflate revenue if they are accidental "
            "duplicates. Review the duplicate_rows_detail sheet before making "
            "business decisions."
        )
    else:
        lines.append("- Duplicate rows: 0.")

    repeated_order_id_rows = data_quality_report["repeated_order_id_rows"]

    if repeated_order_id_rows:
        lines.append(
            f"- Repeated order_id rows: {repeated_order_id_rows}."
        )
    else:
        lines.append("- Repeated order_id rows: 0.")

    lines.append(
        "- Repeated order_id values may be normal for order-line-level data. "
        "Review the repeated_order_id_detail sheet to confirm whether repeated "
        "IDs are expected line items or fully duplicated rows."
    )

    invalid_date_rows = get_quality_issue_count(
        post_conversion_quality,
        "invalid_date_count",
    )
    lines.append(f"- Invalid date rows: {invalid_date_rows}.")

    if invalid_date_rows:
        lines.append("- Invalid date rows were excluded from monthly trend tables.")

    invalid_returned_count = get_quality_issue_count(
        post_conversion_quality,
        "invalid_returned_count",
    )

    if invalid_returned_count:
        lines.append(
            "- Invalid returned values were treated as not returned for revenue calculation."
        )

    lines.append(
        "- invalid_discount_policy: invalid or out-of-range discount_rate values are not used; affected discounted_revenue and final_revenue values are set to NA."
    )

    quality_issues = post_conversion_quality[
        post_conversion_quality["issue_count"] > 0
    ]

    if quality_issues.empty:
        lines.append("- Post-conversion checks found no issues.")
    else:
        for _, row in quality_issues.iterrows():
            lines.append(f"- {row['check_name']}: {int(row['issue_count'])}.")

    expense_quality_issues = expense_quality[expense_quality["issue_count"] > 0]

    if expense_quality.empty:
        lines.append("- Expense post-conversion checks were skipped.")
    elif expense_quality_issues.empty:
        lines.append("- Expense post-conversion checks found no issues.")
    else:
        lines.append(
            "- Invalid expense rows were excluded from finance summary and "
            "expense category breakdown."
        )

        for _, row in expense_quality_issues.iterrows():
            lines.append(f"- {row['check_name']}: {int(row['issue_count'])}.")

    lines.extend(
        [
            "",
            "## Validation Results",
        ]
    )

    validation_checks = validation_report[validation_report["status"] != "info"]
    failed_validations = validation_report[validation_report["status"] == "failed"]
    validation_info = validation_report[validation_report["status"] == "info"]

    if failed_validations.empty:
        lines.append(f"- All {len(validation_checks)} validation checks passed.")
    else:
        lines.append(
            f"- {len(failed_validations)} of {len(validation_checks)} validation checks failed."
        )

        for _, row in failed_validations.iterrows():
            lines.append(
                f"- {row['check_name']}: difference {row['difference']:.2f}."
            )

    for _, row in validation_info.iterrows():
        if row["check_name"] == "invalid_date_excluded_revenue":
            lines.append(
                f"- invalid_date_excluded_revenue: {format_money(row['actual_value'])}."
            )

    lines.extend(
        [
            "",
            "## Finance Summary",
        ]
    )

    finance_status_value = finance_status.loc[
        finance_status["metric"] == "finance_module_status",
        "value",
    ].iloc[0]

    if finance_status_value == "skipped":
        lines.append(
            "- Expense data was not provided, so cash flow analysis was skipped."
        )
    else:
        total_income = get_kpi_value(finance_kpis, "total_income")
        total_expenses = get_kpi_value(finance_kpis, "total_expenses")
        net_cash_flow = get_kpi_value(finance_kpis, "net_cash_flow")
        profit_margin = get_kpi_value(finance_kpis, "profit_margin")
        warning_months = get_kpi_value(finance_kpis, "warning_months")
        largest_expense_category = get_kpi_value(
            finance_kpis,
            "largest_expense_category",
            "",
        )
        largest_expense_amount = get_kpi_value(
            finance_kpis,
            "largest_expense_category_amount",
        )
        strongest_cash_month = cash_flow.loc[cash_flow["net_cash_flow"].idxmax()]
        weakest_cash_month = cash_flow.loc[cash_flow["net_cash_flow"].idxmin()]

        lines.extend(
            [
                f"- Total income was {format_money(total_income)}.",
                f"- Total expenses were {format_money(total_expenses)}.",
                f"- Net cash flow was {format_money(net_cash_flow)}.",
                f"- Profit margin was {profit_margin:.1%}.",
                (
                    f"- Largest expense category: {largest_expense_category} "
                    f"({format_money(largest_expense_amount)})."
                ),
                (
                    f"- Strongest cash flow month: {strongest_cash_month['year_month']} "
                    f"({format_money(strongest_cash_month['net_cash_flow'])})."
                ),
                (
                    f"- Weakest cash flow month: {weakest_cash_month['year_month']} "
                    f"({format_money(weakest_cash_month['net_cash_flow'])})."
                ),
                f"- Cash flow warning months: {int(warning_months)}.",
            ]
        )

        if not expense_categories.empty:
            lines.append(
                f"- {expense_categories.iloc[0]['expense_category']} was the "
                f"largest expense category, representing "
                f"{expense_categories.iloc[0]['share_of_expenses']:.1%} "
                f"of expenses."
            )

        if not cash_flow_warnings.empty:
            first_warning = cash_flow_warnings.iloc[0]
            lines.append(
                f"- First cash flow warning: {first_warning['warning_type']} "
                f"in {first_warning['year_month']}."
            )

    lines.extend(
        [
            "",
            "## Anomaly Notes",
        ]
    )

    if anomalies.empty:
        lines.append("- No anomalies were detected with the current rules.")
    else:
        for _, row in anomalies.head(10).iterrows():
            lines.append(f"- {row['anomaly_type']}: {row['details']}")

    lines.extend(
        [
            "",
            "## Method",
            (
                "- This summary is generated from the monthly, category, customer, "
                "product, finance, cash flow, and anomaly tables. It is written "
                "in a business-friendly style so it can later be replaced or "
                "enhanced with an LLM."
            ),
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")

    return output_path


def run_pipeline(
    csv_path=DEFAULT_INPUT,
    expenses_path=DEFAULT_EXPENSES_INPUT,
    excel_path=DEFAULT_EXCEL_OUTPUT,
    summary_path=DEFAULT_SUMMARY_OUTPUT,
    config_path=None,
):
    """Run the full sales reporting workflow."""
    column_mapping = load_column_mapping(config_path)
    report_tables = build_sales_report(csv_path, expenses_path, column_mapping)
    excel_output = export_excel(report_tables, excel_path)
    summary_output = generate_summary_markdown(report_tables, summary_path)

    return report_tables, excel_output, summary_output


def print_data_quality_report(data_quality_report):
    """Print the data quality report in a readable way."""
    print("Data Quality Report")
    print("===================")
    print(f"File: {data_quality_report['file_path']}")
    print(f"Status: {data_quality_report['status']}")
    print(f"Rows: {data_quality_report['row_count']}")
    print(f"Columns: {data_quality_report['column_count']}")
    print()

    print("Missing required columns:")
    if data_quality_report["missing_required_columns"]:
        for column in data_quality_report["missing_required_columns"]:
            print(f"- {column}")
    else:
        print("- None")
    print()

    print("Missing values by column:")
    for column, missing_count in data_quality_report["missing_values_by_column"].items():
        print(f"- {column}: {missing_count}")
    print()

    print("Duplicate checks:")
    print(f"- Duplicate rows: {data_quality_report['duplicate_rows']}")
    print(f"- Repeated order_id rows: {data_quality_report['repeated_order_id_rows']}")

    if data_quality_report["error_message"]:
        print()
        print(data_quality_report["error_message"])


def parse_args():
    """Read command line options."""
    parser = ArgumentParser(description="Create a sales reporting automation report.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input CSV path.")
    parser.add_argument(
        "--expenses",
        default=DEFAULT_EXPENSES_INPUT,
        help="Expenses CSV path.",
    )
    parser.add_argument("--excel", default=DEFAULT_EXCEL_OUTPUT, help="Output Excel path.")
    parser.add_argument(
        "--summary",
        default=DEFAULT_SUMMARY_OUTPUT,
        help="Output Markdown summary path.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional JSON config path for column name mapping.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        tables, excel_file, summary_file = run_pipeline(
            csv_path=args.input,
            expenses_path=args.expenses,
            excel_path=args.excel,
            summary_path=args.summary,
            config_path=args.config,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"Error: {error}") from error

    print_data_quality_report(tables["data_quality_report"])
    print()
    print(f"Excel report created: {excel_file}")
    print(f"Markdown summary created: {summary_file}")
