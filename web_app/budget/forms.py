from django import forms

from budget.models import LabMember
from budget.services.calculations import CATEGORIES, SUPPORTED_CURRENCIES


STATUS_CHOICES = [("Allocated", "Allocated"), ("Cancelled", "Cancelled")]


class TransactionForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput)
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    fiscal_year = forms.ChoiceField()
    category = forms.ChoiceField(choices=[(value, value) for value in CATEGORIES])
    subcategory = forms.CharField(max_length=100, required=False)
    vendor = forms.CharField(max_length=240, label="Vendor / Payee")
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    po_number = forms.CharField(max_length=120, required=False, label="PO number")
    invoice_number = forms.CharField(max_length=120, required=False, label="Invoice number")
    currency = forms.ChoiceField(
        choices=[(value, value) for value in sorted(SUPPORTED_CURRENCIES)]
    )
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0.01)
    status = forms.ChoiceField(choices=STATUS_CHOICES, initial="Allocated")
    team = forms.ChoiceField()
    receipt_confirmed = forms.BooleanField(required=False)
    pdf_link = forms.URLField(
        required=False,
        max_length=1000,
        label="Receipt / PDF link",
        assume_scheme="https",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, year_choices=(), team_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"].choices = [(value, value) for value in year_choices]
        self.fields["team"].choices = [(value, value) for value in team_choices]


class ReceiptAttachmentForm(forms.Form):
    idempotency_key = forms.CharField(widget=forms.HiddenInput)
    receipt_confirmed = forms.BooleanField(required=False, label="Receipt confirmed")
    pdf_link = forms.URLField(
        required=False,
        max_length=1000,
        label="Receipt / PDF link",
        assume_scheme="https",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))


class AllocationForm(forms.Form):
    fiscal_year = forms.ChoiceField()

    def __init__(self, *args, year_choices=(), allocations=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"].choices = [(value, value) for value in year_choices]
        allocations = allocations or {}
        for category in CATEGORIES:
            self.fields[f"budget_{category.lower()}"] = forms.DecimalField(
                label=category,
                max_digits=16,
                decimal_places=2,
                min_value=0,
                initial=allocations.get(category, 0),
            )

    def allocation_values(self):
        return {
            category: self.cleaned_data[f"budget_{category.lower()}"]
            for category in CATEGORIES
        }


class TeamForm(forms.Form):
    fiscal_year = forms.ChoiceField()
    name = forms.CharField(max_length=120, label="Team name")
    allocation_usd = forms.DecimalField(
        max_digits=16, decimal_places=2, min_value=0, label="Allocation (USD)"
    )
    manager_emails = forms.CharField(required=False, label="Budget manager emails")
    lead_emails = forms.CharField(required=False, label="Team leader emails")
    member_emails = forms.CharField(required=False, label="Member emails")
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, year_choices=(), allow_manager_assignment=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"].choices = [(value, value) for value in year_choices]
        if not allow_manager_assignment:
            self.fields.pop("manager_emails", None)


class ExchangeRateForm(forms.Form):
    fiscal_year = forms.ChoiceField()
    aed_per_usd = forms.DecimalField(
        max_digits=16, decimal_places=6, min_value=0.000001, label="AED per USD"
    )
    eur_to_usd = forms.DecimalField(
        max_digits=16, decimal_places=6, min_value=0.000001, label="EUR to USD"
    )
    jpy_to_usd = forms.DecimalField(
        max_digits=16, decimal_places=8, min_value=0.00000001, label="JPY to USD"
    )
    gbp_to_usd = forms.DecimalField(
        max_digits=16, decimal_places=6, min_value=0.000001, label="GBP to USD"
    )

    def __init__(self, *args, year_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"].choices = [(value, value) for value in year_choices]


class WorkspaceSettingsForm(forms.Form):
    notification_threshold = forms.DecimalField(
        max_digits=5,
        decimal_places=1,
        min_value=1,
        max_value=100,
        label="Notification threshold (%)",
    )
    gmail_label = forms.CharField(
        max_length=200,
        label="Gmail label",
        initial="Budget/Invoices",
    )


class MemberForm(forms.Form):
    display_name = forms.CharField(max_length=160, label="Name")
    email = forms.EmailField()
    role = forms.ChoiceField(
        choices=[
            ("pi", "PI"),
            ("budget_manager", "Budget Manager"),
            ("member", "Team-scoped member or leader"),
        ],
        label="Lab-wide role",
    )
    active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, team_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.team_choices = list(team_choices)
        for index, team_name in enumerate(self.team_choices):
            self.fields[f"team_role_{index}"] = forms.ChoiceField(
                required=False,
                label=f"{team_name} role",
                choices=[
                    ("", "No access"),
                    ("member", "Member"),
                    ("lead", "Team Leader"),
                ],
            )

    def team_role_values(self):
        return {
            team_name: self.cleaned_data.get(f"team_role_{index}", "")
            for index, team_name in enumerate(self.team_choices)
            if self.cleaned_data.get(f"team_role_{index}")
        }


class ErbImportForm(forms.Form):
    excel_file = forms.FileField(
        label="NYUAD ERB Excel",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )
    category = forms.ChoiceField(choices=[(value, value) for value in CATEGORIES])
    subcategory = forms.CharField(max_length=100, required=False, initial="NYUAD Stores")
    team = forms.ChoiceField()

    def __init__(self, *args, team_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].choices = [(value, value) for value in team_choices]


class InvoiceCommitForm(TransactionForm):

    def __init__(self, *args, year_choices=(), team_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"].choices = [
            ("", "Select fiscal year"),
            *((value, value) for value in year_choices),
        ]
        self.fields["team"].choices = [(value, value) for value in team_choices]
        self.fields.pop("status", None)
        self.fields.pop("receipt_confirmed", None)
        self.fields.pop("pdf_link", None)
        self.fields.pop("idempotency_key", None)
