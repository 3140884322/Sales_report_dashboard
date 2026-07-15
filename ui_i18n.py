from __future__ import annotations

from collections.abc import MutableMapping

import streamlit as st


LANGUAGE_STATE_KEY = "ui_language"
LANGUAGE_OPTIONS = ("zh", "en")
LANGUAGE_LABELS = {"zh": "中文", "en": "English"}


EN = {
    "language.label": "语言 / Language",
    "app.title": "Sales Data Analysis Report",
    "app.intro": (
        "Upload one or more CSV/XLSX files containing sales, orders, products, "
        "customers, stores, or related business data. The system will identify "
        "how the data is organized and guide you through each required step."
    ),
    "app.page_title": "Sales Report Generator",
    "common.not_available": "Not available",
    "common.not_applicable": "Not applicable",
    "common.none": "None",
    "common.rows": "Rows",
    "common.columns": "Columns",
    "common.confidence": "Confidence",
    "common.match_rate": "Match rate",
    "common.status": "Status",
    "common.reason": "Reason",
    "common.confirm": "Confirm",
    "common.required": "Required",
    "common.optional": "Optional",
    "common.assumption": "Assumption",
    "common.no_rows": "No rows to display.",
    "common.debug_details": "Debug details",
    "upload.title": "Upload sales data",
    "upload.label": "Sales data files",
    "upload.help.title": "What data should I upload?",
    "upload.help.body": (
        "**Supported:** CSV and XLSX; one workbook may contain multiple sheets.\n\n"
        "**Minimum transaction information:** order/transaction ID, date, product "
        "ID, unit price, and quantity.\n\n"
        "**Optional information:** customer, product name, category, store, return "
        "status, and discount rate.\n\n"
        "At least one table must contain sales transactions. You do not need to "
        "rename columns before uploading; field mapping comes later. Expense data "
        "is uploaded separately during preflight."
    ),
    "upload.spinner": "Reading and profiling uploaded tables...",
    "upload.changed": (
        "Files changed. Previous table discovery, decisions, join plan, and merge "
        "output were cleared."
    ),
    "upload.failed": "Could not read and profile the uploaded data: {error}",
    "upload.summary": (
        "The system read {file_count} file(s) and detected {table_count} table(s). "
        "Please review the detected results."
    ),
    "tables.title": "Review detected tables",
    "tables.expander": "Detected table profiles",
    "tables.explanation": (
        "Each row represents one CSV file or one Excel sheet. Check that the file, "
        "sheet, row count, and column count look reasonable. Table type, business "
        "entity, and confidence are system suggestions, not final confirmation."
    ),
    "tables.terms": (
        "**Table type:** whether the table resembles transactions or reference data.  \n"
        "**Business entity:** what the table appears to describe, such as products "
        "or customers.  \n**Confidence:** strength of the system's structural evidence."
    ),
    "tables.warning": (
        "If the file count, sheet count, or row count is clearly wrong, check the "
        "uploaded files before continuing."
    ),
    "single.detected": (
        "One table was detected. It was selected automatically as the main "
        "transaction table. Relationship review and table merging are not required; "
        "continue to field mapping."
    ),
    "single.failed": "Single-table preparation failed.",
    "single.main_table": "Main transaction table",
    "single.relationship_count": "Confirmed relationships",
    "fact.title": "Select main transaction table",
    "fact.label": "Main transaction table",
    "fact.placeholder": "Select a main transaction table",
    "fact.guidance": (
        "Choose the table that contains one row per sale or order line. It usually "
        "contains an order/transaction ID, date, product, quantity, and price, and "
        "often has the most rows. Repeated order IDs are normal for order-line data."
    ),
    "fact.blocked": "Select the main transaction table before reviewing relationships.",
    "relationships.title": "Review table relationships",
    "relationships.help.title": "How should I review relationship suggestions?",
    "relationships.help.body": (
        "**Approve:** the tables and connection fields are correct.  \n"
        "**Edit:** the tables should connect, but the selected fields are wrong.  \n"
        "**Reject:** the tables should not connect for this report.\n\n"
        "**Recommended** has strong evidence; **Needs Review** needs careful checking; "
        "**Other Candidates** has weaker evidence; **Blocked** cannot be approved "
        "because it may duplicate transactions or create another high-risk join.\n\n"
        "Typical valid examples are 'Sales.product_id → Products.product_id', "
        "'Sales.customer_id → Customers.customer_id', and "
        "'Sales.store_id → Stores.store_id'. Matching names alone do not prove a "
        "relationship, and two transaction-detail tables are usually risky to join."
    ),
    "relationships.metrics_help": (
        "**Confidence:** combined evidence score. **Match rate:** share of left-side "
        "records found on the right. **Key uniqueness:** whether the right key is "
        "unique. **Row growth risk:** whether joining may duplicate sales rows."
    ),
    "relationships.no_candidates": "No reasonable relationship candidates were detected.",
    "relationships.recommended": "Recommended ({count})",
    "relationships.needs_review": "Needs Review ({count})",
    "relationships.other": "Other Candidates ({count})",
    "relationships.blocked": "Blocked ({count})",
    "relationship.right_uniqueness": "Right key uniqueness",
    "relationship.expected_join": "Expected join",
    "relationship.risk_flags": "Risk flags: {flags}",
    "relationship.decision.pending": "Decision: Pending",
    "relationship.decision.approved": "Decision: Approved",
    "relationship.decision.approved_edited": "Decision: Approved (edited)",
    "relationship.decision.rejected": "Decision: Rejected",
    "relationship.decision.rejected_edited": "Decision: Rejected (edited)",
    "relationship.decision.edited_pending": "Decision: Edited, pending explicit approval",
    "relationship.advice.approve": (
        "Suggested action: approve after checking the business meaning; the right key "
        "is unique and the match rate is strong."
    ),
    "relationship.advice.review": (
        "Suggested action: review carefully; some transaction rows may not find a match."
    ),
    "relationship.advice.other": (
        "Suggested action: do not approve unless you can verify the relationship from "
        "business knowledge."
    ),
    "relationship.advice.blocked": (
        "Approval is disabled because this join may duplicate transaction rows or "
        "violates another safety rule."
    ),
    "relationship.approve": "Approve",
    "relationship.edit": "Edit",
    "relationship.reject": "Reject",
    "relationship.editor.title": "Edit relationship",
    "relationship.editor.left_table": "Left table",
    "relationship.editor.right_table": "Right table",
    "relationship.editor.key_size": "Key size",
    "relationship.editor.single": "Single column",
    "relationship.editor.composite": "Two-column composite",
    "relationship.editor.left_key": "Left key {number}",
    "relationship.editor.right_key": "Right key {number}",
    "relationship.editor.select_left": "Select a left column",
    "relationship.editor.select_right": "Select a right column",
    "relationship.editor.recalculate": "Recalculate score and safety",
    "relationship.editor.close": "Close editor",
    "relationship.editor.recalculated": "Recalculated candidate",
    "relationship.editor.approve": "Approve edited relationship",
    "relationship.editor.reject": "Reject edited relationship",
    "plan.title": "Approved Join Plan",
    "plan.count": "Explicitly approved relationships: {count}",
    "plan.explanation": (
        "First build a join plan from the relationships you approved. This does not "
        "change the data. Then execute the plan to perform validated many-to-one joins."
    ),
    "plan.build": "Build Approved Join Plan",
    "plan.blocked.fact": "Select the main transaction table first.",
    "plan.blocked.relationships": "Approve at least one safe relationship first.",
    "plan.blocked.path": (
        "The approved relationships do not form a valid path from the main "
        "transaction table. Review the errors below."
    ),
    "merge.execute": "Execute Safe Merge",
    "merge.blocked.no_plan": "Build a valid approved join plan before merging.",
    "merge.spinner": "Executing approved many-to-one joins...",
    "merge.title": "Merge Execution Summary",
    "merge.success": (
        "Data was merged safely. The main transaction row count stayed the same, so "
        "no duplicated sales records were detected."
    ),
    "merge.original_rows": "Original fact rows",
    "merge.final_rows": "Final merged rows",
    "merge.preview": "Merged dataset preview",
    "merge.explanation": (
        "Matching row counts before and after the merge usually mean transactions "
        "were not duplicated. Unmatched rows are not always errors, but they mean "
        "some records could not receive information from another table."
    ),
    "mapping.title": "Standard Field Mapping",
    "mapping.intro": (
        "Your files may use names such as 'Order No.', 'Sales Date', or 'SKU'. "
        "Map those source columns to the standard business fields used by the report."
    ),
    "mapping.recommendations": "Automatic mapping recommendations",
    "mapping.recommendation_notice": (
        "A recommendation is not confirmation. Review each selected source column "
        "and explicitly confirm active mappings."
    ),
    "mapping.required_section": "Required transaction fields",
    "mapping.optional_section": "Optional analysis fields",
    "mapping.assumption_section": "Business assumptions",
    "mapping.current_summary": "Current mapping summary",
    "mapping.for_field": "Mapping for {field}",
    "mapping.additional": "Additional source columns to retain",
    "mapping.additional_help": (
        "The standardized dataset keeps required fields, confirmed optional fields, "
        "and only the extra columns selected here."
    ),
    "mapping.checks": "Mapping checks ({count} incomplete)",
    "mapping.incomplete": (
        "{count} mapping item(s) still require attention. Complete the highlighted "
        "items before generating the standardized preview."
    ),
    "mapping.required_progress": "Required fields confirmed: {confirmed}/{total}",
    "mapping.generate": "Validate and Generate Unified Orders Preview",
    "mapping.generate_blocked": (
        "Complete all required mappings, resolve duplicate source-column use, and "
        "confirm active choices before continuing."
    ),
    "mapping.spinner": "Validating conversions and generating a 20-row preview...",
    "mapping.preview_title": "Unified Orders Preview",
    "mapping.preview_explanation": (
        "Unified Orders is the standardized order detail used for calculations. It "
        "does not invent new business transactions; it only applies your confirmed "
        "names, types, defaults, and selected extensions."
    ),
    "mapping.passed": "Standard field mapping passed.",
    "mapping.blocked": "Standard field mapping is blocked.",
    "mapping.merged_rows": "Merged rows",
    "mapping.merged_columns": "Merged columns",
    "mapping.memory": "Estimated memory",
    "mapping.unified_rows": "Unified rows",
    "mapping.unified_columns": "Unified columns",
    "mapping.unified_memory": "Unified memory",
    "mapping.preview_rows": "Preview rows",
    "mapping.large_warning": (
        "This dataset is large. Recommendations use bounded samples and only 20 rows "
        "are displayed, but conversion may still use additional memory."
    ),
    "strategy.unmapped": "Not mapped",
    "strategy.default_zero": "Default 0 (explicit business assumption)",
    "strategy.not_provided": "Data not provided (keep as unknown)",
    "strategy.not_applicable": "Not applicable to this business",
    "strategy.omit": "Omit optional field",
    "strategy.source": "Map from source: {source}",
    "preflight.title": "Report Preflight Review",
    "preflight.intro": (
        "Review calculation coverage and data-quality issues before generating the "
        "report. Critical issues block generation; warnings can continue after you "
        "understand them; information describes analysis coverage. Original uploaded "
        "files are never modified."
    ),
    "preflight.expenses": "Optional expense CSV",
    "preflight.expenses_help": (
        "Expense data is used only for finance and cash-flow analysis. It is never "
        "relationship-merged into orders, and the sales report can be generated "
        "without it."
    ),
    "preflight.invalid_date_title": "Invalid date decision",
    "preflight.invalid_date_question": "How should invalid dates be handled?",
    "preflight.invalid_date_block": "Stop and fix the source data",
    "preflight.invalid_date_continue": "Continue; exclude these rows from monthly analysis only",
    "preflight.invalid_date_explain": (
        "Rows with invalid dates can remain in non-monthly totals, but cannot be used "
        "in monthly trends when you choose to continue."
    ),
    "preflight.critical_title": "Critical row decision",
    "preflight.exclude_critical": (
        "Explicitly exclude all {count} invalid price/quantity row(s) from the report"
    ),
    "preflight.critical_explain": (
        "Missing or invalid prices and quantities cannot reliably calculate revenue. "
        "Excluded rows do not contribute to revenue, orders, or units."
    ),
    "preflight.original_rows": "Original fact rows",
    "preflight.merged_rows": "Merged rows",
    "preflight.unified_rows": "Unified rows",
    "preflight.excluded_rows": "Excluded rows",
    "preflight.calculation_rows": "Calculation rows",
    "preflight.memory": "Estimated memory",
    "preflight.date_range": "Data date range: {date_range}",
    "preflight.monthly_excluded": "Rows excluded from monthly analysis because of invalid dates: {count}",
    "preflight.availability": "Standard field sources and availability",
    "preflight.conversions": "Conversion results",
    "preflight.nulls": "Required field null counts",
    "preflight.invalid_price_rows": "Invalid price/quantity rows (first 20)",
    "preflight.invalid_date_rows": "Invalid date rows (first 20)",
    "preflight.preparation": "Data Preparation Summary",
    "preflight.large_excel": "Full audit Excel may take about one minute for large datasets.",
    "preflight.confirm": "I confirm the selected relationships, field mappings, assumptions, and excluded rows.",
    "preflight.generate": "Generate Report",
    "preflight.generate_blocked.issues": "Resolve the critical preflight issues shown above before generating a report.",
    "preflight.generate_blocked.confirm": "Review the summary and select the confirmation checkbox to generate the report.",
    "preflight.report_failed": "Could not generate report: {error}",
    "preflight.report_cached": "Report generated and cached for this confirmed input.",
    "report.read.title": "How to read this report",
    "report.read.body": (
        "1. Start with **Report Status**.\n2. Review **Key Metrics** and the **Visual Dashboard**.\n"
        "3. Check **Business Issues Requiring Review**.\n4. Read **Data Availability and Limitations**.\n"
        "5. Download Excel or Markdown when needed.\n\n"
        "**Ready:** checks passed. **Review Required:** the report exists but some "
        "issues need review. **Failed:** critical data prevents reliable reporting."
    ),
    "report.status.ready": "Ready",
    "report.status.review_required": "Review Required",
    "report.status.failed": "Failed",
    "report.status.ready_message": "The report passed the required data checks.",
    "report.status.review_message": "The report was generated, but some data-quality warnings need review.",
    "report.status.failed_message": "Critical data issues prevented a reliable report.",
    "report.key_metrics": "Key Metrics",
    "report.total_revenue": "Total Final Revenue",
    "report.total_orders": "Total Orders",
    "report.total_units": "Total Units",
    "report.aov": "Overall AOV",
    "report.top_category": "Top Category",
    "report.top_product": "Top Product",
    "report.top_customer": "Top Customer",
    "report.top_store": "Top Store",
    "report.anomalies": "Anomaly Count",
    "report.visual_dashboard": "Visual Dashboard",
    "report.store_analysis": "Store Analysis",
    "report.what_happened": "What happened?",
    "report.business_issues": "Business Issues Requiring Review",
    "report.no_business_issues": "No business issues require review.",
    "report.limitations": "Data Availability and Limitations",
    "report.no_limitations": "No material data limitations were identified.",
    "report.insights": "Business Insights",
    "report.details": "Detail Tables",
    "report.downloads": "Downloads",
    "report.download_help": (
        "The page dashboard is the recommended starting point. Excel is intended for "
        "audit, retention, and further analysis; Markdown is a compact summary for reading and sharing."
    ),
    "report.download_excel": "Download Excel Report",
    "report.download_markdown": "Download Markdown Summary",
    "report.finance_skipped": "Finance analysis was skipped because no expense file was uploaded.",
    "report.data_preparation": "Data Preparation Summary",
    "report.coverage": "Report Coverage",
    "report.no_monthly": "Monthly insight was not generated.",
    "report.no_complete_month": "No complete calendar month was available for ranking.",
    "report.detected_anomalies": "Detected anomalies: {count}.",
    "report.no_anomalies": "No anomalies detected.",
    "report.no_monthly_data": "Monthly revenue data is not available.",
    "report.no_category_data": "Category revenue data is not available.",
    "report.no_product_data": "Top product data is not available.",
    "report.no_customer_data": "Top customer data is not available.",
    "report.no_return_data": "Monthly return rate data is not available.",
    "report.no_cash_flow": "Cash flow data is not available.",
    "report.no_expense_category": "Expense category data is not available.",
    "report.monthly_caption": "Use this chart to spot revenue drops or spikes.",
    "report.category_caption": "Use this chart to see which category drives revenue.",
    "report.product_caption": "Use this chart to see which products contribute the most.",
    "report.customer_caption": "Use this chart to see which customers drive revenue.",
    "report.return_caption": "Use this chart to spot months with elevated returns.",
    "report.anomaly_caption": "Use this chart to see what kind of issues were detected.",
    "report.cashflow_caption": "Use this chart to compare income, expenses, and cash flow.",
    "report.expense_caption": "Use this chart to see where expenses are concentrated.",
    "chart.monthly_revenue": "Monthly Revenue Trend",
    "chart.category_revenue": "Revenue by Category",
    "chart.top_products": "Top Products by Revenue",
    "chart.top_customers": "Top 10 Customers by Revenue",
    "chart.store_revenue": "Store Performance by Revenue",
    "chart.monthly_returns": "Monthly Return Rate",
    "chart.anomalies": "Anomalies by Type",
    "chart.cash_flow": "Income vs Expenses vs Net Cash Flow",
    "chart.expenses": "Expenses by Category",
    "axis.month": "Month",
    "axis.revenue": "Revenue",
    "axis.category": "Category",
    "axis.product": "Product",
    "axis.customer": "Customer",
    "axis.store": "Store",
    "axis.return_rate": "Return Rate",
    "axis.anomaly_type": "Anomaly Type",
    "axis.count": "Count",
    "axis.amount": "Amount",
    "axis.expense_category": "Expense Category",
    "field.order_id": "Order or transaction identifier.",
    "field.date": "Date when the sale occurred.",
    "field.product_id": "Product identifier or SKU.",
    "field.unit_price": "Price per unit before discount.",
    "field.quantity": "Quantity sold on this row.",
    "field.customer_id": "Customer identifier; customer ranking and repeat analysis are skipped when absent.",
    "field.returned": "Return status; return-rate analysis is skipped when absent.",
    "field.discount_rate": "Discount fraction; 0.1 means a 10% discount.",
    "field.store_id": "Store or branch identifier.",
    "field.store_name": "Readable store or branch name.",
    "field.customer_name": "Readable customer name.",
    "field.product_name": "Readable product name.",
    "field.category": "Product category.",
}


ZH = {
    "language.label": "语言 / Language",
    "app.title": "销售数据分析报告",
    "app.intro": "上传一张或多张包含销售、订单、商品、客户、门店或相关业务数据的 CSV/XLSX 文件。系统会识别数据结构，并逐步引导你完成必要操作。",
    "app.page_title": "销售报告生成器",
    "common.not_available": "不可用",
    "common.not_applicable": "不适用",
    "common.none": "无",
    "common.rows": "行数",
    "common.columns": "列数",
    "common.confidence": "置信度",
    "common.match_rate": "匹配率",
    "common.status": "状态",
    "common.reason": "原因",
    "common.confirm": "确认",
    "common.required": "必需",
    "common.optional": "可选",
    "common.assumption": "业务假设",
    "common.no_rows": "暂无可显示的数据。",
    "common.debug_details": "调试详情",
    "upload.title": "上传销售数据",
    "upload.label": "销售数据文件",
    "upload.help.title": "我应该上传什么样的数据？",
    "upload.help.body": (
        "**支持格式：** CSV 和 XLSX；一个 Excel 文件可以包含多个 sheet。\n\n"
        "**最少交易信息：** 订单或交易编号、日期、商品编号、单价和数量。\n\n"
        "**可选信息：** 客户、商品名称、品类、门店、退货状态和折扣率。\n\n"
        "至少需要一张包含销售交易记录的表。无需提前把列名改成系统标准名称，后续可进行字段映射。费用文件在数据预检阶段单独上传。"
    ),
    "upload.spinner": "正在读取文件并生成数据表画像……",
    "upload.changed": "上传文件已变化，旧的表结构识别、关系决定、连接计划和合并结果已清除。",
    "upload.failed": "无法读取或分析上传的数据：{error}",
    "upload.summary": "系统已读取 {file_count} 个文件，共识别到 {table_count} 张数据表。请检查识别结果。",
    "tables.title": "检查识别到的数据表",
    "tables.expander": "识别到的数据表画像",
    "tables.explanation": "每一行代表一个 CSV 文件或一个 Excel sheet。请重点检查文件名、sheet、行数和列数是否合理。表类型、业务实体和置信度只是系统建议，不等于最终确认。",
    "tables.terms": "**表类型判断：** 该表更像交易明细还是参考资料。  \n**业务实体判断：** 该表更像商品、客户、门店等哪类业务对象。  \n**置信度：** 系统结构证据的强弱。",
    "tables.warning": "如果文件数量、sheet 数量或行数明显不对，请先检查上传文件再继续。",
    "single.detected": "识别到一张数据表，系统已自动将它选为主交易表。无需确认表关系或执行多表合并，请继续进行字段映射。",
    "single.failed": "单表数据准备失败。",
    "single.main_table": "主交易表",
    "single.relationship_count": "已确认关系数",
    "fact.title": "选择主交易表",
    "fact.label": "主交易表",
    "fact.placeholder": "请选择主交易表",
    "fact.guidance": "请选择保存每笔销售或订单明细的表。它通常包含订单或交易编号、日期、商品、数量和价格，而且往往行数最多。同一个订单编号出现多行是订单明细数据的正常情况。",
    "fact.blocked": "请先选择主交易表，才能继续确认表关系。",
    "relationships.title": "确认表关系",
    "relationships.help.title": "如何检查关系建议？",
    "relationships.help.body": (
        "**批准：** 两张表及其连接字段正确。  \n**编辑：** 两张表应该连接，但系统选择的字段不正确。  \n"
        "**拒绝：** 两张表不应在本次报告中连接。\n\n"
        "**推荐** 表示证据较强；**需要检查** 表示需要重点核对；**其他候选** 证据较弱；**已阻止** 表示可能重复销售记录或存在其他高风险，不能批准。\n\n"
        "常见正确关系包括 'Sales.product_id → Products.product_id'、'Sales.customer_id → Customers.customer_id' 和 "
        "'Sales.store_id → Stores.store_id'。字段同名并不代表一定应该连接，两张销售明细表直接连接通常风险较高。"
    ),
    "relationships.metrics_help": "**置信度：** 综合证据分数。**匹配率：** 左表记录能在右表找到匹配的比例。**键唯一性：** 右表连接字段是否唯一。**行数膨胀风险：** 连接后是否可能重复销售记录。",
    "relationships.no_candidates": "没有发现合理的关系候选。",
    "relationships.recommended": "推荐（{count}）",
    "relationships.needs_review": "需要检查（{count}）",
    "relationships.other": "其他候选（{count}）",
    "relationships.blocked": "已阻止（{count}）",
    "relationship.right_uniqueness": "右表键唯一性",
    "relationship.expected_join": "预计连接类型",
    "relationship.risk_flags": "风险标记：{flags}",
    "relationship.decision.pending": "决定：待处理",
    "relationship.decision.approved": "决定：已批准",
    "relationship.decision.approved_edited": "决定：已批准（已编辑）",
    "relationship.decision.rejected": "决定：已拒绝",
    "relationship.decision.rejected_edited": "决定：已拒绝（已编辑）",
    "relationship.decision.edited_pending": "决定：已编辑，等待明确批准",
    "relationship.advice.approve": "系统建议：核对业务含义后可批准；右侧键唯一且匹配率较高。",
    "relationship.advice.review": "系统建议：请重点检查；部分交易记录可能找不到匹配。",
    "relationship.advice.other": "系统建议：除非能根据业务知识确认，否则不要批准。",
    "relationship.advice.blocked": "无法批准：该连接可能重复交易行，或违反其他安全规则。",
    "relationship.approve": "批准",
    "relationship.edit": "编辑",
    "relationship.reject": "拒绝",
    "relationship.editor.title": "编辑关系",
    "relationship.editor.left_table": "左表",
    "relationship.editor.right_table": "右表",
    "relationship.editor.key_size": "连接键数量",
    "relationship.editor.single": "单列",
    "relationship.editor.composite": "两列复合键",
    "relationship.editor.left_key": "左侧字段 {number}",
    "relationship.editor.right_key": "右侧字段 {number}",
    "relationship.editor.select_left": "选择左侧字段",
    "relationship.editor.select_right": "选择右侧字段",
    "relationship.editor.recalculate": "重新计算评分与安全检查",
    "relationship.editor.close": "关闭编辑",
    "relationship.editor.recalculated": "重新计算后的候选关系",
    "relationship.editor.approve": "批准编辑后的关系",
    "relationship.editor.reject": "拒绝编辑后的关系",
    "plan.title": "已批准的连接计划",
    "plan.count": "明确批准的关系：{count}",
    "plan.explanation": "先把你批准的关系整理成连接计划，这一步不会修改数据。然后再执行计划，按经过校验的多对一方式连接数据。",
    "plan.build": "构建已批准连接计划",
    "plan.blocked.fact": "请先选择主交易表。",
    "plan.blocked.relationships": "请先批准至少一条安全关系。",
    "plan.blocked.path": "已批准关系无法从主交易表形成有效连接路径，请检查下方错误。",
    "merge.execute": "执行安全合并",
    "merge.blocked.no_plan": "请先构建有效的已批准连接计划。",
    "merge.spinner": "正在按批准计划执行多对一安全连接……",
    "merge.title": "合并执行摘要",
    "merge.success": "数据已安全合并，合并前后主交易记录数量一致，没有发现销售记录被重复放大的情况。",
    "merge.original_rows": "原主交易表行数",
    "merge.final_rows": "合并后行数",
    "merge.preview": "合并数据预览",
    "merge.explanation": "合并前后行数相同通常表示交易记录没有被重复。未匹配记录不一定是错误，但意味着这些记录无法从其他表补充信息。",
    "mapping.title": "标准字段映射",
    "mapping.intro": "你的文件可能使用“订单号”“销售日期”或“SKU”等自有列名。请把这些来源列对应到报告使用的标准业务字段。",
    "mapping.recommendations": "自动映射建议",
    "mapping.recommendation_notice": "系统推荐不等于用户确认。请检查每个来源列，并明确确认所有启用的映射。",
    "mapping.required_section": "必需交易字段",
    "mapping.optional_section": "可选分析字段",
    "mapping.assumption_section": "业务假设",
    "mapping.current_summary": "当前映射摘要",
    "mapping.for_field": "{field} 的映射",
    "mapping.additional": "需要保留的其他来源列",
    "mapping.additional_help": "标准化数据只保留必需字段、已确认的可选字段，以及这里明确选择的扩展列。",
    "mapping.checks": "映射检查（{count} 项未完成）",
    "mapping.incomplete": "还有 {count} 个映射项目需要处理。请完成标记项目后再生成标准化预览。",
    "mapping.required_progress": "必需字段已确认：{confirmed}/{total}",
    "mapping.generate": "校验并生成标准订单明细预览",
    "mapping.generate_blocked": "请完成全部必需映射、解决来源列重复使用，并确认所有启用的选择后再继续。",
    "mapping.spinner": "正在校验转换并生成 20 行预览……",
    "mapping.preview_title": "标准订单明细预览",
    "mapping.preview_explanation": "标准订单明细是最终计算使用的统一订单数据。它不会创造新的业务交易，只会应用你确认的字段名称、类型、默认值和扩展列。",
    "mapping.passed": "标准字段映射已通过。",
    "mapping.blocked": "标准字段映射被阻止。",
    "mapping.merged_rows": "合并后行数",
    "mapping.merged_columns": "合并后列数",
    "mapping.memory": "预计内存",
    "mapping.unified_rows": "标准明细行数",
    "mapping.unified_columns": "标准明细列数",
    "mapping.unified_memory": "标准明细内存",
    "mapping.preview_rows": "预览行数",
    "mapping.large_warning": "该数据集较大。推荐只使用有限样本，页面只显示 20 行，但转换仍可能占用额外内存。",
    "strategy.unmapped": "未映射",
    "strategy.default_zero": "默认 0（明确业务假设）",
    "strategy.not_provided": "数据未提供（保持未知）",
    "strategy.not_applicable": "不适用于此业务",
    "strategy.omit": "不使用此可选字段",
    "strategy.source": "映射来源列：{source}",
    "preflight.title": "报告生成前检查",
    "preflight.intro": "生成报告前，请检查计算覆盖范围和数据质量问题。严重问题会阻止生成；警告可在知情后继续；信息用于说明分析覆盖范围。原始上传文件不会被修改。",
    "preflight.expenses": "可选费用 CSV",
    "preflight.expenses_help": "费用数据只用于费用和现金流分析，不会与订单表进行关系合并。未上传费用文件时仍可生成销售报告。",
    "preflight.invalid_date_title": "无效日期处理",
    "preflight.invalid_date_question": "如何处理无效日期？",
    "preflight.invalid_date_block": "停止并修复来源数据",
    "preflight.invalid_date_continue": "继续；这些行只从月度分析中排除",
    "preflight.invalid_date_explain": "选择继续时，无效日期行可保留在非月度总计中，但不会进入月度趋势。",
    "preflight.critical_title": "严重问题行处理",
    "preflight.exclude_critical": "明确从报告中排除全部 {count} 行无效价格或数量记录",
    "preflight.critical_explain": "缺失或无效的价格和数量无法可靠计算收入。被排除行不会计入销售额、订单量或销量。",
    "preflight.original_rows": "原主交易表行数",
    "preflight.merged_rows": "合并后行数",
    "preflight.unified_rows": "标准明细行数",
    "preflight.excluded_rows": "排除行数",
    "preflight.calculation_rows": "最终计算行数",
    "preflight.memory": "预计内存",
    "preflight.date_range": "数据日期范围：{date_range}",
    "preflight.monthly_excluded": "因日期无效而仅从月度分析排除的行数：{count}",
    "preflight.availability": "标准字段来源与可用性",
    "preflight.conversions": "转换结果",
    "preflight.nulls": "必需字段空值数",
    "preflight.invalid_price_rows": "无效价格或数量行（前 20 行）",
    "preflight.invalid_date_rows": "无效日期行（前 20 行）",
    "preflight.preparation": "数据准备摘要",
    "preflight.large_excel": "大型数据集的完整审计 Excel 可能需要约一分钟。",
    "preflight.confirm": "我确认所选表关系、字段映射、业务假设和被排除行。",
    "preflight.generate": "生成报告",
    "preflight.generate_blocked.issues": "请先解决上方严重预检问题，再生成报告。",
    "preflight.generate_blocked.confirm": "请检查摘要并勾选确认框，然后生成报告。",
    "preflight.report_failed": "无法生成报告：{error}",
    "preflight.report_cached": "报告已生成，并针对本次确认输入进行缓存。",
    "report.read.title": "如何阅读这份报告",
    "report.read.body": (
        "1. 先查看 **报告状态**。\n2. 再查看 **关键指标** 和 **可视化仪表板**。\n"
        "3. 检查 **需要处理的业务问题**。\n4. 阅读 **数据可用性与限制**。\n"
        "5. 按需下载 Excel 或 Markdown。\n\n"
        "**可使用：** 数据检查通过。**需要检查：** 报告已生成，但存在需要核对的问题。**失败：** 严重数据问题导致报告不能可靠生成。"
    ),
    "report.status.ready": "可使用",
    "report.status.review_required": "需要检查",
    "report.status.failed": "失败",
    "report.status.ready_message": "报告已通过必要的数据检查。",
    "report.status.review_message": "报告已生成，但部分数据质量警告需要检查。",
    "report.status.failed_message": "严重数据问题导致报告无法可靠生成。",
    "report.key_metrics": "关键指标",
    "report.total_revenue": "最终销售额",
    "report.total_orders": "订单数",
    "report.total_units": "销量",
    "report.aov": "平均订单金额",
    "report.top_category": "销售额最高品类",
    "report.top_product": "销售额最高商品",
    "report.top_customer": "销售额最高客户",
    "report.top_store": "销售额最高门店",
    "report.anomalies": "异常数量",
    "report.visual_dashboard": "可视化仪表板",
    "report.store_analysis": "门店分析",
    "report.what_happened": "数据处理过程",
    "report.business_issues": "需要处理的业务问题",
    "report.no_business_issues": "没有发现需要处理的业务问题。",
    "report.limitations": "数据可用性与限制",
    "report.no_limitations": "没有发现重要的数据限制。",
    "report.insights": "业务洞察",
    "report.details": "明细表",
    "report.downloads": "下载",
    "report.download_help": "建议普通用户先阅读页面仪表板。Excel 用于审计、保存和进一步分析；Markdown 用于快速阅读和分享摘要。",
    "report.download_excel": "下载 Excel 报告",
    "report.download_markdown": "下载 Markdown 摘要",
    "report.finance_skipped": "未上传费用文件，已跳过费用和现金流分析。",
    "report.data_preparation": "数据准备摘要",
    "report.coverage": "报告覆盖范围",
    "report.no_monthly": "未生成月度洞察。",
    "report.no_complete_month": "没有完整自然月可用于排名。",
    "report.detected_anomalies": "检测到的异常：{count}。",
    "report.no_anomalies": "未检测到异常。",
    "report.no_monthly_data": "没有可用的月度销售额数据。",
    "report.no_category_data": "没有可用的品类销售额数据。",
    "report.no_product_data": "没有可用的商品排行数据。",
    "report.no_customer_data": "没有可用的客户排行数据。",
    "report.no_return_data": "没有可用的月度退货率数据。",
    "report.no_cash_flow": "没有可用的现金流数据。",
    "report.no_expense_category": "没有可用的费用品类数据。",
    "report.monthly_caption": "用于查看销售额的下降或上升。",
    "report.category_caption": "用于查看哪些品类贡献销售额。",
    "report.product_caption": "用于查看销售额贡献最高的商品。",
    "report.customer_caption": "用于查看哪些客户贡献销售额。",
    "report.return_caption": "用于查看退货率较高的月份。",
    "report.anomaly_caption": "用于查看检测到的问题类型。",
    "report.cashflow_caption": "用于比较收入、费用和净现金流。",
    "report.expense_caption": "用于查看费用集中在哪些类别。",
    "chart.monthly_revenue": "月度销售额趋势",
    "chart.category_revenue": "按品类销售额",
    "chart.top_products": "商品销售额排行",
    "chart.top_customers": "客户销售额前 10 名",
    "chart.store_revenue": "门店销售表现",
    "chart.monthly_returns": "月度退货率",
    "chart.anomalies": "异常类型",
    "chart.cash_flow": "收入、费用与净现金流",
    "chart.expenses": "按类别费用",
    "axis.month": "月份",
    "axis.revenue": "销售额",
    "axis.category": "品类",
    "axis.product": "商品",
    "axis.customer": "客户",
    "axis.store": "门店",
    "axis.return_rate": "退货率",
    "axis.anomaly_type": "异常类型",
    "axis.count": "数量",
    "axis.amount": "金额",
    "axis.expense_category": "费用类别",
    "field.order_id": "订单或交易编号。",
    "field.date": "销售发生日期。",
    "field.product_id": "商品编号或 SKU。",
    "field.unit_price": "折扣前的单件商品价格。",
    "field.quantity": "本行销售数量。",
    "field.customer_id": "客户编号；缺失时跳过客户排行和复购分析。",
    "field.returned": "是否退货；缺失时跳过退货率分析。",
    "field.discount_rate": "折扣比例；0.1 表示九折。",
    "field.store_id": "门店或分店编号。",
    "field.store_name": "可读的门店或分店名称。",
    "field.customer_name": "可读的客户名称。",
    "field.product_name": "可读的商品名称。",
    "field.category": "商品品类。",
}


EN.update(
    {
        "workflow.title": "Workflow Progress",
        "workflow.step": "Step",
        "workflow.name": "Stage",
        "workflow.status": "Status",
        "workflow.status.not_started": "○ Not started",
        "workflow.status.current": "▶ Current",
        "workflow.status.completed": "✓ Completed",
        "workflow.status.action_required": "! Action required",
        "workflow.status.skipped": "– Skipped / Not required",
        "guide.step": "Step {number} of {total}: {title}",
        "guide.goal": "Goal",
        "guide.action": "What you need to do",
        "guide.completion": "Completion criteria",
        "guide.next": "Next step",
        "step.1.title": "Upload Data",
        "step.1.goal": "Read your sales files and identify each CSV or Excel sheet.",
        "step.1.action": "Upload one or more sales-related CSV/XLSX files.",
        "step.1.completion": "At least one transaction table is detected and its row count looks reasonable.",
        "step.1.next": "Review the detected tables.",
        "step.2.title": "Review Tables",
        "step.2.goal": "Confirm that files and sheets were read as the expected tables.",
        "step.2.action": "Check file, sheet, row, column, and suggested entity information.",
        "step.2.completion": "The detected table list matches what you intended to upload.",
        "step.2.next": "Choose the main transaction table.",
        "step.3.title": "Select Main Transaction Table",
        "step.3.goal": "Choose the table whose rows form the basis of the sales report.",
        "step.3.action": "Select the order or sales detail table. A single table is selected automatically.",
        "step.3.completion": "One main transaction table is selected.",
        "step.3.next": "Review table relationships, or continue to mapping for a single table.",
        "step.4.title": "Review Relationships",
        "step.4.goal": "Decide which suggested table connections are valid for this report.",
        "step.4.action": "Approve, edit, or reject candidates based on business meaning and safety metrics.",
        "step.4.completion": "The required safe relationships are explicitly approved.",
        "step.4.next": "Build a join plan and execute the safe merge.",
        "step.5.title": "Safe Merge",
        "step.5.goal": "Combine approved tables without duplicating sales transactions.",
        "step.5.action": "Build the approved plan, review it, then execute the merge.",
        "step.5.completion": "The merge passes validation and the transaction row count does not increase.",
        "step.5.next": "Map source columns to standard report fields.",
        "step.6.title": "Field Mapping",
        "step.6.goal": "Tell the system which source columns contain each standard business field.",
        "step.6.action": "Review recommendations, choose sources or explicit fallback strategies, and confirm them.",
        "step.6.completion": "All required fields are confirmed and conversion checks pass.",
        "step.6.next": "Review the standardized order preview and preflight checks.",
        "step.7.title": "Preflight Review",
        "step.7.goal": "Confirm calculation rows, assumptions, exclusions, and analysis coverage.",
        "step.7.action": "Resolve critical issues, review warnings, optionally upload expenses, and confirm the summary.",
        "step.7.completion": "Preflight permits generation and the confirmation checkbox is selected.",
        "step.7.next": "Generate the report.",
        "step.8.title": "Generate Report",
        "step.8.goal": "Run the existing analysis and prepare dashboard, Excel, and Markdown outputs.",
        "step.8.action": "Generate once, then review status, metrics, issues, limitations, and downloads.",
        "step.8.completion": "A cached report result and download files are available.",
        "step.8.next": "Use the dashboard and download the report as needed.",
        "glossary.title": "Glossary",
        "glossary.body": (
            "**Main transaction table / Fact table:** the table containing sales or order lines that form the report basis.\n\n"
            "**Dimension table:** a reference table that adds product, customer, store, or similar descriptions.\n\n"
            "**Relationship:** a proposed connection between fields in two tables. **Join:** applying that connection to add columns.\n\n"
            "**Match rate:** share of transaction rows that find a matching reference record. **Uniqueness:** whether the right-side key identifies one record.\n\n"
            "**Row growth:** extra rows created by a join; this may duplicate revenue. **Field mapping:** assigning source columns to standard report fields.\n\n"
            "**Preflight:** final checks before report generation. **Unified Orders:** standardized order detail used for calculations.\n\n"
            "**AOV:** average order value. **Anomaly:** a rule-based result that may need business review."
        ),
        "table.column.table": "Table",
        "table.column.source": "File",
        "table.column.sheet": "Sheet",
        "table.column.rows": "Rows",
        "table.column.columns": "Columns",
        "table.column.role": "Table type suggestion",
        "table.column.role_confidence": "Table type confidence",
        "table.column.entity_role": "Business entity suggestion",
        "table.column.entity_confidence": "Entity confidence",
        "relationship.breakdown.component": "Scoring component",
        "relationship.breakdown.points": "Points",
        "relationship.block_reason": "Block reason: {reason}",
        "fact.recommendation": "System suggestion: {table}",
        "fact.recommendation_reason": (
            "This table most closely resembles transaction detail based on its "
            "structure, suggested table type, and row count. This is a suggestion "
            "only; please make the final selection."
        ),
        "plan.error": "Plan issue: {error}",
        "merge.error": "Merge stopped: {error}",
        "merge.diagnostics": "Merge diagnostics",
        "common.no_confirmation_needed": "No confirmation needed",
        "mapping.user_fallback": "User-selected fallback strategy.",
        "mapping.column.standard_field": "Standard field",
        "mapping.column.required": "Required",
        "mapping.column.target_type": "Target type",
        "mapping.column.recommendation": "Recommended source or strategy",
        "mapping.column.source_strategy": "Source or strategy",
        "mapping.column.conversion_failures": "Conversion failures",
        "mapping.column.invalid_values": "Invalid values",
        "mapping.column.null_values": "Null values",
        "mapping.column.null_rate": "Null rate",
        "mapping.column.output_type": "Output type",
        "mapping.column.explanation": "Explanation",
        "mapping.error_item": "Check required: {error}",
        "preflight.expenses_label": "expenses.csv (optional)",
        "preflight.issue": "{field}: {message} ({count} rows)",
        "preflight.progress.5": "1/5 Validating unified orders",
        "preflight.progress.20": "2/5 Preparing temporary input",
        "preflight.progress.40": "3/5 Running analysis",
        "preflight.progress.75": "4/5 Generating Excel",
        "preflight.progress.95": "5/5 Finalizing downloads",
        "preflight.critical_help": (
            "Invalid prices or quantities cannot reliably calculate revenue. "
            "They must be fixed or explicitly excluded; excluded rows do not count "
            "toward revenue, orders, or units."
        ),
        "preflight.classification": (
            "**Critical:** blocks report generation until resolved. **Warning:** the "
            "report may continue after review. **Information:** explains coverage "
            "and skipped modules."
        ),
        "report.revenue_drop_warning": "One or more months had a revenue drop above 20%.",
        "report.return_rate_warning": "Months above 15% return rate may need review.",
        "report.cashflow.income": "Monthly Income",
        "report.cashflow.expenses": "Monthly Expenses",
        "report.cashflow.net": "Net Cash Flow",
        "report.customer_not_provided": "Customer data was not provided. Customer analysis was skipped.",
        "report.customer_partial": "Customer data was only partially provided. Customer analysis was skipped.",
        "report.return_not_provided": "Return data was not provided. Return analysis was skipped.",
        "report.return_not_applicable": "Return analysis: Not applicable.",
        "report.return_adjustments_skipped": "Return adjustments were not applied because return status was unavailable.",
        "report.store_partial": "Store data was partially provided. Some transactions could not be assigned to a store.",
        "report.status_value.passed": "passed",
        "report.status_value.not_passed": "not passed",
        "report.status_value.present": "present",
        "report.status_value.missing": "missing",
        "report.status_value.uploaded": "uploaded",
        "report.status_value.not_uploaded": "not uploaded",
        "report.process.original": "Original uploaded order rows: {count}.",
        "report.process.duplicates": "Duplicate review: {groups} duplicate groups involving {rows} rows.",
        "report.process.removed": "Selected duplicate rows removed from temporary report input: {count}.",
        "report.process.calculation": "Final rows used for calculation: {count}.",
        "report.process.required": "Required columns: {status}.",
        "report.process.validation": "Validation checks: {status}.",
        "report.process.expenses": "Expense file: {status}.",
        "report.duplicate_notice": "Original uploaded data contained {groups} duplicate groups involving {rows} rows.",
        "report.removed_notice": "{count} selected duplicate row(s) were removed from the temporary report input. The original uploaded file was not changed.",
        "report.excluded_notice": "{count} row(s) were explicitly excluded from all report calculations.",
        "report.monthly_excluded_notice": "{count} row(s) with invalid dates were excluded from monthly analysis only.",
        "report.column.issue": "Issue",
        "report.column.severity": "Severity",
        "report.column.business_impact": "Business Impact",
        "report.column.suggested_action": "Suggested Action",
        "report.column.limitation": "Limitation",
        "report.column.impact": "Impact",
        "report.insight.strongest": "Strongest complete month: {month} with {revenue} in revenue.",
        "report.insight.weakest": "Weakest complete month: {month} with {revenue} in revenue.",
        "report.insight.top_category": "Top category: {name} ({revenue}).",
        "report.insight.top_product": "Top product: {name} ({revenue}).",
        "report.insight.top_customer": "Top customer: {name} ({revenue}).",
        "report.insight.top_store": "Top store: {name} ({revenue}, {share} of total revenue).",
        "report.insight.lowest_store": "Lowest-revenue store: {name} ({revenue}).",
        "detail.monthly": "Monthly Summary",
        "detail.category": "Category Summary",
        "detail.products": "Top Products",
        "detail.store": "Store Summary",
        "detail.customers": "Top Customers",
        "detail.duplicates": "Duplicate Rows Detail",
        "detail.anomalies": "Anomalies",
        "detail.validation": "Validation Report",
        "detail.quality": "Data Quality Checks",
        "detail.preparation": "Data Preparation Summary",
        "detail.availability": "Field Availability",
        "detail.coverage": "Report Coverage",
        "detail.excluded": "Excluded Rows Detail",
        "table.column.step": "Step",
        "table.column.relationship": "Relationship",
        "table.column.edited": "Edited",
        "table.column.right_table": "Right table",
        "table.column.rows_before": "Rows before",
        "table.column.rows_after": "Rows after",
        "table.column.matched_rows": "Matched rows",
        "table.column.unmatched_rows": "Unmatched rows",
        "table.column.row_growth": "Row growth",
        "table.column.validation": "Validation status",
        "table.column.error": "Error",
        "table.column.confirmed": "Confirmed",
        "table.column.section": "Section",
        "table.column.item": "Item",
        "table.column.value": "Value",
        "table.column.notes": "Notes",
        "availability.column.field": "Field",
        "availability.column.status": "Availability",
        "availability.column.source": "Source column",
        "availability.column.default": "Default value",
        "availability.column.user_confirmed": "User confirmed",
        "availability.column.provided_rows": "Provided rows",
        "availability.column.total_rows": "Total rows",
        "coverage.column.analysis": "Analysis module",
        "coverage.column.status": "Coverage status",
        "reader.encoding_error": (
            "The file may use an unsupported encoding or was decoded as unreadable "
            "text. Try saving the CSV as UTF-8 or uploading it as XLSX."
        ),
        "relationship.fallback.explanation": (
            "Column-name similarity is weak, but the actual values overlap strongly. "
            "Confirm whether they represent the same business identifier."
        ),
        "relationship.format_warning": (
            "The relationship fields may use inconsistent formats, including leading "
            "zeros. The system did not force differently formatted identifiers to match."
        ),
        "relationships.no_candidates_guidance": (
            "Possible reasons: no similar identifier fields were found, value overlap "
            "was too low, the right key was not unique, or the join failed a safety check."
        ),
        "score.name_alignment": "Name alignment",
        "score.name_similarity": "Name similarity",
        "score.type_compatibility": "Type compatibility",
        "score.value_overlap": "Value overlap",
        "score.right_key_uniqueness": "Right-side uniqueness",
        "score.table_role_fit": "Table-role fit",
        "score.entity_role_consistency": "Entity-role consistency",
        "score.row_growth_risk": "Row-growth risk",
        "score.safety_penalty": "Safety penalty",
        "score.other_safety_penalty": "Other safety penalty",
        "risk.right_key_nulls": "Right key contains null values",
        "risk.right_key_not_unique": "Right key is not unique",
        "risk.many_to_many": "Many-to-many risk",
        "risk.row_inflation": "Row-inflation risk",
        "risk.fact_to_fact": "Fact-to-fact risk",
        "risk.order_line_to_header_low_match": "Order-line/header match rate is too low",
        "risk.key_format_mismatch": "Key-format mismatch",
        "risk.weak_name_high_value_overlap": "Weak name match with high value overlap",
        "table.column.encoding": "Detected encoding",
        "table.column.role_breakdown": "Role score breakdown",
    }
)

ZH.update(
    {
        "workflow.title": "流程进度",
        "workflow.step": "步骤",
        "workflow.name": "阶段",
        "workflow.status": "状态",
        "workflow.status.not_started": "○ 未开始",
        "workflow.status.current": "▶ 当前步骤",
        "workflow.status.completed": "✓ 已完成",
        "workflow.status.action_required": "! 需要处理",
        "workflow.status.skipped": "– 已跳过 / 无需执行",
        "guide.step": "第 {number}/{total} 步：{title}",
        "guide.goal": "当前目标",
        "guide.action": "你需要做什么",
        "guide.completion": "完成标准",
        "guide.next": "下一步",
        "step.1.title": "上传数据",
        "step.1.goal": "读取销售文件，并识别每个 CSV 或 Excel sheet。",
        "step.1.action": "上传一张或多张与销售相关的 CSV/XLSX 文件。",
        "step.1.completion": "至少识别到一张交易表，且行数看起来合理。",
        "step.1.next": "检查识别到的数据表。",
        "step.2.title": "检查数据表",
        "step.2.goal": "确认文件和 sheet 被识别为预期的数据表。",
        "step.2.action": "检查文件、sheet、行数、列数和业务实体建议。",
        "step.2.completion": "识别到的数据表清单与预期上传内容一致。",
        "step.2.next": "选择主交易表。",
        "step.3.title": "选择主交易表",
        "step.3.goal": "选择最终销售报告所依据的交易明细表。",
        "step.3.action": "选择订单或销售明细表；只有一张表时系统会自动选择。",
        "step.3.completion": "已选定一张主交易表。",
        "step.3.next": "多表时确认关系；单表时直接进入字段映射。",
        "step.4.title": "确认表关系",
        "step.4.goal": "判断哪些系统建议的表连接适用于本次报告。",
        "step.4.action": "根据业务含义和安全指标批准、编辑或拒绝候选关系。",
        "step.4.completion": "报告需要的安全关系已被明确批准。",
        "step.4.next": "构建连接计划并执行安全合并。",
        "step.5.title": "安全合并",
        "step.5.goal": "在不重复销售交易的前提下合并已批准的数据表。",
        "step.5.action": "先构建并检查计划，再执行安全合并。",
        "step.5.completion": "合并通过校验，且主交易行数没有增加。",
        "step.5.next": "把来源列映射为报告标准字段。",
        "step.6.title": "字段映射",
        "step.6.goal": "告诉系统每个标准业务字段来自哪一列。",
        "step.6.action": "检查推荐，选择来源列或明确的缺失策略，并完成确认。",
        "step.6.completion": "全部必需字段已确认，转换检查通过。",
        "step.6.next": "检查标准订单明细和生成前检查。",
        "step.7.title": "数据预检",
        "step.7.goal": "确认计算行、业务假设、排除行和分析覆盖范围。",
        "step.7.action": "解决严重问题、阅读警告、按需上传费用，并确认摘要。",
        "step.7.completion": "预检允许生成报告，且用户已勾选最终确认。",
        "step.7.next": "生成报告。",
        "step.8.title": "生成报告",
        "step.8.goal": "调用现有分析流程，生成页面仪表板、Excel 和 Markdown。",
        "step.8.action": "生成一次后，查看状态、指标、问题、限制和下载文件。",
        "step.8.completion": "报告结果已缓存，下载文件可用。",
        "step.8.next": "阅读仪表板，并按需下载报告。",
        "glossary.title": "术语说明",
        "glossary.body": (
            "**主交易表 / 事实表：** 保存销售或订单明细、作为报告计算基础的表。\n\n"
            "**维度表：** 用于补充商品、客户、门店等描述信息的参考表。\n\n"
            "**表关系：** 两张表之间可能的字段连接。**数据连接：** 按该关系把另一张表的列补充进来。\n\n"
            "**匹配率：** 交易行能找到参考记录的比例。**唯一性：** 右侧连接字段能否唯一识别一条记录。\n\n"
            "**行数膨胀：** 连接后产生额外行，可能重复计算销售额。**字段映射：** 把来源列指定为报告标准字段。\n\n"
            "**生成前检查：** 生成报告前的最后数据校验。**标准订单明细：** 最终计算使用的统一订单数据。\n\n"
            "**AOV：** 平均订单金额。**异常：** 规则检测到、可能需要业务核查的结果。"
        ),
        "table.column.table": "数据表",
        "table.column.source": "文件",
        "table.column.sheet": "Sheet",
        "table.column.rows": "行数",
        "table.column.columns": "列数",
        "table.column.role": "表类型建议",
        "table.column.role_confidence": "表类型置信度",
        "table.column.entity_role": "业务实体建议",
        "table.column.entity_confidence": "实体置信度",
        "relationship.breakdown.component": "评分项",
        "relationship.breakdown.points": "分数",
        "relationship.block_reason": "阻止原因：{reason}",
        "fact.recommendation": "系统建议：{table}",
        "fact.recommendation_reason": "根据表结构、表类型建议和行数，这张表最像交易明细。这只是系统建议，最终请由你确认。",
        "plan.error": "连接计划问题：{error}",
        "merge.error": "合并已停止：{error}",
        "merge.diagnostics": "合并诊断",
        "common.no_confirmation_needed": "无需额外确认",
        "mapping.user_fallback": "用户选择的备选策略。",
        "mapping.column.standard_field": "标准字段",
        "mapping.column.required": "是否必需",
        "mapping.column.target_type": "目标类型",
        "mapping.column.recommendation": "建议来源或策略",
        "mapping.column.source_strategy": "来源或策略",
        "mapping.column.conversion_failures": "转换失败数",
        "mapping.column.invalid_values": "无效值数",
        "mapping.column.null_values": "空值数",
        "mapping.column.null_rate": "空值率",
        "mapping.column.output_type": "输出类型",
        "mapping.column.explanation": "说明",
        "mapping.error_item": "需要处理：{error}",
        "preflight.expenses_label": "expenses.csv（可选）",
        "preflight.issue": "{field}：{message}（{count} 行）",
        "preflight.progress.5": "1/5 正在校验标准订单明细",
        "preflight.progress.20": "2/5 正在准备临时输入",
        "preflight.progress.40": "3/5 正在运行分析",
        "preflight.progress.75": "4/5 正在生成 Excel",
        "preflight.progress.95": "5/5 正在完成下载文件",
        "preflight.critical_help": "无效价格或数量无法可靠计算销售额，必须修复或明确排除。被排除的行不会计入销售额、订单量和销量。",
        "preflight.classification": "**严重问题：** 解决前阻止生成报告。**警告：** 检查后可以继续。**信息：** 说明数据覆盖范围和被跳过的分析。",
        "report.revenue_drop_warning": "一个或多个月份的销售额下降超过 20%。",
        "report.return_rate_warning": "退货率高于 15% 的月份可能需要检查。",
        "report.cashflow.income": "月度收入",
        "report.cashflow.expenses": "月度费用",
        "report.cashflow.net": "净现金流",
        "report.customer_not_provided": "未提供客户数据，已跳过客户分析。",
        "report.customer_partial": "仅提供了部分客户数据，已跳过客户分析。",
        "report.return_not_provided": "未提供退货数据，已跳过退货分析。",
        "report.return_not_applicable": "退货分析：不适用。",
        "report.return_adjustments_skipped": "由于退货状态不可用，未应用退货调整。",
        "report.store_partial": "仅提供了部分门店数据，部分交易无法归属到门店。",
        "report.status_value.passed": "已通过",
        "report.status_value.not_passed": "未通过",
        "report.status_value.present": "已具备",
        "report.status_value.missing": "缺失",
        "report.status_value.uploaded": "已上传",
        "report.status_value.not_uploaded": "未上传",
        "report.process.original": "原上传订单行数：{count}。",
        "report.process.duplicates": "重复数据检查：{groups} 组，共涉及 {rows} 行。",
        "report.process.removed": "从临时报告输入中删除的已选重复行：{count}。",
        "report.process.calculation": "最终用于计算的行数：{count}。",
        "report.process.required": "必需列：{status}。",
        "report.process.validation": "校验结果：{status}。",
        "report.process.expenses": "费用文件：{status}。",
        "report.duplicate_notice": "原上传数据包含 {groups} 组重复数据，共涉及 {rows} 行。",
        "report.removed_notice": "已从临时报告输入中删除 {count} 行已选重复数据，原上传文件未被修改。",
        "report.excluded_notice": "已明确从全部报告计算中排除 {count} 行。",
        "report.monthly_excluded_notice": "已从月度分析中排除 {count} 行无效日期数据，其他计算不受影响。",
        "report.column.issue": "问题",
        "report.column.severity": "严重程度",
        "report.column.business_impact": "业务影响",
        "report.column.suggested_action": "建议操作",
        "report.column.limitation": "数据限制",
        "report.column.impact": "影响",
        "report.insight.strongest": "最强完整月份：{month}，销售额 {revenue}。",
        "report.insight.weakest": "最弱完整月份：{month}，销售额 {revenue}。",
        "report.insight.top_category": "销售额最高品类：{name}（{revenue}）。",
        "report.insight.top_product": "销售额最高商品：{name}（{revenue}）。",
        "report.insight.top_customer": "销售额最高客户：{name}（{revenue}）。",
        "report.insight.top_store": "销售额最高门店：{name}（{revenue}，占总销售额 {share}）。",
        "report.insight.lowest_store": "销售额最低门店：{name}（{revenue}）。",
        "detail.monthly": "月度汇总",
        "detail.category": "品类汇总",
        "detail.products": "商品排行",
        "detail.store": "门店汇总",
        "detail.customers": "客户排行",
        "detail.duplicates": "重复行明细",
        "detail.anomalies": "异常明细",
        "detail.validation": "校验报告",
        "detail.quality": "数据质量检查",
        "detail.preparation": "数据准备摘要",
        "detail.availability": "字段可用性",
        "detail.coverage": "报告覆盖范围",
        "detail.excluded": "被排除行明细",
        "table.column.step": "步骤",
        "table.column.relationship": "表关系",
        "table.column.edited": "是否编辑",
        "table.column.right_table": "右表",
        "table.column.rows_before": "合并前行数",
        "table.column.rows_after": "合并后行数",
        "table.column.matched_rows": "已匹配行数",
        "table.column.unmatched_rows": "未匹配行数",
        "table.column.row_growth": "行数增长",
        "table.column.validation": "校验状态",
        "table.column.error": "错误",
        "table.column.confirmed": "已确认",
        "table.column.section": "分类",
        "table.column.item": "项目",
        "table.column.value": "值",
        "table.column.notes": "备注",
        "availability.column.field": "字段",
        "availability.column.status": "可用状态",
        "availability.column.source": "来源列",
        "availability.column.default": "默认值",
        "availability.column.user_confirmed": "用户已确认",
        "availability.column.provided_rows": "已提供行数",
        "availability.column.total_rows": "总行数",
        "coverage.column.analysis": "分析模块",
        "coverage.column.status": "覆盖状态",
        "reader.encoding_error": "文件可能使用了不受支持的字符编码，或读取后出现乱码。请尝试将 CSV 另存为 UTF-8 或上传 XLSX 文件。",
        "relationship.fallback.explanation": "列名语义匹配较弱，但两列的实际值高度重合。请确认它们是否代表同一个业务编号。",
        "relationship.format_warning": "关系字段可能使用了不一致的格式，包括前导零。系统没有强制将格式不同的业务编号视为相同。",
        "relationships.no_candidates_guidance": "可能原因：未找到相似的编号字段、字段值重合率过低、右表键不唯一，或连接未通过安全检查。",
        "score.name_alignment": "列名匹配",
        "score.name_similarity": "列名相似度",
        "score.type_compatibility": "类型兼容性",
        "score.value_overlap": "值重合",
        "score.right_key_uniqueness": "右表键唯一性",
        "score.table_role_fit": "表角色匹配",
        "score.entity_role_consistency": "实体角色一致性",
        "score.row_growth_risk": "行数膨胀风险",
        "score.safety_penalty": "安全扣分",
        "score.other_safety_penalty": "其他安全扣分",
        "risk.right_key_nulls": "右表键包含空值",
        "risk.right_key_not_unique": "右表键不唯一",
        "risk.many_to_many": "多对多风险",
        "risk.row_inflation": "行数膨胀风险",
        "risk.fact_to_fact": "事实表对事实表风险",
        "risk.order_line_to_header_low_match": "订单明细与订单主表匹配率过低",
        "risk.key_format_mismatch": "关系键格式不一致",
        "risk.weak_name_high_value_overlap": "列名匹配较弱、值重合较高",
        "table.column.encoding": "识别到的编码",
        "table.column.role_breakdown": "表角色评分明细",
    }
)


TRANSLATIONS = {"en": EN, "zh": ZH}


FIELD_DISPLAY_NAMES = {
    "en": {
        "order_id": "Order ID", "date": "Order Date", "product_id": "Product ID",
        "unit_price": "Unit Price", "quantity": "Quantity", "customer_id": "Customer ID",
        "returned": "Returned", "discount_rate": "Discount Rate", "store_id": "Store ID",
        "store_name": "Store Name", "customer_name": "Customer Name",
        "product_name": "Product Name", "category": "Category",
    },
    "zh": {
        "order_id": "订单编号", "date": "订单日期", "product_id": "商品编号",
        "unit_price": "单价", "quantity": "数量", "customer_id": "客户编号",
        "returned": "退货状态", "discount_rate": "折扣率", "store_id": "门店编号",
        "store_name": "门店名称", "customer_name": "客户名称",
        "product_name": "商品名称", "category": "品类",
    },
}


def get_language(state: MutableMapping | None = None) -> str:
    if state is None:
        state = st.session_state
    language = state.get(LANGUAGE_STATE_KEY, "zh")
    return language if language in LANGUAGE_OPTIONS else "zh"


def set_language(state: MutableMapping, language: str) -> None:
    state[LANGUAGE_STATE_KEY] = language if language in LANGUAGE_OPTIONS else "zh"


def t(key: str, language: str | None = None, **kwargs) -> str:
    language = language or get_language()
    template = TRANSLATIONS.get(language, EN).get(key)
    if template is None:
        template = EN.get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def field_label(field_name: str, language: str | None = None) -> str:
    language = language or get_language()
    display_name = FIELD_DISPLAY_NAMES.get(language, {}).get(field_name, field_name)
    if language == "zh":
        return f"{field_name}（{display_name}）"
    return f"{field_name} ({display_name})"


def field_help(field_name: str, language: str | None = None) -> str:
    return t(f"field.{field_name}", language)


def render_language_selector() -> str:
    if LANGUAGE_STATE_KEY not in st.session_state:
        st.session_state[LANGUAGE_STATE_KEY] = "zh"
    return st.selectbox(
        t("language.label", "zh"),
        LANGUAGE_OPTIONS,
        format_func=lambda value: LANGUAGE_LABELS[value],
        key=LANGUAGE_STATE_KEY,
    )
