from django.db import models


class FiscalYear(models.Model):
    label = models.CharField(max_length=9, unique=True)
    spreadsheet_id = models.CharField(max_length=128, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    sync_state = models.CharField(max_length=20, default="pending")
    sync_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-label"]

    def __str__(self):
        return self.label


class CategoryAllocation(models.Model):
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="allocations")
    category = models.CharField(max_length=64)
    budget_usd = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["fiscal_year", "category"], name="unique_fy_category")
        ]
        ordering = ["category"]


class Team(models.Model):
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=120)
    allocation_usd = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    manager_emails = models.JSONField(default=list, blank=True)
    lead_emails = models.JSONField(default=list, blank=True)
    member_emails = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["fiscal_year", "name"], name="unique_fy_team")]
        ordering = ["name"]


class LabMember(models.Model):
    ROLE_CHOICES = [
        ("pi", "PI"),
        ("budget_manager", "Budget Manager"),
        ("lead", "Team Leader"),
        ("member", "Member"),
    ]
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=160, blank=True)
    highest_role = models.CharField(max_length=32, choices=ROLE_CHOICES, default="member")
    team_names = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.display_name or self.email


class Transaction(models.Model):
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="transactions")
    transaction_id = models.CharField(max_length=64)
    date = models.DateField(null=True, blank=True)
    category = models.CharField(max_length=64, blank=True)
    subcategory = models.CharField(max_length=100, blank=True)
    vendor = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    po_number = models.CharField(max_length=120, blank=True)
    invoice_number = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount_usd_equiv = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=32, default="Allocated")
    team = models.CharField(max_length=120, blank=True)
    entered_by = models.EmailField(blank=True)
    entry_method = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    pdf_link = models.URLField(max_length=1000, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "transaction_id"], name="unique_fy_transaction"
            )
        ]
        ordering = ["-date", "-transaction_id"]


class SyncRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("matched", "Matched"),
        ("mismatch", "Mismatch"),
        ("failed", "Failed"),
    ]
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="sync_runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running")
    actor = models.CharField(max_length=160, blank=True)
    source_transaction_count = models.PositiveIntegerField(default=0)
    mirror_transaction_count = models.PositiveIntegerField(default=0)
    source_totals = models.JSONField(default=dict, blank=True)
    mirror_totals = models.JSONField(default=dict, blank=True)
    differences = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class InvoiceDraft(models.Model):
    STATUS_CHOICES = [
        ("review", "Needs review"),
        ("ready", "Ready"),
        ("imported", "Imported"),
        ("dismissed", "Dismissed"),
    ]
    uploader_email = models.EmailField()
    file_name = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    parsed_data = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="review")
    imported_fiscal_year = models.CharField(max_length=9, blank=True)
    imported_transaction_id = models.CharField(max_length=64, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["uploader_email", "file_sha256"], name="unique_user_pdf")
        ]
        ordering = ["-created_at"]
