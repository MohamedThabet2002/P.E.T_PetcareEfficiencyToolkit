"""
Report category pages for the reports center.

``reports_page.ReportsPage`` hosts the shared header toolbar (period
trigger, granularity, exports; calendar in a popup) and a QTabWidget whose pages are the per-category
``BaseReportTab`` subclasses in this package (``overview_tab``, ``financial_tab``,
``patient_tab``, ``supply_tab``, ``audit_tab``).
"""