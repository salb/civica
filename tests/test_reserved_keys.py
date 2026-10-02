# tests/test_reserved_keys.py
#
# Strato 1, contratto del core: le chiavi con un setter dedicato non
# si possono scrivere con set_global_variable. Lo scrittore generico
# rifiuta, con un errore esplicito, e non lascia tracce nello stato.

import pytest

from orchestrator import WorkflowState

# Il contratto, scritto qui per intero e NON letto da _RESERVED_KEYS:
# se qualcuno togliesse una chiave dall'elenco nel codice, il test
# deve accorgersene.
CHIAVI_RISERVATE = [
    "current_phase",
    "request_type",
    "final_output",
    "collected_data",
    "pending_questions",
    "current_cycle",
    "business_rules",
    "prompt_templates",
    "output_templates",
    "validation_schemas",
]


@pytest.mark.parametrize("chiave", CHIAVI_RISERVATE)
def test_la_chiave_riservata_viene_rifiutata(chiave):
    stato = WorkflowState({})
    with pytest.raises(ValueError, match=chiave):
        stato.set_global_variable(chiave, "valore abusivo")


@pytest.mark.parametrize("chiave", CHIAVI_RISERVATE)
def test_il_rifiuto_non_lascia_tracce_nello_stato(chiave):
    stato = WorkflowState({})
    with pytest.raises(ValueError):
        stato.set_global_variable(chiave, "valore abusivo")
    assert chiave not in stato.as_dict()


def test_una_chiave_dinamica_viene_scritta():
    # Guardia: lo scrittore generico funziona per le chiavi non riservate.
    stato = WorkflowState({})
    stato.set_global_variable("temp_input", "testo")
    assert stato.as_dict()["temp_input"] == "testo"
