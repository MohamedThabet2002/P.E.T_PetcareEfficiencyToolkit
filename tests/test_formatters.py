"""Tests for src/utils/formatters.py"""

import pytest

from src.utils.formatters import format_age


class TestFormatAge:
    def test_zero_months(self):
        assert format_age(0) == "0 months"

    def test_single_month(self):
        assert format_age(1) == "1 month"

    def test_multiple_months(self):
        assert format_age(5) == "5 months"

    def test_exactly_one_year(self):
        assert format_age(12) == "1 year"

    def test_one_year_and_months(self):
        assert format_age(13) == "1 year 1 month"
        assert format_age(15) == "1 year 3 months"

    def test_two_years(self):
        assert format_age(24) == "2 years"

    def test_two_years_and_months(self):
        assert format_age(27) == "2 years 3 months"

    def test_large_age(self):
        assert format_age(36) == "3 years"
        assert format_age(100) == "8 years 4 months"

    def test_float_input(self):
        assert format_age(5.5) == "5 months"
        assert format_age(13.9) == "1 year 1 month"

    def test_invalid_inputs(self):
        assert format_age(None) == ""
        assert format_age(-1) == ""
        assert format_age("5") == ""
        # NOTE: bool is a subclass of int in Python, so `True` passes the
        # isinstance check and gets converted to 1 month.
        assert format_age(True) == "1 month"
        assert format_age([]) == ""

    def test_boundary_values(self):
        assert format_age(11) == "11 months"
        assert format_age(12) == "1 year"
        assert format_age(23) == "1 year 11 months"
        assert format_age(24) == "2 years"
