import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseForbidden
from google.auth.transport import requests
from google.oauth2 import id_token

from budget.models import LabMember


logger = logging.getLogger(__name__)
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


def verify_iap_assertion(assertion):
    return id_token.verify_token(
        assertion,
        requests.Request(),
        audience=settings.IAP_EXPECTED_AUDIENCE,
        certs_url=IAP_CERTS_URL,
    )


class IAPAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.IAP_EXPECTED_AUDIENCE or request.path == "/health/":
            return self.get_response(request)
        assertion = request.headers.get("X-Goog-IAP-JWT-Assertion", "")
        if not assertion:
            return HttpResponseForbidden("A verified IAP identity is required.")
        try:
            claims = verify_iap_assertion(assertion)
            email = str(claims.get("email", "")).strip().lower()
        except Exception:
            logger.warning("Rejected an invalid IAP assertion.")
            return HttpResponseForbidden("The IAP identity could not be verified.")
        try:
            member = LabMember.objects.get(email=email, active=True)
        except LabMember.DoesNotExist:
            return HttpResponseForbidden("Your NYU email is not in the Kamei Lab allowlist.")
        user, _ = get_user_model().objects.update_or_create(
            username=email,
            defaults={"email": email, "first_name": member.display_name[:150]},
        )
        if not request.user.is_authenticated or request.user.email != email:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.lab_member = member
        return self.get_response(request)
