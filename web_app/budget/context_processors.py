def lab_context(request):
    member = getattr(request, "lab_member", None)
    return {"lab_member": member, "lab_role": getattr(member, "highest_role", "")}
