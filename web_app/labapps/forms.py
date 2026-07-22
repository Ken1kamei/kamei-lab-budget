from django import forms


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
    email = forms.EmailField()
    name = forms.CharField(max_length=160)
    display_name = forms.CharField(max_length=160, required=False)
    global_role = forms.ChoiceField(
        choices=[("pi", "PI"), ("admin", "Admin"), ("lead", "Team lead"), ("member", "Member")]
    )
    active = forms.BooleanField(required=False, initial=True)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


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
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    target_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_member_id"].choices = [
            (row["member_id"], row.get("display_name") or row.get("name") or row["member_id"])
            for row in (members or [])
        ]


class MilestoneForm(forms.Form):
    project_id = forms.ChoiceField(choices=[])
    milestone = forms.CharField(max_length=500)
    time_window = forms.CharField(max_length=120, required=False)
    owner_member_id = forms.ChoiceField(choices=[])
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
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
    title = forms.CharField(max_length=500)
    team = forms.CharField(max_length=240)
    owner = forms.CharField(max_length=240)
    category = forms.CharField(max_length=120, required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    files = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"multiple": False}),
        help_text="Upload a lab notebook or protocol document.",
    )
