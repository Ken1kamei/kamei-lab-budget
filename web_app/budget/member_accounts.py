from django.conf import settings


def normalize_member_email(value):
    return str(value or "").strip().lower()


def allowed_member_email(value):
    email = normalize_member_email(value)
    return bool(
        email
        and (
            email.endswith("@nyu.edu")
            or email in settings.LAB_MEMBER_EMAIL_EXCEPTIONS
        )
    )


def validate_member_email(value):
    email = normalize_member_email(value)
    if allowed_member_email(email):
        return email
    exceptions = ", ".join(sorted(settings.LAB_MEMBER_EMAIL_EXCEPTIONS))
    raise ValueError(
        "Use an @nyu.edu account"
        + (f" or an approved lab account ({exceptions})." if exceptions else ".")
    )
