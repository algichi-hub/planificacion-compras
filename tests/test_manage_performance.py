"""Regression for isolated Manage fragment and selective cache invalidation."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_manage_updates_do_not_flush_erp_query_cache():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "query.clear()" not in app
    assert "@st.cache_data(ttl=600,show_spinner=False)\ndef group_catalogue" in app
    assert "@st.cache_data(ttl=600,show_spinner=False)\ndef group_items" in app
    assert "groups=group_catalogue()" in app
    assert "items=group_items(group_id)" in app
    assert "group_catalogue.clear()" in app
    assert "group_items.clear()" in app


def test_aggrid_fragment_confines_edit_reruns():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    manage=app.split("with tab4:",1)[1]
    start=manage.index("            @st.fragment\n            def render_manage_grid():")
    end=manage.index("            render_manage_grid()",start)
    fragment=manage[start:end]
    assert "items_manage=group_items(group_id_manage)" in fragment
    assert "AgGrid(" in fragment
    assert 'st.rerun(scope="fragment")' in fragment
    assert "query.clear()" not in fragment
    assert "group_catalogue.clear()" not in fragment
    assert "st.rerun()" not in fragment
    assert "group_items.clear()" not in fragment
    assert "write_bulk(" in fragment
    assert '"bulk_result"' not in fragment
    assert 'key=f"manage_grid_{group_id_manage}_{st.session_state[revision_key]}"' in fragment


def test_group_management_updates_invalidate_only_group_data():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    manage=app.split("with tab4:",1)[1]
    refresh=manage.split("def _refresh_manage():",1)[1].split("@st.dialog",1)[0]
    assert "group_items.clear()" in refresh
    assert 'st.session_state.pop("bulk_result",None)' in refresh
    assert "query.clear()" not in refresh
    assert "group_catalogue.clear()" not in refresh
    # A metadata change must invalidate catalogue AND membership, not the ERP cache.
    assert manage.count("group_catalogue.clear()")==3
    assert manage.count("group_items.clear()")==4


def test_no_new_polling_or_database_writes_in_group_report():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert "write_bulk(" not in group
    assert "items=group_items(group_id)" in group
    assert "st.dataframe(" in group
    assert "st_autorefresh" not in app
