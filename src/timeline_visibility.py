"""Independent, lazy timeline visibility and data caches for each Streamlit view.

The state container is passed in explicitly for deterministic tests; no
Streamlit dependency or Neon calls live in this module.
"""


def sync_context(state, scope, context):
    """A new snapshot, SC or group always starts with its timeline hidden."""
    prefix = f"{scope}_timeline"
    if state.get(f"{prefix}_context") != context:
        state[f"{prefix}_context"] = context
        state[f"{prefix}_visible"] = False
        state.pop(f"{prefix}_data", None)


def reset_timeline(state, scope):
    """A new report invalidates its own timeline, not the other section."""
    prefix = f"{scope}_timeline"
    state[f"{prefix}_visible"] = False
    state.pop(f"{prefix}_data", None)


def toggle_timeline(state, scope):
    """Toggle just one view; never clear the fetched data on hide."""
    key = f"{scope}_timeline_visible"
    state[key] = not bool(state.get(key, False))
    return state[key]


def timeline_visible(state, scope):
    return bool(state.get(f"{scope}_timeline_visible", False))
