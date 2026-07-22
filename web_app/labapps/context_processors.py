from .permissions import can_write, current_registry_member, is_portal_admin


APP_SHELLS = {
    "budget": ("Budget Manager", "Budget and invoice management"),
    "tracker": ("Project Tracker", "Research operations"),
    "knowledge": ("Notebooks / Protocols", "Private lab knowledge"),
    "registry": ("Lab Registry", "Members, teams, and access"),
    "portal": ("Kamei Lab", "Private lab portal"),
}


def _navigation_section(request):
    match = getattr(request, "resolver_match", None)
    namespace = getattr(match, "namespace", "")
    url_name = getattr(match, "url_name", "") or ""
    if namespace == "budget":
        return "budget"
    if namespace == "labapps":
        if url_name == "portal":
            return "portal"
        if url_name == "portal_admin":
            return "registry"
        if url_name == "tracker":
            return "tracker"
        if url_name.startswith("knowledge"):
            return "knowledge"
    return "portal"


def lab_apps_context(request):
    member = current_registry_member(request)
    section = _navigation_section(request)
    title, subtitle = APP_SHELLS[section]
    app_id = {
        "budget": "budget",
        "tracker": "project_tracker",
        "knowledge": "notebooks_protocols",
    }.get(section)
    return {
        "registry_member": member,
        "lab_apps_admin": is_portal_admin(member),
        "lab_nav_section": section,
        "lab_nav_title": title,
        "lab_nav_subtitle": subtitle,
        "lab_nav_can_write": bool(app_id and can_write(member, app_id)),
    }
