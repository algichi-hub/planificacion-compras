"""Selection lifecycle for the independent Mis SC tables.

Native Streamlit dataframe selection state is read-only; rotating widget keys
on context changes and explicit summary refresh ensures no preselected rows.
"""


def sync_my_sc_context(state, context):
    """Return widget revision; invalidate stale selections for another context."""
    if state.get("my_sc_context") != context:
        state["my_sc_context"] = context
        state["my_sc_revision"] = state.get("my_sc_revision", 0) + 1
    return state["my_sc_revision"]


def reset_my_sc_selection(state):
    """Reset both selection levels when Resumen is pressed again."""
    state["my_sc_revision"] = state.get("my_sc_revision", 0) + 1
    return state["my_sc_revision"]
