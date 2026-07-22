from django import template


register = template.Library()


@register.filter
def get_item(mapping, key):
    if not mapping:
        return ""
    value = mapping.get(key, {})
    if isinstance(value, dict):
        return value.get("display_name") or value.get("name") or key
    return value


@register.filter
def metadata(record, key):
    return (record.metadata or {}).get(key, "")
