import importlib
import sys

import streamlit as st

RUNTIME_SCHEMA_VERSION = "2026-06-08-allocated-cancelled-status-v1"


def refresh_runtime_modules():
    """Reload shared app modules once per session after schema-level code changes."""
    if st.session_state.get("_runtime_schema_version") == RUNTIME_SCHEMA_VERSION:
        return
    for module_name in (
        "utils.categories",
        "utils.budget",
        "utils.sheets",
        "utils.parse_invoice",
        "utils.theme",
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            importlib.reload(module)
    st.session_state["_runtime_schema_version"] = RUNTIME_SCHEMA_VERSION
