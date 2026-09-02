from django import forms

from budget.member_accounts import validate_member_email
from .services.knowledge import MAX_KNOWLEDGE_FILE_BYTES


STATUS_CHOICES = [
    ("Not started", "Not started"),
    ("In progress", "In progress"),
    ("Blocked", "Blocked"),
    ("Completed", "Completed"),
]
REVIEW_CHOICES = [
    ("Pending", "Pending"),
    ("Approved", "Approved"),
    ("Revision requested", "Revision requested"),
]


class MemberForm(forms.Form):
    member_id = forms.CharField(required=False, widget=forms.HiddenInput)
    email = forms.EmailField(label="Email")
    name = forms.CharField(max_length=160, label="Full name")
    display_name = forms.CharField(max_length=160, required=False, label="Display name")
    global_role = forms.ChoiceField(
        choices=[
            ("pi", "Principal Investigator"),
            ("admin", "Administrator"),
            ("lead", "Team lead"),
            ("member", "Member"),
        ],
        label="Portal role",
    )
    active = forms.BooleanField(required=False, initial=True, label="Active member")
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def clean_email(self):
        try:
            return validate_member_email(self.cleaned_data["email"])
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error


class MemberDeleteForm(forms.Form):
    member_id = forms.CharField(widget=forms.HiddenInput)
    reassign_to_member_id = forms.ChoiceField(
        label="Transfer linked tracker records to",
        required=False,
        choices=[],
    )
    confirm_email = forms.EmailField(
        label="Type the member email to confirm permanent deletion"
    )

    def __init__(
        self,
        *args,
        members=None,
        reference_count=0,
        expected_email="",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["confirm_email"].help_text = (
            f"Enter exactly: {expected_email}" if expected_email else ""
        )
        if reference_count:
            self.fields["reassign_to_member_id"].required = True
            self.fields["reassign_to_member_id"].choices = [
                (
                    row["member_id"],
                    "{} — {} ({})".format(
                        row.get("display_name")
                        or row.get("name")
                        or row.get("email")
                        or row["member_id"],
                        row.get("email") or "no email",
                        row["member_id"],
                    ),
                )
                for row in (members or [])
                if str(row.get("member_id") or "").strip()
            ]
        else:
            self.fields.pop("reassign_to_member_id")


class TeamForm(forms.Form):
    team_name = forms.CharField(max_length=160)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    active = forms.BooleanField(required=False, initial=True)


class AppRoleForm(forms.Form):
    member_id = forms.ChoiceField(choices=[])
    app_id = forms.ChoiceField(choices=[])
    app_role = forms.ChoiceField(
        choices=[("viewer", "Viewer"), ("member", "Member"), ("lead", "Lead"), ("manager", "Manager"), ("owner", "Owner")]
    )
    scope_team_id = forms.ChoiceField(choices=[], required=False)
    active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, members=None, apps=None, teams=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member_id"].choices = [
            (row["member_id"], row.get("display_name") or row.get("name") or row["member_id"])
            for row in (members or [])
        ]
        self.fields["app_id"].choices = [
            (row["app_id"], row.get("app_name") or row["app_id"]) for row in (apps or [])
        ]
        self.fields["scope_team_id"].choices = [("", "All teams")] + [
            (row["team_id"], row.get("team_name") or row["team_id"]) for row in (teams or [])
        ]


class ProjectForm(forms.Form):
    project = forms.CharField(max_length=240)
    aim = forms.CharField(max_length=500)
    owner_member_id = forms.ChoiceField(choices=[])
    assigned_team_ids = forms.MultipleChoiceField(
        choices=[],
        required=False,
        label="Assigned teams",
        widget=forms.CheckboxSelectMultiple,
    )
    assigned_member_ids = forms.MultipleChoiceField(
        choices=[],
        required=False,
        label="Assigned lab members",
        widget=forms.CheckboxSelectMultiple,
    )
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    target_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, members=None, teams=None, **kwargs):
        super().__init__(*args, **kwargs)
        member_choices = [
            (row["member_id"], row.get("display_name") or row.get("name") or row["member_id"])
            for row in (members or [])
        ]
        self.fields["owner_member_id"].choices = member_choices
        self.fields["assigned_member_ids"].choices = member_choices
        self.fields["assigned_team_ids"].choices = [
            (row["team_id"], row.get("team_name") or row["team_id"])
            for row in (teams or [])
        ]

    def clean(self):
        cleaned = super().clean()
        owner_member_id = cleaned.get("owner_member_id")
        assigned_member_ids = list(cleaned.get("assigned_member_ids") or [])
        if owner_member_id and owner_member_id not in assigned_member_ids:
            assigned_member_ids.append(owner_member_id)
        cleaned["assigned_member_ids"] = assigned_member_ids
        return cleaned


class ProjectAssignmentForm(forms.Form):
    assigned_team_ids = forms.MultipleChoiceField(
        choices=[],
        required=False,
        label="Assigned teams",
        widget=forms.CheckboxSelectMultiple,
    )
    assigned_member_ids = forms.MultipleChoiceField(
        choices=[],
        required=False,
        label="Assigned lab members",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, members=None, teams=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_team_ids"].choices = [
            (row["team_id"], row.get("team_name") or row["team_id"])
            for row in (teams or [])
        ]
        self.fields["assigned_member_ids"].choices = [
            (
                row["member_id"],
                row.get("display_name") or row.get("name") or row["member_id"],
            )
            for row in (members or [])
        ]


class MilestoneForm(forms.Form):
    project_id = forms.ChoiceField(choices=[])
    milestone = forms.CharField(max_length=500)
    time_window = forms.CharField(max_length=120, required=False)
    owner_member_id = forms.ChoiceField(choices=[])
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    progress_percent = forms.DecimalField(
        min_value=0,
        max_value=100,
        decimal_places=1,
        required=False,
        initial=0,
        label="Progress (%)",
    )
    status = forms.ChoiceField(choices=STATUS_CHOICES)
    next_action = forms.CharField(max_length=500)
    blocker_reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    help_needed_from = forms.CharField(max_length=240, required=False)

    def __init__(self, *args, projects=None, members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project_id"].choices = [
            (row["project_id"], row.get("project") or row["project_id"]) for row in (projects or [])
        ]
        self.fields["owner_member_id"].choices = [
            (row["member_id"], row.get("display_name") or row.get("name") or row["member_id"])
            for row in (members or [])
        ]


class GanttImportForm(forms.Form):
    project_id = forms.ChoiceField(choices=[], label="Project")
    default_owner_member_id = forms.ChoiceField(
        choices=[],
        label="Default owner for unmatched names",
    )
    gantt_file = forms.FileField(
        label="Gantt Excel file",
        help_text="Upload the Kamei Lab template or a compatible .xlsx Gantt chart.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )

    def __init__(self, *args, projects=None, members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project_id"].choices = [
            (row["project_id"], row.get("project") or row["project_id"])
            for row in (projects or [])
        ]
        self.fields["default_owner_member_id"].choices = [
            (
                row["member_id"],
                row.get("display_name") or row.get("name") or row["member_id"],
            )
            for row in (members or [])
        ]

    def clean_gantt_file(self):
        uploaded = self.cleaned_data["gantt_file"]
        if not uploaded.name.casefold().endswith(".xlsx"):
            raise forms.ValidationError("Upload an .xlsx Excel workbook.")
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The Gantt workbook must be 10 MB or smaller.")
        return uploaded


class ExperimentForm(forms.Form):
    milestone_id = forms.ChoiceField(choices=[])
    member_id = forms.ChoiceField(choices=[])
    experiment_title = forms.CharField(max_length=500)
    experiment_type = forms.CharField(max_length=160, required=False)
    status = forms.ChoiceField(choices=STATUS_CHOICES)
    next_action = forms.CharField(max_length=500)
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    experiment_data_link = forms.URLField(required=False, assume_scheme="https")
    protocol_link = forms.URLField(required=False, assume_scheme="https")
    analysis_folder_link = forms.URLField(required=False, assume_scheme="https")
    blocker_reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    help_needed_from = forms.CharField(max_length=240, required=False)

    def __init__(self, *args, milestones=None, members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["milestone_id"].choices = [
            (row["milestone_id"], row.get("milestone") or row["milestone_id"])
            for row in (milestones or [])
        ]
        self.fields["member_id"].choices = [
            (row["member_id"], row.get("display_name") or row.get("name") or row["member_id"])
            for row in (members or [])
        ]


class ReviewForm(forms.Form):
    record_type = forms.ChoiceField(choices=[("Milestone", "Milestone"), ("Experiment", "Experiment")])
    record_id = forms.CharField(max_length=160)
    review_status = forms.ChoiceField(choices=REVIEW_CHOICES[1:])
    review_note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))


class KnowledgeUploadForm(forms.Form):
    record_type = forms.ChoiceField(choices=[("notebook", "Notebook"), ("protocol", "Protocol")])
    status = forms.ChoiceField(
        choices=[("draft", "Draft"), ("active", "Active")],
        initial="active",
        required=False,
    )
    title = forms.CharField(max_length=500)
    team = forms.CharField(max_length=240)
    owner = forms.CharField(max_length=240)
    category = forms.CharField(max_length=120, required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    files = forms.FileField(
        widget=forms.ClearableFileInput(
            attrs={
                "multiple": False,
                "accept": ".docx,.pdf,.txt,.md,.xlsx,.pptx,.csv,.png,.jpg,.jpeg,.tif,.tiff",
            }
        ),
        help_text="Upload a lab document (25 MB maximum). DOCX, PDF, MD, and TXT content is extracted automatically.",
    )

    def clean_files(self):
        uploaded = self.cleaned_data["files"]
        allowed = {
            ".docx",
            ".pdf",
            ".txt",
            ".md",
            ".xlsx",
            ".pptx",
            ".csv",
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
        }
        suffix = "." + uploaded.name.rsplit(".", 1)[-1].casefold() if "." in uploaded.name else ""
        if suffix not in allowed:
            raise forms.ValidationError(
                "Upload a supported document, spreadsheet, presentation, text, or image file."
            )
        if uploaded.size > MAX_KNOWLEDGE_FILE_BYTES:
            raise forms.ValidationError("The uploaded file must be 25 MB or smaller.")
        return uploaded

    def clean_status(self):
        return self.cleaned_data.get("status") or "active"


class KnowledgeStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            ("draft", "Draft"),
            ("active", "Active"),
            ("archived", "Archived"),
        ]
    )
