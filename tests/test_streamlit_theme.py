"""Regression checks for switchable Streamlit themes inherited from LSE."""

from pathlib import Path
import tomllib


ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/".streamlit"/"config.toml"


def test_both_native_theme_variants_defined_with_light_default():
    config=tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    theme=config["theme"]
    assert theme["base"]=="light"
    assert "light" in theme and "dark" in theme
    for mode in ("light","dark"):
        colors=theme[mode]
        for key in (
            "primaryColor","backgroundColor","secondaryBackgroundColor",
            "textColor","borderColor","dataframeBorderColor",
            "dataframeHeaderBackgroundColor","dataframeHeaderTextColor",
        ):
            assert colors[key].startswith("#")
            assert len(colors[key])==7
        assert all(k in theme[mode]["sidebar"] for k in (
            "backgroundColor","secondaryBackgroundColor","textColor","borderColor"
        ))


def test_light_defaults_and_custom_palette_not_global():
    theme=tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]
    assert theme["light"]["backgroundColor"]=="#FFFFFF"
    assert theme["light"]["borderColor"]=="#E5E7EB"
    assert theme["light"]["primaryColor"]=="#2563EB"
    # Global color overrides would bleed through to the dark mode.
    for key in ("backgroundColor","textColor","secondaryBackgroundColor","primaryColor"):
        assert key not in theme


def test_streamlit_version_supports_both_theme_variants():
    requirements=(ROOT/"requirements.txt").read_text(encoding="utf-8")
    assert "streamlit>=1.52,<2" in requirements
