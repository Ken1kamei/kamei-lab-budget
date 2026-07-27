import pytest
from django.test import override_settings

from budget.member_accounts import validate_member_email


@override_settings(LAB_MEMBER_EMAIL_EXCEPTIONS={"nyuadkameilab@gmail.com"})
def test_member_email_policy_accepts_nyu_and_configured_lab_account():
    assert validate_member_email(" MEMBER@NYU.EDU ") == "member@nyu.edu"
    assert (
        validate_member_email("NYUADKAMEILAB@GMAIL.COM")
        == "nyuadkameilab@gmail.com"
    )


@override_settings(LAB_MEMBER_EMAIL_EXCEPTIONS={"nyuadkameilab@gmail.com"})
def test_member_email_policy_rejects_other_accounts():
    with pytest.raises(ValueError, match="Use an @nyu.edu account"):
        validate_member_email("someone@gmail.com")
