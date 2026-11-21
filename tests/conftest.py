import shutil
import socket
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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Memvo promises it never goes online; any socket use fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("memvo tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
