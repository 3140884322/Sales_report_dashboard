import pandas as pd
import plotly.express as px
import streamlit as st

from generic_relationship_ui import render_generic_relationship_mode
from generic_report_generation import (
    customer_analysis_available,
    customer_analysis_unavailable_message,
    return_analysis_available,
)


EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


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
    if "is_partial_period" in monthly.columns:
        hover_data["is_partial_period"] = True
        hover_data["partial_reason"] = True
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

    label_column = (
        "anomaly_label" if "anomaly_label" in anomalies.columns else "anomaly_type"
    )
    anomaly_counts = (
        anomalies.groupby(label_column)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    fig = px.bar(
        anomaly_counts,
        x=label_column,
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
    """Create business and data-quality issues that require review."""
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

    if not anomalies.empty:
        for _, anomaly in anomalies.iterrows():
            rows.append(
                {
                    "Issue": anomaly.get(
                        "anomaly_label", anomaly["anomaly_type"]
                    ),
                    "Severity": "Warning",
                    "Business Impact": anomaly["details"],
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


def make_data_limitations_table(report_result):
    """Create optional-data limitations that do not imply a business problem."""
    rows = []
    report_tables = report_result["report_tables"]
    if not report_result["expenses_uploaded"]:
        rows.append(
            {
                "Limitation": "Expense data was not provided",
                "Impact": "Finance and cash-flow analysis was skipped.",
            }
        )
    if not return_analysis_available(report_tables):
        rows.append(
            {
                "Limitation": "Return data was not provided",
                "Impact": "Return rates and return anomalies were skipped.",
            }
        )
    if not customer_analysis_available(report_tables):
        rows.append(
            {
                "Limitation": customer_analysis_unavailable_message(report_tables),
                "Impact": "Customer rankings and lifecycle analysis were skipped.",
            }
        )
    rows.append(
        {
            "Limitation": "Cost data was not provided",
            "Impact": "Gross-margin analysis is not available.",
        }
    )
    return pd.DataFrame(rows, columns=["Limitation", "Impact"])


def show_action_required(report_result):
    """Separate business issues from optional-data limitations."""
    st.subheader("Business Issues Requiring Review")
    action_table = make_action_required_table(report_result)

    if action_table.empty:
        st.success("No business issues require review.")
    else:
        st.dataframe(action_table, hide_index=True, use_container_width=True)

    st.subheader("Data Availability and Limitations")
    limitations = make_data_limitations_table(report_result)
    if limitations.empty:
        st.success("No material data limitations were identified.")
    else:
        st.dataframe(limitations, hide_index=True, use_container_width=True)


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

    complete_months = (
        monthly.loc[~monthly["is_partial_period"].fillna(False)]
        if "is_partial_period" in monthly.columns
        else monthly
    )
    strongest_month = (
        complete_months.loc[complete_months["revenue"].idxmax()]
        if not complete_months.empty
        else None
    )
    weakest_month = (
        complete_months.loc[complete_months["revenue"].idxmin()]
        if not complete_months.empty
        else None
    )
    top_category = categories.iloc[0] if not categories.empty else None
    top_product = products.iloc[0] if not products.empty else None
    top_customer = customers.iloc[0] if not customers.empty else None

    if strongest_month is not None:
        st.write(
            f"- Strongest complete month: {strongest_month['year_month']} "
            f"with {format_money(strongest_month['revenue'])} in revenue."
        )
        st.write(
            f"- Weakest complete month: {weakest_month['year_month']} "
            f"with {format_money(weakest_month['revenue'])} in revenue."
        )
    else:
        st.write("- No complete calendar month was available for ranking.")

    if "is_partial_period" in monthly.columns:
        for reason in monthly.loc[
            monthly["is_partial_period"].fillna(False), "partial_reason"
        ]:
            st.write(f"- {reason}.")

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
    anomaly_display = report_tables["anomalies"].drop(
        columns=["anomaly_type"], errors="ignore"
    )
    show_table_expander("Anomalies", anomaly_display)
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


st.set_page_config(page_title="Sales Report Generator", layout="wide")

st.title("Upload Sales Data")
st.write(
    "Upload one or more CSV/XLSX files containing sales, orders, products, "
    "customers, stores, or related business data. The system will identify "
    "how the data is organized and guide the user through the required steps."
)

report_result = render_generic_relationship_mode()
if report_result is not None:
    show_report_dashboard(report_result)
