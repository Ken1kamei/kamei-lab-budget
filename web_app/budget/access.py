from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from budget.models import LabMember


ROLE_PRIORITY = {"member": 1, "lead": 2, "budget_manager": 3, "pi": 4}


def current_member(request):
    if not request.user.is_authenticated:
        return None
    email = str(request.user.email or "").strip().lower()
    try:
        member = LabMember.objects.get(email=email, active=True)
    except LabMember.DoesNotExist:
        return None
    request.lab_member = member
    return member


def lab_access(minimum_role="member"):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("budget:login")
            member = current_member(request)
            if member is None:
                return HttpResponseForbidden("Your NYU email is not in the Kamei Lab allowlist.")
            if ROLE_PRIORITY.get(member.highest_role, 0) < ROLE_PRIORITY[minimum_role]:
                return HttpResponseForbidden("You do not have permission to view this page.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
