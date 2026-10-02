# tests/conftest.py
#
# Pytest carica questo file da solo, prima di qualunque test in tests/.
# Qui sta quello che ogni test darebbe per scontato.

import os
import socket
import sys

import pytest
import yaml

# 1. La radice del progetto, calcolata da questo file e non dalla
#    cartella da cui si lancia pytest. (Il percorso di import lo dà
#    pythonpath nel pyproject.toml.)
CARTELLA_PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2. Chiave finta IMPOSTA (non setdefault): anche se nella shell c'è
#    la chiave vera, i test non la vedono.
os.environ["OPENAI_API_KEY"] = "chiave-finta-per-test"

# 3. logger.demo() disponibile per tutti i test.
import logger_config  # noqa: E402,F401


# 4. Guardia: nessun test apre connessioni di rete.
#    Se un mock manca, il test fallisce subito invece di chiamare OpenAI.
@pytest.fixture(autouse=True)
def niente_rete(monkeypatch):
    def vietato(*args, **kwargs):
        raise RuntimeError("Un test ha provato ad aprire una connessione di rete: manca un mock.")
    monkeypatch.setattr(socket.socket, "connect", vietato)


# 5. Percorsi dei config, sempre assoluti.
@pytest.fixture
def percorso_config():
    def _percorso(nome_file):
        return os.path.join(CARTELLA_PROGETTO, "config", nome_file)
    return _percorso


@pytest.fixture
def config_principale(percorso_config):
    with open(percorso_config("config_administrative_assistant.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def config_ricerca(percorso_config):
    with open(percorso_config("config_research_assistant.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)