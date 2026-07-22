import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory

from budget.middleware import IAPAuthenticationMiddleware
from budget.models import LabMember


@pytest.mark.django_db
def test_iap_middleware_verifies_assertion_and_logs_in_allowlisted_member(settings, monkeypatch):
    settings.IAP_EXPECTED_AUDIENCE = "/projects/123/locations/test/services/budget"
    LabMember.objects.create(email="member@nyu.edu", display_name="Member", active=True)
    monkeypatch.setattr(
        "budget.middleware.verify_iap_assertion",
        lambda assertion: {"email": "member@nyu.edu", "sub": "accounts.google.com:123"},
    )
    request = RequestFactory().get("/", HTTP_X_GOOG_IAP_JWT_ASSERTION="signed")
    request.session = __import__("django.contrib.sessions.backends.db", fromlist=["SessionStore"]).SessionStore()
    request.user = __import__("django.contrib.auth.models", fromlist=["AnonymousUser"]).AnonymousUser()
    middleware = IAPAuthenticationMiddleware(lambda req: HttpResponse(req.user.email))

    response = middleware(request)

    assert response.status_code == 200
    assert response.content == b"member@nyu.edu"
    assert get_user_model().objects.filter(email="member@nyu.edu").exists()


@pytest.mark.django_db
def test_iap_middleware_rejects_unknown_member(settings, monkeypatch):
    settings.IAP_EXPECTED_AUDIENCE = "/projects/123/locations/test/services/budget"
    monkeypatch.setattr(
        "budget.middleware.verify_iap_assertion", lambda assertion: {"email": "unknown@nyu.edu"}
    )
    request = RequestFactory().get("/", HTTP_X_GOOG_IAP_JWT_ASSERTION="signed")
    request.session = __import__("django.contrib.sessions.backends.db", fromlist=["SessionStore"]).SessionStore()
    request.user = __import__("django.contrib.auth.models", fromlist=["AnonymousUser"]).AnonymousUser()

    response = IAPAuthenticationMiddleware(lambda req: HttpResponse("ok"))(request)

    assert response.status_code == 403
