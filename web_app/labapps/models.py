from django.db import models


class SheetRecord(models.Model):
    SOURCE_CHOICES = [("registry", "Registry"), ("tracker", "Project tracker")]

    source = models.CharField(max_length=24, choices=SOURCE_CHOICES)
    table_name = models.CharField(max_length=64)
    record_id = models.CharField(max_length=160)
    payload = models.JSONField(default=dict)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "table_name", "record_id"],
                name="unique_lab_sheet_record",
            )
        ]
        ordering = ["source", "table_name", "record_id"]
        indexes = [models.Index(fields=["source", "table_name"])]


class KnowledgeRecord(models.Model):
    RECORD_TYPES = [("protocol", "Protocol"), ("notebook", "Notebook")]

    record_id = models.CharField(max_length=160, unique=True)
    record_type = models.CharField(max_length=16, choices=RECORD_TYPES)
    title = models.CharField(max_length=500)
    team = models.CharField(max_length=240, blank=True)
    owner = models.CharField(max_length=240, blank=True)
    category = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=64, blank=True)
    source_path = models.CharField(max_length=1200, blank=True)
    object_name = models.CharField(max_length=1200, blank=True)
    original_filename = models.CharField(max_length=500, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    canonical_record_id = models.CharField(max_length=160, blank=True)
    search_text = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    uploaded_by = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "record_id"]
        indexes = [
            models.Index(fields=["record_type", "team"]),
            models.Index(fields=["record_type", "status"]),
            models.Index(
                fields=["canonical_record_id"],
                name="labapps_kno_canonic_cac87c_idx",
            ),
            models.Index(
                fields=["content_sha256"],
                name="labapps_kno_content_23b557_idx",
            ),
        ]


class LabAppAudit(models.Model):
    actor = models.EmailField(blank=True)
    app_id = models.CharField(max_length=64)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=255)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["app_id", "-timestamp"])]
