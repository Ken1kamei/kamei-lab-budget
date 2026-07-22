from django import forms

from budget.services.calculations import CATEGORIES, SUPPORTED_CURRENCIES


class InvoiceCommitForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    fiscal_year = forms.ChoiceField()
    category = forms.ChoiceField(choices=[(value, value) for value in CATEGORIES])
    subcategory = forms.CharField(max_length=100, required=False)
    vendor = forms.CharField(max_length=240)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    po_number = forms.CharField(max_length=120, required=False)
    invoice_number = forms.CharField(max_length=120, required=False)
    currency = forms.ChoiceField(
        choices=[(value, value) for value in sorted(SUPPORTED_CURRENCIES)]
    )
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0.01)
    team = forms.ChoiceField()
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, year_choices=(), team_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"].choices = [(value, value) for value in year_choices]
        self.fields["team"].choices = [(value, value) for value in team_choices]
