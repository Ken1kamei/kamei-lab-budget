from django.urls import path

from budget import erb_views, operation_views, report_views, settings_views, views


app_name = "budget"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("login/google/", views.google_login, name="google_login"),
    path("login/google/callback/", views.google_callback, name="google_callback"),
    path("login/development/", views.dev_login, name="dev_login"),
    path("logout/", views.logout_view, name="logout"),
    path("transactions/", views.transactions_view, name="transactions"),
    path("transactions/add/", operation_views.add_transaction, name="add_transaction"),
    path(
        "transactions/<str:fiscal_year>/<str:transaction_id>/edit/",
        operation_views.edit_transaction,
        name="edit_transaction",
    ),
    path("transactions/export/", operation_views.export_transactions, name="export_transactions"),
    path("imports/", views.imports_view, name="imports"),
    path("imports/<int:draft_id>/file/", views.invoice_file, name="invoice_file"),
    path(
        "imports/<int:draft_id>/dismiss/",
        views.dismiss_invoice_draft,
        name="dismiss_invoice_draft",
    ),
    path("imports/erb/", erb_views.erb_import, name="erb_import"),
    path(
        "imports/<int:draft_id>/commit/",
        views.commit_invoice_draft,
        name="commit_invoice_draft",
    ),
    path("comparison/", views.comparison_view, name="comparison"),
    path("reports/", report_views.reports, name="reports"),
    path("settings/", settings_views.settings_page, name="settings"),
    path("sync/", views.sync_view, name="sync"),
    path("health/", views.health, name="health"),
]
