import shutil
from pathlib import Path

import pytest

from memvo.vault import Vault

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def files(tmp_path) -> Path:
    """Copies of the fixtures, so tests may edit them."""
    dst = tmp_path / "statements"
    shutil.copytree(FIXTURES, dst)
    return dst


@pytest.fixture
def vault(tmp_path):
    v = Vault.init(tmp_path / "vault.db")
    yield v
    v.close()
