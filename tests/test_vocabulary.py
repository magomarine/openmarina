"""Tests for the controlled vocabulary."""
import pytest
import openmarina as om
from openmarina import vocabulary as vocab


def test_known_variables_and_units():
    assert vocab.is_variable("wave_height_significant")
    assert vocab.unit_for("air_pressure") == "Pa"
    assert vocab.unit_for("water_temperature") == "degree_celsius"


def test_unknown_variable_raises_vocabulary_error():
    with pytest.raises(om.VocabularyError):
        vocab.get("sea_vibes")


def test_direction_convention_split():
    assert vocab.get("wind_direction").direction == "from"
    assert vocab.get("wave_direction").direction == "from"
    assert vocab.get("current_direction").direction == "to"


def test_bounds():
    assert vocab.in_bounds("wave_height_significant", 1.5)
    assert not vocab.in_bounds("wave_height_significant", -1.0)
    assert not vocab.in_bounds("salinity", 99.0)
