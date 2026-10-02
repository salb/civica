# tests/test_data_normalizer.py
#
# Test unitari su DataNormalizerAgent: un solo agente, isolato,
# senza orchestratore e senza LLM (l'agente è rule-based, niente mock).

import logging

import pytest

from agents_administrative_assistant import DataNormalizerAgent
from orchestrator import WorkflowState


def normalizza_data(valore: str) -> str:
    """Passa una singola data al normalizzatore e restituisce il risultato."""
    # PREPARA: uno stato minimo con un solo campo di tipo date
    stato = WorkflowState({
        "request_type": "prova",
        "collected_data": {"data": valore},
        "validation_schemas": {"prova": {"data": {"type": "date"}}},
    })
    agente = DataNormalizerAgent(logger=logging.getLogger("test"))

    # ESEGUI
    successo, dati = agente.run("default", stato)

    assert successo
    return dati["data"]


# VERIFICA: un test, molti casi. Ogni riga è (ingresso, uscita attesa).
@pytest.mark.parametrize("ingresso, atteso", [
    ("2026-04-03", "2026-04-03"),   # ISO: il formato che l'LLM produce
    ("03/04/2026", "2026-04-03"),   # italiano ambiguo: 3 aprile, non 4 marzo
    ("03.04.2026", "2026-04-03"),   # italiano con i punti
    ("13/04/2026", "2026-04-13"),   # italiano non ambiguo
    ("3/4/2026",   "2026-04-03"),   # italiano senza zeri iniziali
])
def test_date_normalizzate_in_formato_iso(ingresso, atteso):
    assert normalizza_data(ingresso) == atteso

def normalizza_booleano(valore: str):
    """Passa una singola risposta sì/no al normalizzatore e restituisce il risultato."""
    # PREPARA: uno stato minimo con un solo campo di tipo bool
    stato = WorkflowState({
        "request_type": "prova",
        "collected_data": {"risposta": valore},
        "validation_schemas": {"prova": {"risposta": {"type": "bool"}}},
    })
    agente = DataNormalizerAgent(logger=logging.getLogger("test"))

    # ESEGUI
    successo, dati = agente.run("default", stato)

    assert successo
    return dati["risposta"]


# Guardia: le forme negative esplicite devono restare False anche dopo la correzione.
@pytest.mark.parametrize("ingresso", ["no", "NO", " no ", "n", "false", "falso", "0", "off"])
def test_forme_negative_diventano_false(ingresso):
    assert normalizza_booleano(ingresso) is False


# Il caso nuovo: ciò che non è né sì né no resta mancante, così il validatore ripropone la domanda.
@pytest.mark.parametrize("ingresso", ["forse", "boh", "sì grazie", "nì", "2"],
                         ids=["forse", "boh", "si_grazie", "ni", "due"])
def test_risposte_non_riconosciute_restano_mancanti(ingresso):
    assert normalizza_booleano(ingresso) is None