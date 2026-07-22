from django.urls import path

from budget import views


app_name = "budget"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("login/google/", views.google_login, name="google_login"),
    path("login/google/callback/", views.google_callback, name="google_callback"),
    path("login/development/", views.dev_login, name="dev_login"),
    path("logout/", views.logout_view, name="logout"),
    path("transactions/", views.transactions_view, name="transactions"),
    path("imports/", views.imports_view, name="imports"),
    path("comparison/", views.comparison_view, name="comparison"),
    path("sync/", views.sync_view, name="sync"),
    path("health/", views.health, name="health"),
]
