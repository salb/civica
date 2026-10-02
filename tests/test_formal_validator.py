# tests/test_formal_validator.py
#
# Test unitari su FormalValidatorAgent: quando un campo obbligatorio
# va considerato mancante (e quindi chiesto all'utente).

import logging

import pytest

from agents_administrative_assistant import FormalValidatorAgent
from orchestrator import WorkflowState


def campi_da_chiedere(valore) -> list:
    """Valida un solo campo obbligatorio e restituisce le chiavi da chiedere."""
    # PREPARA
    stato = WorkflowState({
        "request_type": "prova",
        "collected_data": {"campo": valore},
        "validation_schemas": {"prova": {"campo": {"required": True}}},
    })
    agente = FormalValidatorAgent(logger=logging.getLogger("test"))

    # ESEGUI
    successo, esito = agente.run("prova", stato)

    assert successo
    return [domanda["key"] for domanda in esito["pending_questions"]]


# Valori che per un campo obbligatorio significano "manca"
@pytest.mark.parametrize("valore", [None, "", "   ", []])
def test_campo_obbligatorio_vuoto_viene_chiesto(valore):
    assert campi_da_chiedere(valore) == ["campo"]


# Valori legittimi che NON devono essere scambiati per mancanti
@pytest.mark.parametrize("valore", ["Mario Rossi", False, 0])
def test_campo_obbligatorio_valorizzato_non_viene_chiesto(valore):
    assert campi_da_chiedere(valore) == []
