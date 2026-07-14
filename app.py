import json
import hashlib
import traceback
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis import REQUIRED_COLUMNS, run_pipeline
from multi_table_loader import (
    MultiTableLoaderError,
    load_multi_table_dataset,
    read_csv_with_encoding_fallback,
)
from generic_relationship_ui import render_generic_relationship_mode
from generic_report_generation import (
    customer_analysis_available,
    customer_analysis_unavailable_message,
    return_analysis_available,
)


EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
OPTIONAL_ORDER_COLUMNS = ["customer_name", "product_name", "category"]
SELECT_COLUMN = "Select a column"
DO_NOT_MAP = "Do not map"
AUTO_PRODUCT_NAME = "Auto: use product_name"

COLUMN_ALIASES = {
    "order_id": ["订单编号", "订单号", "order_number", "order no", "order id"],
    "date": ["下单日期", "订单日期", "日期", "order_date", "order date"],
    "customer_id": ["客户ID", "客户编号", "customer", "customer id"],
    "product_id": ["商品编号", "产品编号", "sku", "product", "product id"],
    "unit_price": ["单价", "销售单价", "price", "unit price"],
    "quantity": ["数量", "件数", "qty", "units"],
    "discount_rate": ["折扣率", "折扣", "discount", "discount rate"],
    "returned": ["是否退货", "退货", "returned", "return_flag"],
    "customer_name": ["客户名称", "客户名", "customer name"],
    "product_name": ["商品名称", "产品名称", "product name"],
    "category": ["品类", "类别", "分类", "category"],
}


def save_uploaded_file(uploaded_file, output_path):
    """Save one Streamlit upload to a temporary file path."""
    output_path.write_bytes(uploaded_file.getvalue())

    return output_path


def read_uploaded_csv(uploaded_file):
    """Read an uploaded CSV file into a DataFrame."""
    return pd.read_csv(BytesIO(uploaded_file.getvalue()))


def get_uploaded_file_signature(uploaded_file):
    """Return a stable signature for one uploaded file."""
    if uploaded_file is None:
        return None

    file_bytes = uploaded_file.getvalue()

    return {
        "name": getattr(uploaded_file, "name", "uploaded_file"),
        "size": len(file_bytes),
        "md5": hashlib.md5(file_bytes).hexdigest(),
    }


def make_multi_table_upload_signature(uploaded_files):
    """Return a signature for the current multi-table upload set."""
    return {
        table_name: get_uploaded_file_signature(uploaded_file)
        for table_name, uploaded_file in uploaded_files.items()
    }


def clear_multi_table_state_if_uploads_changed(upload_signature):
    """Clear prepared multi-table state when source uploads change."""
    previous_signature = st.session_state.get("multi_table_upload_signature")

    if previous_signature != upload_signature:
        st.session_state["multi_table_upload_signature"] = upload_signature
        st.session_state.pop("multi_table_result", None)
        st.session_state.pop("report_result", None)


def read_uploaded_table_summary(uploaded_file, table_name):
    """Read one uploaded table for the file summary and preview area."""
    frame, metadata = read_csv_with_encoding_fallback(uploaded_file, table_name)

    return {
        "metadata": metadata,
        "preview": frame.head(5),
    }


def get_cached_uploaded_table_summary(uploaded_file, table_name):
    """Cache uploaded table previews so reruns do not repeatedly parse files."""
    if uploaded_file is None:
        return None

    cache_key = f"table_preview_{table_name}"
    signature = get_uploaded_file_signature(uploaded_file)
    cached = st.session_state.get(cache_key)

    if cached and cached["signature"] == signature:
        return cached["summary"]

    summary = read_uploaded_table_summary(uploaded_file, table_name)
    st.session_state[cache_key] = {
        "signature": signature,
        "summary": summary,
    }

    return summary


def show_uploaded_table_summary(uploaded_file, table_name):
    """Show file name, shape, columns, and preview for one uploaded CSV."""
    if uploaded_file is None:
        return

    try:
        summary = get_cached_uploaded_table_summary(uploaded_file, table_name)
    except Exception as error:
        st.error(f"Could not read {table_name}: {error}")
        with st.expander(f"{table_name} error details"):
            st.code(traceback.format_exc())
        return

    metadata = summary["metadata"]

    with st.expander(f"{table_name}: {metadata['file_name']}", expanded=False):
        st.write(f"Rows: {metadata['row_count']:,}")
        st.write(f"Columns: {metadata['column_count']:,}")
        st.write(f"Encoding: {metadata['encoding']}")
        st.write("Column names:")
        st.dataframe(
            pd.DataFrame({"column": metadata["columns"]}),
            hide_index=True,
            use_container_width=True,
        )
        st.write("Preview:")
        st.dataframe(summary["preview"], hide_index=True, use_container_width=True)


def save_orders_file(uploaded_file, output_path, source_rows_to_remove=None):
    """Save uploaded orders, optionally removing selected source row numbers."""
    if not source_rows_to_remove:
        return save_uploaded_file(uploaded_file, output_path)

    orders = read_uploaded_csv(uploaded_file)
    source_row_numbers = pd.Series(orders.index + 2, index=orders.index)
    filtered_orders = orders.loc[
        ~source_row_numbers.isin(source_rows_to_remove)
    ].copy()
    filtered_orders.to_csv(output_path, index=False)

    return output_path


def make_duplicate_rows_preview(uploaded_file):
    """Return fully duplicated uploaded order rows for Streamlit review."""
    orders = read_uploaded_csv(uploaded_file)
    original_columns = list(orders.columns)
    duplicate_mask = orders.duplicated(subset=original_columns, keep=False)
    duplicate_rows = orders.loc[duplicate_mask].copy()

    if duplicate_rows.empty:
        return pd.DataFrame(columns=["duplicate_group_id", "source_row_number"])

    duplicate_rows.insert(0, "source_row_number", duplicate_rows.index + 2)
    duplicate_rows.insert(
        0,
        "duplicate_group_id",
        duplicate_rows.groupby(original_columns, dropna=False).ngroup() + 1,
    )

    display_columns = [
        "duplicate_group_id",
        "source_row_number",
    ] + original_columns

    return duplicate_rows[display_columns].sort_values(
        ["duplicate_group_id", "source_row_number"]
    )


def get_duplicate_review_counts(duplicate_rows):
    """Return duplicate group count and involved row count."""
    if duplicate_rows.empty:
        return 0, 0

    return int(duplicate_rows["duplicate_group_id"].nunique()), len(duplicate_rows)


def add_duplicate_counts_to_detail(
    duplicate_rows,
    duplicate_group_count,
    duplicate_row_count,
):
    """Add duplicate group and row counts to an Excel detail table."""
    if duplicate_rows.empty:
        return duplicate_rows

    detail = duplicate_rows.copy()
    detail.insert(2, "duplicate_group_count", duplicate_group_count)
    detail.insert(3, "duplicate_row_count", duplicate_row_count)

    return detail


def replace_duplicate_detail_sheet(excel_path, duplicate_rows_detail):
    """Replace duplicate_rows_detail with original uploaded duplicate details."""
    with pd.ExcelWriter(
        excel_path,
        engine="openpyxl",
        mode="a",
        if_sheet_exists="replace",
    ) as writer:
        duplicate_rows_detail.to_excel(
            writer,
            sheet_name="duplicate_rows_detail",
            index=False,
        )


def add_duplicate_review_notes(
    summary_text,
    duplicate_group_count,
    duplicate_row_count,
    removed_row_count,
):
    """Add Streamlit duplicate-review notes to the Markdown summary."""
    notes = []

    if duplicate_group_count:
        notes.append(
            f"- Original uploaded data contained {duplicate_group_count} "
            f"duplicate groups involving {duplicate_row_count} rows."
        )

    if removed_row_count:
        notes.append(
            f"- {removed_row_count} selected duplicate row(s) were removed "
            "from the temporary report input before calculation. The original "
            "uploaded file was not changed."
        )

    if not notes:
        return summary_text

    lines = summary_text.splitlines()

    if "## Data Quality Notes" in lines:
        insert_index = lines.index("## Data Quality Notes") + 1
    elif "## Method" in lines:
        insert_index = lines.index("## Method")
        notes = ["", "## Data Quality Notes"] + notes
    else:
        insert_index = len(lines)
        notes = ["", "## Data Quality Notes"] + notes

    lines[insert_index:insert_index] = notes

    return "\n".join(lines)


def read_csv_columns(uploaded_file):
    """Read only the header row from an uploaded CSV file."""
    csv_bytes = uploaded_file.getvalue()
    header = pd.read_csv(BytesIO(csv_bytes), nrows=0)

    return list(header.columns)


def normalize_column_name(column_name):
    """Normalize a column name so simple aliases can be matched."""
    return str(column_name).strip().lower().replace("_", " ")


def guess_source_column(standard_column, csv_columns):
    """Guess which uploaded CSV column maps to one standard column."""
    aliases = COLUMN_ALIASES.get(standard_column, [])
    normalized_columns = {
        normalize_column_name(column): column
        for column in csv_columns
    }

    for alias in aliases:
        normalized_alias = normalize_column_name(alias)

        if normalized_alias in normalized_columns:
            return normalized_columns[normalized_alias]

    return None


def get_missing_required_columns(csv_columns):
    """Return required columns that were not found directly in the upload."""
    return [
        column
        for column in REQUIRED_COLUMNS
        if column not in csv_columns
    ]


def get_uploaded_config_mapping(config_file):
    """Read an optional uploaded config.json file."""
    empty_mapping = {"orders_columns": {}, "expenses_columns": {}}

    if config_file is None:
        return empty_mapping

    try:
        config = json.loads(config_file.getvalue().decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"config.json is not valid JSON: {error}") from error

    return {
        "orders_columns": config.get("orders_columns", {}) or {},
        "expenses_columns": config.get("expenses_columns", {}) or {},
    }


def get_default_required_selection(standard_column, csv_columns, config_mapping):
    """Choose a friendly default for a required mapping selectbox."""
    configured_source = config_mapping.get("orders_columns", {}).get(standard_column)

    if configured_source in csv_columns:
        return configured_source

    guessed_source = guess_source_column(standard_column, csv_columns)

    if guessed_source:
        return guessed_source

    if standard_column == "product_id" and "product_name" in csv_columns:
        return AUTO_PRODUCT_NAME

    return SELECT_COLUMN


def get_default_optional_selection(standard_column, csv_columns, config_mapping):
    """Choose a friendly default for an optional mapping selectbox."""
    configured_source = config_mapping.get("orders_columns", {}).get(standard_column)

    if configured_source in csv_columns:
        return configured_source

    guessed_source = guess_source_column(standard_column, csv_columns)

    if guessed_source:
        return guessed_source

    return DO_NOT_MAP


def normalize_selected_source(selected_source):
    """Convert a UI selectbox value into a CSV source column name."""
    if selected_source in [SELECT_COLUMN, DO_NOT_MAP, None]:
        return None

    if selected_source == AUTO_PRODUCT_NAME:
        return "product_name"

    return selected_source


def build_orders_mapping(required_selections, optional_selections):
    """Build the orders_columns mapping selected in the Streamlit page."""
    orders_mapping = {}
    used_sources = set()

    for standard_column, selected_source in required_selections.items():
        source_column = normalize_selected_source(selected_source)

        if source_column is None:
            continue

        orders_mapping[standard_column] = source_column
        used_sources.add(source_column)

    for standard_column, selected_source in optional_selections.items():
        source_column = normalize_selected_source(selected_source)

        if source_column is None or source_column in used_sources:
            continue

        orders_mapping[standard_column] = source_column
        used_sources.add(source_column)

    return orders_mapping


def merge_column_mappings(uploaded_config_mapping, ui_orders_mapping):
    """Merge uploaded config.json mapping with mappings chosen in the UI."""
    merged_mapping = {
        "orders_columns": dict(uploaded_config_mapping.get("orders_columns", {})),
        "expenses_columns": dict(uploaded_config_mapping.get("expenses_columns", {})),
    }
    merged_mapping["orders_columns"].update(ui_orders_mapping)

    return merged_mapping


def mapping_has_values(column_mapping):
    """Return True if any mapping value exists."""
    return bool(
        column_mapping.get("orders_columns")
        or column_mapping.get("expenses_columns")
    )


def validate_orders_mapping(csv_columns, missing_required_columns, column_mapping):
    """Return user-facing mapping errors before running the report."""
    errors = []
    orders_mapping = column_mapping.get("orders_columns", {})
    source_usage = {}

    for required_column in missing_required_columns:
        source_column = orders_mapping.get(required_column)

        if source_column is None:
            if required_column == "date":
                errors.append("Monthly trend analysis requires a date column.")

            errors.append(f"Please map the required column: {required_column}")
            continue

        if source_column not in csv_columns:
            errors.append(
                f"Mapped column for {required_column} was not found: {source_column}"
            )

    for standard_column, source_column in orders_mapping.items():
        if not source_column:
            continue

        source_usage.setdefault(source_column, []).append(standard_column)

    for source_column, standard_columns in source_usage.items():
        if len(standard_columns) > 1:
            joined_columns = ", ".join(standard_columns)
            errors.append(
                f"One uploaded column cannot map to multiple fields: "
                f"{source_column} -> {joined_columns}"
            )

    return errors


def get_status_message(report_status):
    """Return the status and reason from the report_status table."""
    status_row = report_status.iloc[0]

    return status_row["status"], status_row["reason"]


def format_money(value):
    """Format a value as money for dashboard display."""
    if pd.isna(value):
        return "$0.00"

    return f"${float(value):,.2f}"


def format_number(value):
    """Format a value as a whole number for dashboard display."""
    if pd.isna(value):
        return "0"

    return f"{int(value):,}"


def divide_safely(numerator, denominator):
    """Divide dashboard values without raising on zero."""
    if pd.isna(denominator) or denominator == 0:
        return 0

    return numerator / denominator


def get_dashboard_metrics(report_tables):
    """Create KPI values for the dashboard from report tables."""
    enriched_orders = report_tables["enriched_orders"]
    monthly = report_tables["monthly_summary"]
    categories = report_tables["category_summary"]
    products = report_tables["top_products"]
    customers = report_tables["customer_summary"]
    anomalies = report_tables["anomalies"]

    total_revenue = (
        enriched_orders["final_revenue"].sum()
        if not enriched_orders.empty
        else 0
    )
    total_orders = (
        enriched_orders["order_id"].nunique()
        if not enriched_orders.empty
        else 0
    )
    total_units = (
        enriched_orders["quantity"].sum()
        if not enriched_orders.empty
        else 0
    )
    overall_aov = divide_safely(total_revenue, total_orders)
    top_category = categories.iloc[0]["category"] if not categories.empty else ""
    top_product = products.iloc[0]["product_name"] if not products.empty else ""
    top_customer = (
        customers.iloc[0]["customer_name"] if not customers.empty else ""
    )
    anomaly_count = len(anomalies)

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "total_units": total_units,
        "overall_aov": overall_aov,
        "top_category": top_category,
        "top_product": top_product,
        "top_customer": top_customer,
        "anomaly_count": anomaly_count,
    }


def show_kpi_cards(report_tables):
    """Show the main KPI cards."""
    metrics = get_dashboard_metrics(report_tables)

    st.subheader("Key Metrics")
    first_row = st.columns(4)
    first_row[0].metric(
        "Total Final Revenue",
        format_money(metrics["total_revenue"]),
    )
    first_row[1].metric("Total Orders", format_number(metrics["total_orders"]))
    first_row[2].metric("Total Units", format_number(metrics["total_units"]))
    first_row[3].metric("Overall AOV", format_money(metrics["overall_aov"]))

    customer_available = customer_analysis_available(report_tables)
    second_row = st.columns(4 if customer_available else 3)
    second_row[0].metric("Top Category", metrics["top_category"] or "N/A")
    second_row[1].metric("Top Product", metrics["top_product"] or "N/A")
    if customer_available:
        second_row[2].metric("Top Customer", metrics["top_customer"] or "N/A")
        second_row[3].metric(
            "Anomaly Count", format_number(metrics["anomaly_count"])
        )
    else:
        second_row[2].metric(
            "Anomaly Count", format_number(metrics["anomaly_count"])
        )


def clean_time_axis(table):
    """Return chart data with year_month converted for Plotly display."""
    chart_data = table.copy()

    if "year_month" in chart_data.columns:
        chart_data["year_month"] = chart_data["year_month"].astype(str)

    return chart_data


def show_monthly_revenue_trend(report_tables):
    """Show monthly revenue as a line chart."""
    monthly = clean_time_axis(report_tables["monthly_summary"])
    anomalies = report_tables["anomalies"]

    st.caption("Use this chart to spot revenue drops or spikes.")

    if monthly.empty:
        st.info("Monthly revenue data is not available.")
        return

    hover_data = {
        "revenue": ":$,.2f",
        "orders": ":,",
        "units": ":,",
        "AOV": ":$,.2f",
    }
    if return_analysis_available(report_tables):
        hover_data["return_rate"] = ":.1%"

    fig = px.line(
        monthly,
        x="year_month",
        y="revenue",
        markers=True,
        title="Monthly Revenue Trend",
        hover_data=hover_data,
    )
    fig.update_yaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title="Month", yaxis_title="Revenue")
    st.plotly_chart(fig, use_container_width=True)

    if (
        not anomalies.empty
        and (anomalies["anomaly_type"] == "sales_drop_over_20_percent").any()
    ):
        st.warning("One or more months had a revenue drop above 20%.")


def show_revenue_by_category(report_tables):
    """Show revenue grouped by category."""
    categories = report_tables["category_summary"].copy()

    st.caption("Use this chart to see which category drives revenue.")

    if categories.empty:
        st.info("Category revenue data is not available.")
        return

    categories = categories.sort_values("revenue", ascending=False)
    fig = px.bar(
        categories,
        x="category",
        y="revenue",
        title="Revenue by Category",
        hover_data={
            "revenue": ":$,.2f",
            "orders": ":,",
            "units": ":,",
            "AOV": ":$,.2f",
        },
    )
    fig.update_xaxes(
        categoryorder="array",
        categoryarray=categories["category"].tolist(),
    )
    fig.update_yaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title="Category", yaxis_title="Revenue")
    st.plotly_chart(fig, use_container_width=True)


def show_top_products_chart(report_tables):
    """Show top products by revenue."""
    products = report_tables["top_products"].copy()

    st.caption("Use this chart to see which products contribute the most.")

    if products.empty:
        st.info("Top product data is not available.")
        return

    products = products.sort_values("revenue", ascending=True)
    fig = px.bar(
        products,
        x="revenue",
        y="product_name",
        orientation="h",
        title="Top Products by Revenue",
        hover_data={
            "revenue": ":$,.2f",
            "orders": ":,",
            "units": ":,",
            "AOV": ":$,.2f",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title="Revenue", yaxis_title="Product")
    st.plotly_chart(fig, use_container_width=True)


def show_top_customers_chart(report_tables):
    """Show top customers by revenue."""
    customers = report_tables["customer_summary"].head(10).copy()

    st.caption("Use this chart to see which customers drive revenue.")

    if customers.empty:
        st.info("Top customer data is not available.")
        return

    customers = customers.sort_values("revenue", ascending=True)
    fig = px.bar(
        customers,
        x="revenue",
        y="customer_name",
        orientation="h",
        title="Top 10 Customers by Revenue",
        hover_data={
            "revenue": ":$,.2f",
            "orders": ":,",
            "units": ":,",
            "AOV": ":$,.2f",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title="Revenue", yaxis_title="Customer")
    st.plotly_chart(fig, use_container_width=True)


def show_monthly_return_rate_chart(report_tables):
    """Show monthly return rate."""
    monthly = clean_time_axis(report_tables["monthly_summary"])

    st.caption("Use this chart to spot months with elevated returns.")

    if monthly.empty:
        st.info("Monthly return rate data is not available.")
        return

    fig = px.bar(
        monthly,
        x="year_month",
        y="return_rate",
        title="Monthly Return Rate",
        hover_data={
            "return_rate": ":.1%",
            "orders": ":,",
            "units": ":,",
            "revenue": ":$,.2f",
        },
    )
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(xaxis_title="Month", yaxis_title="Return Rate")
    st.plotly_chart(fig, use_container_width=True)

    if (monthly["return_rate"] > 0.15).any():
        st.warning("Months above 15% return rate may need review.")


def show_anomalies_by_type_chart(report_tables):
    """Show anomaly count grouped by anomaly type."""
    anomalies = report_tables["anomalies"]

    st.caption("Use this chart to see what kind of issues were detected.")

    if anomalies.empty:
        st.info("No anomalies detected.")
        return

    anomaly_counts = (
        anomalies.groupby("anomaly_type")
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    fig = px.bar(
        anomaly_counts,
        x="anomaly_type",
        y="count",
        title="Anomalies by Type",
        hover_data={"count": ":,"},
    )
    fig.update_layout(xaxis_title="Anomaly Type", yaxis_title="Count")
    st.plotly_chart(fig, use_container_width=True)


def show_income_expense_cash_flow_chart(report_tables):
    """Show income, expenses, and net cash flow over time."""
    cash_flow = clean_time_axis(report_tables["cash_flow_summary"])

    st.caption("Use this chart to compare income, expenses, and cash flow.")

    if cash_flow.empty:
        st.info("Cash flow data is not available.")
        return

    cash_flow_long = cash_flow.melt(
        id_vars="year_month",
        value_vars=["monthly_income", "monthly_expenses", "net_cash_flow"],
        var_name="metric",
        value_name="amount",
    )
    metric_labels = {
        "monthly_income": "Monthly Income",
        "monthly_expenses": "Monthly Expenses",
        "net_cash_flow": "Net Cash Flow",
    }
    cash_flow_long["metric"] = cash_flow_long["metric"].map(metric_labels)

    fig = px.line(
        cash_flow_long,
        x="year_month",
        y="amount",
        color="metric",
        markers=True,
        title="Income vs Expenses vs Net Cash Flow",
        hover_data={"amount": ":$,.2f"},
    )
    fig.update_yaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title="Month", yaxis_title="Amount", legend_title="")
    st.plotly_chart(fig, use_container_width=True)


def show_expenses_by_category_chart(report_tables):
    """Show expenses grouped by category."""
    expenses = report_tables["expense_category_breakdown"].copy()

    st.caption("Use this chart to see where expenses are concentrated.")

    if expenses.empty:
        st.info("Expense category data is not available.")
        return

    expenses = expenses.sort_values("total_expense", ascending=True)
    fig = px.bar(
        expenses,
        x="total_expense",
        y="expense_category",
        orientation="h",
        title="Expenses by Category",
        hover_data={
            "total_expense": ":$,.2f",
            "expense_count": ":,",
            "share_of_expenses": ":.1%",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title="Total Expense", yaxis_title="Expense Category")
    st.plotly_chart(fig, use_container_width=True)


def show_visual_dashboard(report_result):
    """Show Plotly charts for the main report dashboard."""
    report_tables = report_result["report_tables"]

    st.subheader("Visual Dashboard")

    first_left, first_right = st.columns(2)

    with first_left:
        show_monthly_revenue_trend(report_tables)

    with first_right:
        show_revenue_by_category(report_tables)

    second_left, second_right = st.columns(2)

    with second_left:
        show_top_products_chart(report_tables)

    with second_right:
        if customer_analysis_available(report_tables):
            show_top_customers_chart(report_tables)
        else:
            st.info(customer_analysis_unavailable_message(report_tables))

    third_left, third_right = st.columns(2)

    with third_left:
        if return_analysis_available(report_tables):
            show_monthly_return_rate_chart(report_tables)
        else:
            st.info("Return data was not provided. Return analysis was skipped.")

    with third_right:
        show_anomalies_by_type_chart(report_tables)

    if not report_result["expenses_uploaded"]:
        st.info("Expense file was not uploaded, so finance charts are skipped.")
        return

    cash_flow = report_tables["cash_flow_summary"]

    if cash_flow.empty:
        st.info("Finance charts are skipped because cash flow data is empty.")
        return

    finance_left, finance_right = st.columns(2)

    with finance_left:
        show_income_expense_cash_flow_chart(report_tables)

    with finance_right:
        show_expenses_by_category_chart(report_tables)


def validation_checks_passed(report_tables):
    """Return True if validation checks did not fail."""
    validation_report = report_tables["validation_report"]

    if validation_report.empty:
        return False

    return not (validation_report["status"] == "failed").any()


def show_what_happened(report_result):
    """Explain how the uploaded data became the report."""
    st.subheader("What happened?")

    report_tables = report_result["report_tables"]
    data_quality_report = report_tables["data_quality_report"]
    validation_status = (
        "passed"
        if validation_checks_passed(report_tables)
        else "not passed"
    )
    required_columns_status = (
        "present"
        if not data_quality_report["missing_required_columns"]
        else "missing"
    )
    expense_status = (
        "uploaded"
        if report_result["expenses_uploaded"]
        else "not uploaded"
    )

    lines = [
        f"Original uploaded order rows: {report_result['original_row_count']:,}.",
        (
            f"Duplicate review: {report_result['duplicate_group_count']} "
            f"duplicate groups involving {report_result['duplicate_row_count']} rows."
        ),
        (
            f"Selected duplicate rows removed from temporary report input: "
            f"{report_result['removed_row_count']:,}."
        ),
        f"Final rows used for calculation: {report_result['calculation_row_count']:,}.",
        f"Required columns: {required_columns_status}.",
        f"Validation checks: {validation_status}.",
        f"Expense file: {expense_status}.",
    ]

    for line in lines:
        st.write(f"- {line}")


def make_action_required_table(report_result):
    """Create dashboard action rows based on report status and warnings."""
    rows = []
    report_tables = report_result["report_tables"]
    anomalies = report_tables["anomalies"]

    if report_result["status"] == "failed":
        rows.append(
            {
                "Issue": "Report failed",
                "Severity": "Critical",
                "Business Impact": report_result["reason"],
                "Suggested Action": (
                    "Fix the data quality issue, then generate the report again."
                ),
            }
        )

    if (
        report_result["duplicate_group_count"]
        and report_result["removed_row_count"] == 0
    ):
        rows.append(
            {
                "Issue": "Duplicate rows",
                "Severity": "Review",
                "Business Impact": "Revenue may be inflated if the duplicate rows are accidental.",
                "Suggested Action": "Review duplicate rows before using revenue numbers.",
            }
        )

    if not report_result["expenses_uploaded"]:
        rows.append(
            {
                "Issue": "Missing expense file",
                "Severity": "Info",
                "Business Impact": "Cash flow analysis was skipped.",
                "Suggested Action": "Upload expenses.csv if cash flow reporting is needed.",
            }
        )

    if not return_analysis_available(report_tables):
        rows.append(
            {
                "Issue": "Return data unavailable",
                "Severity": "Info",
                "Business Impact": "Return rates and return anomalies were not calculated.",
                "Suggested Action": "Provide a returned field if return analysis is required.",
            }
        )

    if not customer_analysis_available(report_tables):
        rows.append(
            {
                "Issue": "Customer data unavailable",
                "Severity": "Info",
                "Business Impact": "Customer rankings and lifecycle analysis were skipped.",
                "Suggested Action": "Provide customer_id if customer analysis is required.",
            }
        )

    if not anomalies.empty:
        for anomaly_type, count in anomalies["anomaly_type"].value_counts().items():
            rows.append(
                {
                    "Issue": anomaly_type,
                    "Severity": "Warning",
                    "Business Impact": f"{count} anomaly row(s) need review.",
                    "Suggested Action": (
                        "Open the Anomalies detail table and investigate the "
                        "affected rows."
                    ),
                }
            )

    return pd.DataFrame(
        rows,
        columns=["Issue", "Severity", "Business Impact", "Suggested Action"],
    )


def show_action_required(report_result):
    """Show required actions as a compact table."""
    st.subheader("Action Required")
    action_table = make_action_required_table(report_result)

    if action_table.empty:
        st.success("No action required.")
    else:
        st.dataframe(action_table, hide_index=True, use_container_width=True)


def show_business_insights(report_tables):
    """Show the main business takeaways."""
    monthly = report_tables["monthly_summary"]
    categories = report_tables["category_summary"]
    products = report_tables["top_products"]
    customers = report_tables["customer_summary"]
    anomalies = report_tables["anomalies"]

    st.subheader("Business Insights")

    if monthly.empty:
        st.write("- Monthly insight was not generated.")
        return

    strongest_month = monthly.loc[monthly["revenue"].idxmax()]
    weakest_month = monthly.loc[monthly["revenue"].idxmin()]
    top_category = categories.iloc[0] if not categories.empty else None
    top_product = products.iloc[0] if not products.empty else None
    top_customer = customers.iloc[0] if not customers.empty else None

    st.write(
        f"- Strongest month: {strongest_month['year_month']} "
        f"with {format_money(strongest_month['revenue'])} in revenue."
    )
    st.write(
        f"- Weakest month: {weakest_month['year_month']} "
        f"with {format_money(weakest_month['revenue'])} in revenue."
    )

    if top_category is not None:
        st.write(
            f"- Top category: {top_category['category']} "
            f"({format_money(top_category['revenue'])})."
        )

    if top_product is not None:
        st.write(
            f"- Top product: {top_product['product_name']} "
            f"({format_money(top_product['revenue'])})."
        )

    if top_customer is not None:
        st.write(
            f"- Top customer: {top_customer['customer_name']} "
            f"({format_money(top_customer['revenue'])})."
        )

    st.write(f"- Detected anomalies: {len(anomalies):,}.")


def show_table_expander(title, table):
    """Show a detail table only when the user opens an expander."""
    with st.expander(title):
        if table.empty:
            st.info("No rows to display.")
        else:
            st.dataframe(table, hide_index=True, use_container_width=True)


def show_detail_tables(report_result):
    """Show detail tables in collapsed sections."""
    report_tables = report_result["report_tables"]
    data_quality_checks = pd.concat(
        [
            report_tables["data_quality"],
            report_tables["post_conversion_data_quality"].assign(
                section="post_conversion"
            ),
        ],
        ignore_index=True,
        sort=False,
    )

    st.subheader("Detail Tables")
    show_table_expander("Monthly Summary", report_tables["monthly_summary"])
    show_table_expander("Category Summary", report_tables["category_summary"])
    show_table_expander("Top Products", report_tables["top_products"])
    if customer_analysis_available(report_tables):
        show_table_expander("Top Customers", report_tables["customer_summary"])
    show_table_expander(
        "Duplicate Rows Detail",
        report_result["duplicate_rows_detail"],
    )
    show_table_expander("Anomalies", report_tables["anomalies"])
    show_table_expander("Validation Report", report_tables["validation_report"])
    show_table_expander("Data Quality Checks", data_quality_checks)
    if "data_preparation_summary" in report_tables:
        show_table_expander(
            "Data Preparation Summary",
            report_tables["data_preparation_summary"],
        )
    if "field_availability" in report_tables:
        show_table_expander(
            "Field Availability",
            report_tables["field_availability"],
        )
    if "excluded_rows_detail" in report_tables:
        show_table_expander(
            "Excluded Rows Detail",
            report_tables["excluded_rows_detail"],
        )


def show_report_status(status, reason):
    """Display report status with a simple visual state."""
    if status == "ready":
        message = f"{status}: {reason}"
        st.success(message)
    elif status == "review_required":
        message = (
            "Report generated successfully, but some data quality warnings "
            "need review."
        )
        st.warning(message)
        st.caption(f"Reason: {reason}")
    else:
        message = f"{status}: {reason}"
        st.error(message)


def generate_report(
    orders_file,
    expenses_file,
    config_file,
    column_mapping=None,
    source_rows_to_remove=None,
    duplicate_rows_detail=None,
    duplicate_group_count=0,
    duplicate_row_count=0,
):
    """Run the existing analysis pipeline using temporary uploaded files."""
    original_row_count = len(read_uploaded_csv(orders_file))
    removed_row_count = len(source_rows_to_remove or [])

    with TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        orders_path = save_orders_file(
            orders_file,
            temp_dir / "orders.csv",
            source_rows_to_remove,
        )
        calculation_row_count = len(pd.read_csv(orders_path))
        expenses_path = temp_dir / "expenses.csv"
        config_path = None
        excel_path = temp_dir / "sales_report.xlsx"
        summary_path = temp_dir / "summary.md"

        if expenses_file is not None:
            save_uploaded_file(expenses_file, expenses_path)

        uploaded_config_mapping = get_uploaded_config_mapping(config_file)
        final_column_mapping = merge_column_mappings(
            uploaded_config_mapping,
            (column_mapping or {}).get("orders_columns", {}),
        )

        if mapping_has_values(final_column_mapping):
            config_path = temp_dir / "config.json"
            config_path.write_text(
                json.dumps(final_column_mapping, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        report_tables, excel_output, summary_output = run_pipeline(
            csv_path=orders_path,
            expenses_path=expenses_path,
            excel_path=excel_path,
            summary_path=summary_path,
            config_path=config_path,
        )

        status, reason = get_status_message(report_tables["report_status"])
        summary_text = add_duplicate_review_notes(
            summary_output.read_text(encoding="utf-8"),
            duplicate_group_count,
            duplicate_row_count,
            removed_row_count,
        )

        if duplicate_rows_detail is not None and not duplicate_rows_detail.empty:
            detail_for_excel = add_duplicate_counts_to_detail(
                duplicate_rows_detail,
                duplicate_group_count,
                duplicate_row_count,
            )
            replace_duplicate_detail_sheet(excel_output, detail_for_excel)

        return {
            "status": status,
            "reason": reason,
            "expenses_uploaded": expenses_file is not None,
            "report_tables": report_tables,
            "original_row_count": original_row_count,
            "calculation_row_count": calculation_row_count,
            "removed_row_count": removed_row_count,
            "duplicate_group_count": duplicate_group_count,
            "duplicate_row_count": duplicate_row_count,
            "duplicate_rows_detail": add_duplicate_counts_to_detail(
                duplicate_rows_detail,
                duplicate_group_count,
                duplicate_row_count,
            )
            if duplicate_rows_detail is not None
            else pd.DataFrame(),
            "excel_bytes": excel_output.read_bytes(),
            "summary_text": summary_text,
        }


def generate_report_from_unified_orders(unified_orders, expenses_file=None):
    """Generate a report by passing a prepared orders table into run_pipeline."""
    with TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        orders_path = temp_dir / "orders.csv"
        expenses_path = temp_dir / "expenses.csv"
        excel_path = temp_dir / "sales_report.xlsx"
        summary_path = temp_dir / "summary.md"

        unified_orders.to_csv(orders_path, index=False)

        if expenses_file is not None:
            save_uploaded_file(expenses_file, expenses_path)

        report_tables, excel_output, summary_output = run_pipeline(
            csv_path=orders_path,
            expenses_path=expenses_path,
            excel_path=excel_path,
            summary_path=summary_path,
        )

        status, reason = get_status_message(report_tables["report_status"])

        return {
            "status": status,
            "reason": reason,
            "expenses_uploaded": expenses_file is not None,
            "report_tables": report_tables,
            "original_row_count": len(unified_orders),
            "calculation_row_count": len(unified_orders),
            "removed_row_count": 0,
            "duplicate_group_count": 0,
            "duplicate_row_count": 0,
            "duplicate_rows_detail": pd.DataFrame(),
            "excel_bytes": excel_output.read_bytes(),
            "summary_text": summary_output.read_text(encoding="utf-8"),
        }


def show_report_dashboard(report_result):
    """Show the generated report dashboard and downloads."""
    st.divider()
    show_report_status(report_result["status"], report_result["reason"])

    if report_result["duplicate_group_count"]:
        st.info(
            f"Original uploaded data contained "
            f"{report_result['duplicate_group_count']} duplicate groups involving "
            f"{report_result['duplicate_row_count']} rows."
        )

    if report_result["removed_row_count"]:
        st.info(
            f"{report_result['removed_row_count']} selected duplicate row(s) "
            "were removed from the temporary report input. The original "
            "uploaded file was not changed."
        )

    if not report_result["expenses_uploaded"]:
        st.info("Finance Analysis Skipped. Expense file was not uploaded.")

    if report_result.get("report_kind") == "generic":
        st.subheader("Data Preparation Summary")
        st.dataframe(
            report_result["data_preparation_summary"].astype("string"),
            hide_index=True,
            use_container_width=True,
        )
        if report_result.get("excluded_row_count"):
            st.warning(
                f"{report_result['excluded_row_count']:,} row(s) were explicitly "
                "excluded from all report calculations."
            )
        if report_result.get("monthly_analysis_excluded_row_count"):
            st.warning(
                f"{report_result['monthly_analysis_excluded_row_count']:,} row(s) "
                "with invalid dates were excluded from monthly analysis only."
            )
        if not return_analysis_available(report_result["report_tables"]):
            st.info("Return data was not provided. Return analysis was skipped.")
            st.caption(
                "Return adjustments were not applied because return status was unavailable."
            )
        if not customer_analysis_available(report_result["report_tables"]):
            st.info(
                customer_analysis_unavailable_message(
                    report_result["report_tables"]
                )
            )

    show_kpi_cards(report_result["report_tables"])
    show_visual_dashboard(report_result)
    show_what_happened(report_result)
    show_action_required(report_result)
    show_business_insights(report_result["report_tables"])
    show_detail_tables(report_result)

    st.subheader("Downloads")
    st.caption(
        "Excel contains detailed sheets for audit and further analysis. The "
        "dashboard above is the recommended place to review the report."
    )
    download_columns = st.columns(2)

    with download_columns[0]:
        st.download_button(
            "Download Excel Report",
            data=report_result["excel_bytes"],
            file_name="sales_report.xlsx",
            mime=EXCEL_MIME_TYPE,
        )

    with download_columns[1]:
        st.download_button(
            "Download Markdown Summary",
            data=report_result["summary_text"],
            file_name="summary.md",
            mime="text/markdown",
        )


def format_merge_summary_for_display(merge_summary):
    """Create a compact merge summary for the Streamlit review table."""
    if merge_summary.empty:
        return merge_summary

    display = merge_summary[
        [
            "right_table",
            "before_row_count",
            "after_row_count",
            "unmatched_count",
            "match_rate",
            "row_inflation",
        ]
    ].copy()
    display = display.rename(
        columns={
            "before_row_count": "before",
            "after_row_count": "after",
            "unmatched_count": "unmatched",
        }
    )
    display["match_rate"] = display["match_rate"].apply(
        lambda value: "N/A" if pd.isna(value) else f"{value:.2%}"
    )

    return display


def multi_table_has_blocking_issues(multi_table_result):
    """Return True when prepared multi-table data should not generate a report."""
    merge_summary = multi_table_result["merge_summary"]
    quality_warnings = multi_table_result["quality_warnings"]

    if not merge_summary.empty and merge_summary["row_inflation"].fillna(False).any():
        return True

    if quality_warnings.empty:
        return False

    blocking_severities = {"error", "critical"}

    return quality_warnings["severity"].str.lower().isin(blocking_severities).any()


def show_multi_table_prepare_result(multi_table_result):
    """Show merge diagnostics and unified orders preview for multi-table mode."""
    source_summary = multi_table_result["source_table_summary"]
    merge_summary = multi_table_result["merge_summary"]
    quality_warnings = multi_table_result["quality_warnings"]
    unified_orders = multi_table_result["unified_orders"]

    st.subheader("Step 3: Review Merge & Quality")

    st.markdown("### Source Table Summary")
    st.dataframe(
        source_summary[["table_name", "row_count", "column_count"]],
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("### Merge Summary")
    merge_display = format_merge_summary_for_display(merge_summary)
    st.dataframe(merge_display, hide_index=True, use_container_width=True)

    if not merge_summary.empty and merge_summary["row_inflation"].fillna(False).any():
        st.error("Row inflation was detected. Report generation is blocked.")

    st.markdown("### Data Quality Warnings")

    if quality_warnings.empty:
        st.success("No multi-table data quality warnings were found.")
    else:
        if multi_table_has_blocking_issues(multi_table_result):
            st.error("Blocking data quality issues were found.")
        else:
            st.warning("Data quality warnings were found. Review them before using the report.")

        st.dataframe(quality_warnings, hide_index=True, use_container_width=True)

    st.markdown("### Unified Orders Preview")
    st.write(f"Final unified order rows: {len(unified_orders):,}")
    st.dataframe(
        unified_orders.head(20),
        hide_index=True,
        use_container_width=True,
    )


def show_multi_table_upload_summaries(uploaded_files):
    """Show summaries and previews for uploaded multi-table CSV files."""
    st.markdown("#### Uploaded Table Previews")

    for table_name, uploaded_file in uploaded_files.items():
        show_uploaded_table_summary(uploaded_file, table_name)


st.set_page_config(page_title="Sales Report Generator", layout="wide")

st.title("Sales Report Generator")


def render_single_table_mode():
    """Render the existing single-table upload and report flow."""
    orders_file = st.file_uploader(
        "orders.csv (required)",
        type=["csv"],
        key="single_orders_file",
    )
    expenses_file = st.file_uploader(
        "expenses.csv (optional)",
        type=["csv"],
        key="single_expenses_file",
    )

    with st.expander("Advanced"):
        config_file = st.file_uploader(
            "config.json (optional)",
            type=["json"],
            key="single_config_file",
        )

    orders_columns = []
    missing_required_columns = []
    config_mapping = {"orders_columns": {}, "expenses_columns": {}}
    ui_orders_mapping = {}
    column_mapping_errors = []
    duplicate_rows_to_remove = []
    duplicate_rows_preview = pd.DataFrame()
    duplicate_group_count = 0
    duplicate_row_count = 0
    header_read_error = None
    config_read_error = None
    duplicate_preview_error = None

    if orders_file is not None:
        try:
            orders_columns = read_csv_columns(orders_file)
            missing_required_columns = get_missing_required_columns(orders_columns)
        except Exception as error:
            header_read_error = f"Could not read orders.csv header: {error}"

    if config_file is not None:
        try:
            config_mapping = get_uploaded_config_mapping(config_file)
        except ValueError as error:
            config_read_error = str(error)

    if header_read_error:
        st.error(header_read_error)

    if config_read_error:
        st.error(config_read_error)

    if orders_columns:
        st.subheader("Uploaded Columns")
        st.dataframe(
            pd.DataFrame({"column": orders_columns}),
            hide_index=True,
            use_container_width=True,
        )

        st.subheader("Column Mapping")

        required_selections = {}
        optional_selections = {}

        if missing_required_columns:
            st.warning(
                "Some required columns were not found directly. Map them before "
                "generating the report."
            )

            if "date" in missing_required_columns:
                st.info("Monthly trend analysis requires a date column.")

            for required_column in missing_required_columns:
                options = [SELECT_COLUMN]

                if required_column == "product_id" and "product_name" in orders_columns:
                    options.append(AUTO_PRODUCT_NAME)

                options.extend(orders_columns)
                default_selection = get_default_required_selection(
                    required_column,
                    orders_columns,
                    config_mapping,
                )

                if default_selection not in options:
                    default_selection = SELECT_COLUMN

                required_selections[required_column] = st.selectbox(
                    required_column,
                    options,
                    index=options.index(default_selection),
                    key=f"required_mapping_{required_column}",
                )
        else:
            st.success("All required columns were found directly.")

        with st.expander("Optional order columns"):
            for optional_column in OPTIONAL_ORDER_COLUMNS:
                if optional_column in orders_columns:
                    st.caption(f"{optional_column} was found directly.")
                    continue

                options = [DO_NOT_MAP] + orders_columns
                default_selection = get_default_optional_selection(
                    optional_column,
                    orders_columns,
                    config_mapping,
                )

                if default_selection not in options:
                    default_selection = DO_NOT_MAP

                optional_selections[optional_column] = st.selectbox(
                    optional_column,
                    options,
                    index=options.index(default_selection),
                    key=f"optional_mapping_{optional_column}",
                )

        ui_orders_mapping = build_orders_mapping(
            required_selections,
            optional_selections,
        )
        final_mapping = merge_column_mappings(config_mapping, ui_orders_mapping)
        column_mapping_errors = validate_orders_mapping(
            orders_columns,
            missing_required_columns,
            final_mapping,
        )

        try:
            duplicate_rows_preview = make_duplicate_rows_preview(orders_file)
            duplicate_group_count, duplicate_row_count = get_duplicate_review_counts(
                duplicate_rows_preview
            )
        except Exception as error:
            duplicate_rows_preview = pd.DataFrame()
            duplicate_preview_error = f"Could not review duplicate rows: {error}"

        if duplicate_preview_error:
            st.warning(duplicate_preview_error)
        elif not duplicate_rows_preview.empty:
            st.subheader("Duplicate Row Review")
            st.warning(
                f"Found {duplicate_group_count} duplicate groups involving "
                f"{duplicate_row_count} rows."
            )
            st.caption(
                "Duplicate rows are not removed automatically. Review the full "
                "row details below and decide whether to keep all rows or remove "
                "selected source row numbers before generating the report."
            )
            st.dataframe(
                duplicate_rows_preview,
                hide_index=True,
                use_container_width=True,
            )

            duplicate_action = st.radio(
                "How should duplicate rows be handled?",
                [
                    "Keep all duplicate rows",
                    "Remove selected rows before generating report",
                ],
                index=0,
            )

            if duplicate_action == "Remove selected rows before generating report":
                duplicate_options = duplicate_rows_preview[
                    "source_row_number"
                ].astype(int).tolist()
                duplicate_rows_to_remove = st.multiselect(
                    "Select source_row_number rows to remove",
                    duplicate_options,
                )

                if duplicate_rows_to_remove:
                    st.info(
                        f"{len(duplicate_rows_to_remove)} selected row(s) will be "
                        "removed from the temporary report input. The uploaded file "
                        "itself will not be changed."
                    )
                else:
                    st.info("No duplicate rows are currently selected for removal.")
    else:
        final_mapping = config_mapping

    submitted = st.button("Generate Report", key="single_generate_report")

    if submitted:
        st.session_state.pop("report_result", None)

        if orders_file is None:
            st.error("orders.csv is required.")
        elif header_read_error:
            st.error(header_read_error)
        elif config_read_error:
            st.error(config_read_error)
        elif column_mapping_errors:
            for error in column_mapping_errors:
                st.error(error)
        else:
            try:
                with st.spinner("Generating report..."):
                    st.session_state["report_result"] = generate_report(
                        orders_file,
                        expenses_file,
                        config_file,
                        final_mapping,
                        duplicate_rows_to_remove,
                        duplicate_rows_preview,
                        duplicate_group_count,
                        duplicate_row_count,
                    )
            except Exception as error:
                st.error(f"Could not generate report: {error}")
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    report_result = st.session_state.get("report_result")

    if report_result:
        show_report_dashboard(report_result)


def render_multi_table_mode():
    """Render Maven-style multi-table upload, merge, and report flow."""
    st.subheader("Step 1: Upload Tables")

    sales_file = st.file_uploader(
        "Sales.csv (required)",
        type=["csv"],
        key="multi_sales_file",
    )
    products_file = st.file_uploader(
        "Products.csv (required)",
        type=["csv"],
        key="multi_products_file",
    )
    customers_file = st.file_uploader(
        "Customers.csv (optional)",
        type=["csv"],
        key="multi_customers_file",
    )
    stores_file = st.file_uploader(
        "Stores.csv (optional)",
        type=["csv"],
        key="multi_stores_file",
    )
    exchange_rates_file = st.file_uploader(
        "Exchange_Rates.csv (optional)",
        type=["csv"],
        key="multi_exchange_rates_file",
    )
    expenses_file = st.file_uploader(
        "expenses.csv (optional)",
        type=["csv"],
        key="multi_expenses_file",
    )

    uploaded_files = {
        "Sales": sales_file,
        "Products": products_file,
        "Customers": customers_file,
        "Stores": stores_file,
        "Exchange_Rates": exchange_rates_file,
    }
    upload_signature = make_multi_table_upload_signature(uploaded_files)
    clear_multi_table_state_if_uploads_changed(upload_signature)
    expenses_signature = get_uploaded_file_signature(expenses_file)

    if st.session_state.get("multi_expenses_signature") != expenses_signature:
        st.session_state["multi_expenses_signature"] = expenses_signature
        st.session_state.pop("report_result", None)

    show_multi_table_upload_summaries(uploaded_files)

    missing_required_files = []

    if sales_file is None:
        missing_required_files.append("Sales.csv")

    if products_file is None:
        missing_required_files.append("Products.csv")

    if missing_required_files:
        st.warning(
            "Required file(s) missing: " + ", ".join(missing_required_files)
        )

    st.subheader("Step 2: Prepare Multi-table Dataset")
    prepare_clicked = st.button(
        "Prepare Multi-table Dataset",
        key="prepare_multi_table_dataset",
    )

    if prepare_clicked:
        st.session_state.pop("report_result", None)

        if missing_required_files:
            st.error(
                "Cannot prepare dataset. Missing required file(s): "
                + ", ".join(missing_required_files)
            )
        else:
            try:
                with st.spinner("Preparing multi-table dataset..."):
                    st.session_state["multi_table_result"] = load_multi_table_dataset(
                        sales_source=sales_file,
                        products_source=products_file,
                        customers_source=customers_file,
                        stores_source=stores_file,
                        exchange_rates_source=exchange_rates_file,
                    )
                st.success("Multi-table dataset prepared successfully.")
            except MultiTableLoaderError as error:
                st.session_state.pop("multi_table_result", None)
                st.error(str(error))
            except Exception as error:
                st.session_state.pop("multi_table_result", None)
                st.error(f"Could not prepare multi-table dataset: {error}")
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    multi_table_result = st.session_state.get("multi_table_result")

    if multi_table_result:
        show_multi_table_prepare_result(multi_table_result)

        blocking_issues = multi_table_has_blocking_issues(multi_table_result)

        st.subheader("Step 4: Generate Report")

        if blocking_issues:
            st.error(
                "Report generation is blocked until merge or data quality errors "
                "are fixed."
            )

        generate_clicked = st.button(
            "Generate Report",
            key="multi_generate_report",
            disabled=blocking_issues,
        )

        if generate_clicked:
            st.session_state.pop("report_result", None)

            try:
                with st.spinner("Generating report..."):
                    st.session_state["report_result"] = generate_report_from_unified_orders(
                        multi_table_result["unified_orders"],
                        expenses_file,
                    )
            except Exception as error:
                st.error(f"Could not generate report: {error}")
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    report_result = st.session_state.get("report_result")

    if report_result:
        show_report_dashboard(report_result)


mode = st.radio(
    "Data Import Mode",
    [
        "Single Table Mode",
        "Multi-table Dataset Mode",
        "Generic Relationship Mode",
    ],
    index=0,
    horizontal=True,
)

if st.session_state.get("active_import_mode") != mode:
    st.session_state["active_import_mode"] = mode
    st.session_state.pop("report_result", None)

if mode == "Single Table Mode":
    render_single_table_mode()
elif mode == "Multi-table Dataset Mode":
    render_multi_table_mode()
else:
    generic_report_result = render_generic_relationship_mode()
    if generic_report_result is not None:
        show_report_dashboard(generic_report_result)
