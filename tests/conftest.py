from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def good_rules_path() -> Path:
    return FIXTURES / "good_rules.yml"


@pytest.fixture
def bad_rules_path() -> Path:
    return FIXTURES / "bad_rules.yml"


@pytest.fixture
def realistic_rules_path() -> Path:
    return FIXTURES / "realistic.yml"
