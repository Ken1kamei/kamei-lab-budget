from django.urls import path

from . import views


app_name = "labapps"

urlpatterns = [
    path("portal/", views.portal, name="portal"),
    path("portal/admin/", views.portal_admin, name="portal_admin"),
    path("portal/slack/connect/", views.slack_connect, name="slack_connect"),
    path("portal/slack/callback/", views.slack_callback, name="slack_callback"),
    path("portal/slack/confirm/", views.slack_confirm, name="slack_confirm"),
    path("portal/slack/disconnect/", views.slack_disconnect, name="slack_disconnect"),
    path("tracker/", views.tracker, name="tracker"),
    path("knowledge/", views.knowledge, name="knowledge"),
    path("knowledge/upload/", views.knowledge_upload, name="knowledge_upload"),
    path(
        "knowledge/<str:record_id>/reprocess/",
        views.knowledge_reprocess,
        name="knowledge_reprocess",
    ),
    path("knowledge/<str:record_id>/download/", views.knowledge_download, name="knowledge_download"),
    path(
        "knowledge/<str:record_id>/original/",
        views.knowledge_original,
        name="knowledge_original",
    ),
    path(
        "knowledge/<str:record_id>/status/",
        views.knowledge_status,
        name="knowledge_status",
    ),
]
