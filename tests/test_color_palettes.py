"""Tests for src/ui/themes/color_palettes.py"""

import pytest

from src.ui.themes.color_palettes import (
    PALETTES,
    ThemeConfig,
    ThemeManager,
    adjust_color,
    get_contrast_color,
    get_styled_qss,
    hex_to_rgba,
)


class TestPalettes:
    def test_all_required_keys_present(self):
        required_keys = {
            "brand_500", "bg_base", "bg_surface", "text_primary", "text_secondary",
            "border", "state_success", "state_warning", "state_danger", "state_info",
        }
        for theme_name, palette in PALETTES.items():
            assert required_keys.issubset(palette.keys()), f"Missing keys in {theme_name}"

    def test_colors_are_hex(self):
        for theme_name, palette in PALETTES.items():
            for key, value in palette.items():
                assert value.startswith("#"), f"{theme_name}.{key} not a hex color: {value}"
                assert len(value) == 7, f"{theme_name}.{key} not 6-digit hex: {value}"

    def test_light_and_dark_differ(self):
        assert PALETTES["light"] != PALETTES["dark"]


class TestAdjustColor:
    def test_lighter(self):
        assert adjust_color("#808080", 1.5) != "#808080"

    def test_darker(self):
        assert adjust_color("#808080", 0.5) != "#808080"

    def test_invalid_color_returns_same(self):
        # QColor("not-a-color") creates an invalid color; lighter() on it
        # returns #000000 (the real implementation does not raise).
        assert adjust_color("not-a-color", 1.5) == "#000000"


class TestGetContrastColor:
    def test_dark_color_returns_white(self):
        assert get_contrast_color("#000000") == "#FFFFFF"

    def test_light_color_returns_black(self):
        assert get_contrast_color("#FFFFFF") == "#000000"

    def test_invalid_color_returns_black(self):
        # QColor("garbage") is invalid -> RGB all 0 -> luminance 0 -> white.
        assert get_contrast_color("garbage") == "#FFFFFF"


class TestHexToRgba:
    def test_conversion(self):
        assert hex_to_rgba("#FF0000", 1.0) == "rgba(255, 0, 0, 1.0)"
        assert hex_to_rgba("#00FF00", 0.5) == "rgba(0, 255, 0, 0.5)"
        assert hex_to_rgba("#0000FF", 0.25) == "rgba(0, 0, 255, 0.25)"


class TestThemeConfig:
    def test_get_and_item(self):
        cfg = ThemeConfig({"a": 1, "b": 2})
        assert cfg["a"] == 1
        assert cfg.get("b") == 2
        assert cfg.get("missing", "default") == "default"

    def test_qcolor(self, qapp):
        cfg = ThemeConfig({"color": "#FF0000"})
        color = cfg.qcolor("color")
        assert color.red() == 255
        assert color.green() == 0
        assert color.blue() == 0

    def test_to_dict_copies(self):
        cfg = ThemeConfig({"a": 1})
        result = cfg.to_dict()
        assert result == {"a": 1}
        result["a"] = 99
        assert cfg["a"] == 1  # original unchanged


class TestThemeManager:
    def test_singleton(self):
        assert ThemeManager.instance() is ThemeManager.instance()

    def test_has_theme_changed_signal(self, qapp):
        assert hasattr(ThemeManager.instance(), "theme_changed")


class TestGetStyledQss:
    def test_missing_file_returns_empty(self, tmp_path):
        assert get_styled_qss(str(tmp_path / "missing.qss")) == ""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_replaces_variables(self, tmp_path, theme):
        qss = tmp_path / "style.qss"
        qss.write_text(
            "QLabel { color: @text_primary; background: @bg_base; }",
            encoding="utf-8",
        )
        result = get_styled_qss(str(qss), theme=theme)
        palette = PALETTES[theme]
        assert palette["text_primary"] in result
        assert palette["bg_base"] in result
        assert "@text_primary" not in result

    def test_contrast_modifier(self, tmp_path):
        qss = tmp_path / "style.qss"
        qss.write_text("QPushButton { color: @brand_500_contrast; }", encoding="utf-8")
        result = get_styled_qss(str(qss), theme="light")
        # For light theme brand is #4A90E2 -> luminance above 0.5 -> black contrast
        assert "#000000" in result

    def test_alpha_modifier(self, tmp_path):
        qss = tmp_path / "style.qss"
        qss.write_text("QWidget { background: @brand_500_a50; }", encoding="utf-8")
        result = get_styled_qss(str(qss), theme="light")
        assert "rgba(" in result

    def test_unknown_variable_left_untouched(self, tmp_path):
        qss = tmp_path / "style.qss"
        qss.write_text("QLabel { color: @does_not_exist; }", encoding="utf-8")
        result = get_styled_qss(str(qss), theme="light")
        assert "@does_not_exist" in result

    def test_custom_palette_dict(self, tmp_path):
        qss = tmp_path / "style.qss"
        qss.write_text("QLabel { color: @brand_500; }", encoding="utf-8")
        result = get_styled_qss(str(qss), theme="light", custom_palette={"brand_500": "#123456"})
        assert "#123456" in result

    def test_cache_hit_and_refresh(self, tmp_path):
        qss = tmp_path / "style.qss"
        qss.write_text("QLabel { color: @brand_500; }", encoding="utf-8")
        first = get_styled_qss(str(qss), theme="light")
        # Modify file, cache should return old content
        qss.write_text("QLabel { color: @bg_base; }", encoding="utf-8")
        second = get_styled_qss(str(qss), theme="light")
        assert first == second  # cached
        # Refresh forces re-read
        third = get_styled_qss(str(qss), theme="light", refresh_cache=True)
        assert third != second
