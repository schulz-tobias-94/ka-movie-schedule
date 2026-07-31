import pytest

from schauburg_schedule.sources.schauburg import VERSION_LABELS, version_label


@pytest.mark.parametrize("value, expected", [("OV", "OV"), ("ov", "ov"), ("OmU", "OmU"), ("OmeU", "OmeU"), ("OmdU", "OmdU"), ("DE", None), ("movie", None), ("OV extra", None)])
def test_version_labels_are_exact_and_case_insensitive(value, expected):
    assert version_label(value) == expected


def test_labels_are_configurable_in_one_constant():
    assert {"OV", "OmU", "OmeU", "OmdU"}.issubset(VERSION_LABELS)
