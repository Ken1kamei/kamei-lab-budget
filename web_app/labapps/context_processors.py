from .permissions import current_registry_member, is_portal_admin


def lab_apps_context(request):
    member = current_registry_member(request)
    return {
        "registry_member": member,
        "lab_apps_admin": is_portal_admin(member),
    }
