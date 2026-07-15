import pandas as pd
import plotly.express as px
import streamlit as st

from generic_relationship_ui import render_generic_relationship_mode
from generic_report_generation import (
    customer_analysis_available,
    customer_analysis_unavailable_message,
    get_field_availability_notes,
    get_field_availability_status,
    return_analysis_available,
)
from generic_store_analysis import (
    store_analysis_available,
    valid_store_summary,
)
from ui_guidance import (
    render_glossary,
    render_step_guide,
    render_workflow_progress,
)
from ui_i18n import render_language_selector, t


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


def _customer_unavailable_display(report_tables):
    status = get_field_availability_status(report_tables, "customer_id")
    if status == "partially_provided":
        return t("report.customer_partial")
    if status == "mapping_conflict":
        return get_field_availability_notes(report_tables, "customer_id")
    return t("report.customer_not_provided")


def _return_unavailable_display(report_tables):
    status = get_field_availability_status(report_tables, "returned")
    if status == "not_applicable":
        return t("report.return_not_applicable")
    return t("report.return_not_provided")


def get_dashboard_metrics(report_tables):
    """Create KPI values for the dashboard from report tables."""
    enriched_orders = report_tables["enriched_orders"]
    monthly = report_tables["monthly_summary"]
    categories = report_tables["category_summary"]
    products = report_tables["top_products"]
    customers = report_tables["customer_summary"]
    anomalies = report_tables["anomalies"]
    stores = valid_store_summary(report_tables.get("store_summary"))

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
    top_store = stores.iloc[0]["store_name"] if not stores.empty else ""
    anomaly_count = len(anomalies)

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "total_units": total_units,
        "overall_aov": overall_aov,
        "top_category": top_category,
        "top_product": top_product,
        "top_customer": top_customer,
        "top_store": top_store,
        "anomaly_count": anomaly_count,
    }


def show_kpi_cards(report_tables):
    """Show the main KPI cards."""
    metrics = get_dashboard_metrics(report_tables)

    st.subheader(t("report.key_metrics"))
    first_row = st.columns(4)
    first_row[0].metric(
        t("report.total_revenue"),
        format_money(metrics["total_revenue"]),
    )
    first_row[1].metric(t("report.total_orders"), format_number(metrics["total_orders"]))
    first_row[2].metric(t("report.total_units"), format_number(metrics["total_units"]))
    first_row[3].metric(t("report.aov"), format_money(metrics["overall_aov"]))

    secondary_metrics = [
        (t("report.top_category"), metrics["top_category"] or t("common.not_available")),
        (t("report.top_product"), metrics["top_product"] or t("common.not_available")),
    ]
    if customer_analysis_available(report_tables):
        secondary_metrics.append((t("report.top_customer"), metrics["top_customer"] or t("common.not_available")))
    if store_analysis_available(report_tables):
        secondary_metrics.append((t("report.top_store"), metrics["top_store"] or t("common.not_available")))
    secondary_metrics.append(
        (t("report.anomalies"), format_number(metrics["anomaly_count"]))
    )
    for start in range(0, len(secondary_metrics), 4):
        row_metrics = secondary_metrics[start : start + 4]
        columns = st.columns(len(row_metrics))
        for column, (label, value) in zip(columns, row_metrics):
            column.metric(label, value)


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

    st.caption(t("report.monthly_caption"))

    if monthly.empty:
        st.info(t("report.no_monthly_data"))
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
        title=t("chart.monthly_revenue"),
        hover_data=hover_data,
    )
    fig.update_yaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title=t("axis.month"), yaxis_title=t("axis.revenue"))
    st.plotly_chart(fig, use_container_width=True)

    if (
        not anomalies.empty
        and (anomalies["anomaly_type"] == "sales_drop_over_20_percent").any()
    ):
        st.warning(t("report.revenue_drop_warning"))


def show_revenue_by_category(report_tables):
    """Show revenue grouped by category."""
    categories = report_tables["category_summary"].copy()

    st.caption(t("report.category_caption"))

    if categories.empty:
        st.info(t("report.no_category_data"))
        return

    categories = categories.sort_values("revenue", ascending=False)
    fig = px.bar(
        categories,
        x="category",
        y="revenue",
        title=t("chart.category_revenue"),
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
    fig.update_layout(xaxis_title=t("axis.category"), yaxis_title=t("axis.revenue"))
    st.plotly_chart(fig, use_container_width=True)


def show_top_products_chart(report_tables):
    """Show top products by revenue."""
    products = report_tables["top_products"].copy()

    st.caption(t("report.product_caption"))

    if products.empty:
        st.info(t("report.no_product_data"))
        return

    products = products.sort_values("revenue", ascending=True)
    fig = px.bar(
        products,
        x="revenue",
        y="product_name",
        orientation="h",
        title=t("chart.top_products"),
        hover_data={
            "revenue": ":$,.2f",
            "orders": ":,",
            "units": ":,",
            "AOV": ":$,.2f",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title=t("axis.revenue"), yaxis_title=t("axis.product"))
    st.plotly_chart(fig, use_container_width=True)


def show_top_customers_chart(report_tables):
    """Show top customers by revenue."""
    customers = report_tables["customer_summary"].head(10).copy()

    st.caption(t("report.customer_caption"))

    if customers.empty:
        st.info(t("report.no_customer_data"))
        return

    customers = customers.sort_values("revenue", ascending=True)
    fig = px.bar(
        customers,
        x="revenue",
        y="customer_name",
        orientation="h",
        title=t("chart.top_customers"),
        hover_data={
            "revenue": ":$,.2f",
            "orders": ":,",
            "units": ":,",
            "AOV": ":$,.2f",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title=t("axis.revenue"), yaxis_title=t("axis.customer"))
    st.plotly_chart(fig, use_container_width=True)


def show_store_performance_chart(report_tables):
    """Show revenue and operating context for each assigned store."""
    stores = report_tables["store_summary"].sort_values(
        "revenue", ascending=True
    )
    if stores.empty:
        return
    if get_field_availability_status(report_tables, "store_analysis") == "partially_provided":
        st.info(t("report.store_partial"))
    fig = px.bar(
        stores,
        x="revenue",
        y="store_name",
        orientation="h",
        title=t("chart.store_revenue"),
        hover_data={
            "revenue": ":$,.2f",
            "orders": ":,",
            "units": ":,",
            "aov": ":$,.2f",
            "revenue_share": ":.1%",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title=t("axis.revenue"), yaxis_title=t("axis.store"))
    st.plotly_chart(fig, use_container_width=True)


def show_monthly_return_rate_chart(report_tables):
    """Show monthly return rate."""
    monthly = clean_time_axis(report_tables["monthly_summary"])

    st.caption(t("report.return_caption"))

    if monthly.empty:
        st.info(t("report.no_return_data"))
        return

    fig = px.bar(
        monthly,
        x="year_month",
        y="return_rate",
        title=t("chart.monthly_returns"),
        hover_data={
            "return_rate": ":.1%",
            "orders": ":,",
            "units": ":,",
            "revenue": ":$,.2f",
        },
    )
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(xaxis_title=t("axis.month"), yaxis_title=t("axis.return_rate"))
    st.plotly_chart(fig, use_container_width=True)

    if (monthly["return_rate"] > 0.15).any():
        st.warning(t("report.return_rate_warning"))


def show_anomalies_by_type_chart(report_tables):
    """Show anomaly count grouped by anomaly type."""
    anomalies = report_tables["anomalies"]

    st.caption(t("report.anomaly_caption"))

    if anomalies.empty:
        st.info(t("report.no_anomalies"))
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
        title=t("chart.anomalies"),
        hover_data={"count": ":,"},
    )
    fig.update_layout(xaxis_title=t("axis.anomaly_type"), yaxis_title=t("axis.count"))
    st.plotly_chart(fig, use_container_width=True)


def show_income_expense_cash_flow_chart(report_tables):
    """Show income, expenses, and net cash flow over time."""
    cash_flow = clean_time_axis(report_tables["cash_flow_summary"])

    st.caption(t("report.cashflow_caption"))

    if cash_flow.empty:
        st.info(t("report.no_cash_flow"))
        return

    cash_flow_long = cash_flow.melt(
        id_vars="year_month",
        value_vars=["monthly_income", "monthly_expenses", "net_cash_flow"],
        var_name="metric",
        value_name="amount",
    )
    metric_labels = {
        "monthly_income": t("report.cashflow.income"),
        "monthly_expenses": t("report.cashflow.expenses"),
        "net_cash_flow": t("report.cashflow.net"),
    }
    cash_flow_long["metric"] = cash_flow_long["metric"].map(metric_labels)

    fig = px.line(
        cash_flow_long,
        x="year_month",
        y="amount",
        color="metric",
        markers=True,
        title=t("chart.cash_flow"),
        hover_data={"amount": ":$,.2f"},
    )
    fig.update_yaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title=t("axis.month"), yaxis_title=t("axis.amount"), legend_title="")
    st.plotly_chart(fig, use_container_width=True)


def show_expenses_by_category_chart(report_tables):
    """Show expenses grouped by category."""
    expenses = report_tables["expense_category_breakdown"].copy()

    st.caption(t("report.expense_caption"))

    if expenses.empty:
        st.info(t("report.no_expense_category"))
        return

    expenses = expenses.sort_values("total_expense", ascending=True)
    fig = px.bar(
        expenses,
        x="total_expense",
        y="expense_category",
        orientation="h",
        title=t("chart.expenses"),
        hover_data={
            "total_expense": ":$,.2f",
            "expense_count": ":,",
            "share_of_expenses": ":.1%",
        },
    )
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    fig.update_layout(xaxis_title=t("axis.amount"), yaxis_title=t("axis.expense_category"))
    st.plotly_chart(fig, use_container_width=True)


def show_visual_dashboard(report_result):
    """Show Plotly charts for the main report dashboard."""
    report_tables = report_result["report_tables"]

    st.subheader(t("report.visual_dashboard"))

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
            st.info(_customer_unavailable_display(report_tables))

    third_left, third_right = st.columns(2)

    with third_left:
        if return_analysis_available(report_tables):
            show_monthly_return_rate_chart(report_tables)
        else:
            st.info(_return_unavailable_display(report_tables))

    with third_right:
        show_anomalies_by_type_chart(report_tables)

    if store_analysis_available(report_tables):
        st.subheader(t("report.store_analysis"))
        show_store_performance_chart(report_tables)

    if not report_result["expenses_uploaded"]:
        st.info(t("report.finance_skipped"))
        return

    cash_flow = report_tables["cash_flow_summary"]

    if cash_flow.empty:
        st.info(t("report.no_cash_flow"))
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
    st.subheader(t("report.what_happened"))

    report_tables = report_result["report_tables"]
    data_quality_report = report_tables["data_quality_report"]
    validation_status = (
        t("report.status_value.passed")
        if validation_checks_passed(report_tables)
        else t("report.status_value.not_passed")
    )
    required_columns_status = (
        t("report.status_value.present")
        if not data_quality_report["missing_required_columns"]
        else t("report.status_value.missing")
    )
    expense_status = (
        t("report.status_value.uploaded")
        if report_result["expenses_uploaded"]
        else t("report.status_value.not_uploaded")
    )

    lines = [
        t("report.process.original", count=f"{report_result['original_row_count']:,}"),
        t("report.process.duplicates", groups=report_result["duplicate_group_count"], rows=report_result["duplicate_row_count"]),
        t("report.process.removed", count=f"{report_result['removed_row_count']:,}"),
        t("report.process.calculation", count=f"{report_result['calculation_row_count']:,}"),
        t("report.process.required", status=required_columns_status),
        t("report.process.validation", status=validation_status),
        t("report.process.expenses", status=expense_status),
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
    if get_field_availability_status(report_tables, "returned") == "not_provided":
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
    st.subheader(t("report.business_issues"))
    action_table = make_action_required_table(report_result)

    if action_table.empty:
        st.success(t("report.no_business_issues"))
    else:
        st.dataframe(
            action_table,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Issue": t("report.column.issue"),
                "Severity": t("report.column.severity"),
                "Business Impact": t("report.column.business_impact"),
                "Suggested Action": t("report.column.suggested_action"),
            },
        )

    st.subheader(t("report.limitations"))
    limitations = make_data_limitations_table(report_result)
    if limitations.empty:
        st.success(t("report.no_limitations"))
    else:
        st.dataframe(
            limitations,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Limitation": t("report.column.limitation"),
                "Impact": t("report.column.impact"),
            },
        )


def show_business_insights(report_tables):
    """Show the main business takeaways."""
    monthly = report_tables["monthly_summary"]
    categories = report_tables["category_summary"]
    products = report_tables["top_products"]
    customers = report_tables["customer_summary"]
    anomalies = report_tables["anomalies"]

    st.subheader(t("report.insights"))

    if monthly.empty:
        st.write(f"- {t('report.no_monthly')}")
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
    stores = valid_store_summary(report_tables.get("store_summary"))

    if strongest_month is not None:
        strongest_text = t(
            "report.insight.strongest",
            month=strongest_month["year_month"],
            revenue=format_money(strongest_month["revenue"]),
        )
        weakest_text = t(
            "report.insight.weakest",
            month=weakest_month["year_month"],
            revenue=format_money(weakest_month["revenue"]),
        )
        st.write(f"- {strongest_text}")
        st.write(f"- {weakest_text}")
    else:
        st.write(f"- {t('report.no_complete_month')}")

    if "is_partial_period" in monthly.columns:
        for reason in monthly.loc[
            monthly["is_partial_period"].fillna(False), "partial_reason"
        ]:
            st.write(f"- {reason}.")

    if top_category is not None:
        st.write(
            f"- {t('report.insight.top_category', name=top_category['category'], revenue=format_money(top_category['revenue']))}"
        )

    if top_product is not None:
        st.write(
            f"- {t('report.insight.top_product', name=top_product['product_name'], revenue=format_money(top_product['revenue']))}"
        )

    if top_customer is not None:
        st.write(
            f"- {t('report.insight.top_customer', name=top_customer['customer_name'], revenue=format_money(top_customer['revenue']))}"
        )

    if len(stores) >= 2:
        top_store = stores.iloc[0]
        lowest_store = stores.iloc[-1]
        top_store_text = t(
            "report.insight.top_store",
            name=top_store["store_name"],
            revenue=format_money(top_store["revenue"]),
            share=f"{top_store['revenue_share']:.1%}",
        )
        lowest_store_text = t(
            "report.insight.lowest_store",
            name=lowest_store["store_name"],
            revenue=format_money(lowest_store["revenue"]),
        )
        st.write(f"- {top_store_text}")
        st.write(f"- {lowest_store_text}")

    st.write(f"- {t('report.detected_anomalies', count=f'{len(anomalies):,}')}")


def show_table_expander(title, table):
    """Show a detail table only when the user opens an expander."""
    with st.expander(title):
        if table.empty:
            st.info(t("common.no_rows"))
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

    st.subheader(t("report.details"))
    show_table_expander(t("detail.monthly"), report_tables["monthly_summary"])
    show_table_expander(t("detail.category"), report_tables["category_summary"])
    show_table_expander(t("detail.products"), report_tables["top_products"])
    if store_analysis_available(report_tables):
        show_table_expander(t("detail.store"), report_tables["store_summary"])
    if customer_analysis_available(report_tables):
        show_table_expander(t("detail.customers"), report_tables["customer_summary"])
    show_table_expander(
        t("detail.duplicates"),
        report_result["duplicate_rows_detail"],
    )
    anomaly_display = report_tables["anomalies"].drop(
        columns=["anomaly_type"], errors="ignore"
    )
    show_table_expander(t("detail.anomalies"), anomaly_display)
    show_table_expander(t("detail.validation"), report_tables["validation_report"])
    show_table_expander(t("detail.quality"), data_quality_checks)
    if "data_preparation_summary" in report_tables:
        show_table_expander(
            t("detail.preparation"),
            report_tables["data_preparation_summary"],
        )
    if "field_availability" in report_tables:
        show_table_expander(
            t("detail.availability"),
            report_tables["field_availability"],
        )
    if "report_coverage" in report_tables:
        show_table_expander(
            t("detail.coverage"),
            report_tables["report_coverage"],
        )
    if "excluded_rows_detail" in report_tables:
        show_table_expander(
            t("detail.excluded"),
            report_tables["excluded_rows_detail"],
        )


def show_report_status(status, reason):
    """Display report status with a simple visual state."""
    if status == "ready":
        message = f"{t('report.status.ready')}: {t('report.status.ready_message')}"
        st.success(message)
    elif status == "review_required":
        message = f"{t('report.status.review_required')}: {t('report.status.review_message')}"
        st.warning(message)
        st.caption(f"{t('common.reason')}: {reason}")
    else:
        message = f"{t('report.status.failed')}: {t('report.status.failed_message')}"
        st.error(message)
        st.caption(f"{t('common.reason')}: {reason}")


def show_report_dashboard(report_result):
    """Show the generated report dashboard and downloads."""
    st.divider()
    render_step_guide(8)
    with st.expander(t("report.read.title"), expanded=True):
        st.markdown(t("report.read.body"))
    show_report_status(report_result["status"], report_result["reason"])

    if report_result["duplicate_group_count"]:
        st.info(t(
            "report.duplicate_notice",
            groups=report_result["duplicate_group_count"],
            rows=report_result["duplicate_row_count"],
        ))

    if report_result["removed_row_count"]:
        st.info(t("report.removed_notice", count=report_result["removed_row_count"]))

    if not report_result["expenses_uploaded"]:
        st.info(t("report.finance_skipped"))

    if report_result.get("report_kind") == "generic":
        st.subheader(t("report.data_preparation"))
        st.dataframe(
            report_result["data_preparation_summary"].astype("string"),
            hide_index=True,
            use_container_width=True,
            column_config={
                "section": t("table.column.section"),
                "item": t("table.column.item"),
                "value": t("table.column.value"),
                "notes": t("table.column.notes"),
            },
        )
        if "report_coverage" in report_result["report_tables"]:
            st.subheader(t("report.coverage"))
            st.dataframe(
                report_result["report_tables"]["report_coverage"],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "analysis": t("coverage.column.analysis"),
                    "coverage_status": t("coverage.column.status"),
                    "notes": t("table.column.notes"),
                },
            )
        if report_result.get("excluded_row_count"):
            st.warning(t(
                "report.excluded_notice",
                count=f"{report_result['excluded_row_count']:,}",
            ))
        if report_result.get("monthly_analysis_excluded_row_count"):
            st.warning(t(
                "report.monthly_excluded_notice",
                count=f"{report_result['monthly_analysis_excluded_row_count']:,}",
            ))
        returned_status = get_field_availability_status(
            report_result["report_tables"], "returned"
        )
        if returned_status in {"not_provided", "not_applicable"}:
            st.info(_return_unavailable_display(report_result["report_tables"]))
            if returned_status == "not_provided":
                st.caption(t("report.return_adjustments_skipped"))
        if not customer_analysis_available(report_result["report_tables"]):
            st.info(_customer_unavailable_display(report_result["report_tables"]))

    show_kpi_cards(report_result["report_tables"])
    show_visual_dashboard(report_result)
    show_what_happened(report_result)
    show_action_required(report_result)
    show_business_insights(report_result["report_tables"])
    show_detail_tables(report_result)

    st.subheader(t("report.downloads"))
    st.caption(t("report.download_help"))
    download_columns = st.columns(2)

    with download_columns[0]:
        st.download_button(
            t("report.download_excel"),
            data=report_result["excel_bytes"],
            file_name="sales_report.xlsx",
            mime=EXCEL_MIME_TYPE,
        )

    with download_columns[1]:
        st.download_button(
            t("report.download_markdown"),
            data=report_result["summary_text"],
            file_name="summary.md",
            mime="text/markdown",
        )


st.set_page_config(page_title="Sales Report Generator", layout="wide")

render_language_selector()
st.title(t("app.title"))
st.write(t("app.intro"))
render_workflow_progress()

report_result = render_generic_relationship_mode()
if report_result is not None:
    show_report_dashboard(report_result)
render_glossary()
