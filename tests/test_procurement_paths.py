# tests/test_procurement_paths.py
#
# Strato 2, i percorsi del workflow acquisti diversi dal caso fortunato:
# - un campo manca: la domanda all'utente e la ripresa;
# - il budget non basta, o il progetto non esiste: rifiuto senza altre
#   chiamate al modello;
# - i riferimenti normativi vengono dallo YAML, non dal codice.

import logging
from unittest.mock import patch

import pytest

from agents_administrative_assistant import (
    DataExtractorAgent,
    SemanticEnrichmentAgent,
    get_agent_instance,
)
from core_framework import DebuggerAgent
from orchestrator import AdvancedOrchestrator, create_composite_factory

ESTRAZIONE_COMPLETA = {
    "descrizione_bene": "Workstation per elaborazione dati sismici",
    "costo_stimato": 1200.0,
    "motivazione": "Serve per il progetto",
    "progetto": "prin2024-02",
    "nome_richiedente": "mario rossi",
    "fornitore_suggerito": "Rossi Informatica srl",
    "cf_fornitore": "01234567890",
    "cig": "B123456789",
    "numero_impegno": "2026/0042",
    "data_impegno": "2026-09-15",
    "capitolo_spesa": "1.03.02",
    "obiettivo_funzione": "OF-01",
    "urgenza": None,
}


@pytest.fixture
def orchestratore(config_principale, percorso_config):
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), factory, config_principale)
    orch.state.set_request_type("richiesta_acquisto")
    orch.state.set_global_variable("user_request", "richiesta finta")
    return orch


def esegui(orch, estrazione, monkeypatch=None, risposte=None):
    """Esegue il workflow; restituisce risultato, domande poste e mock dell'arricchimento."""
    domande = []
    if monkeypatch is not None:
        risposte = list(risposte or [])

        def input_finto(domanda):
            domande.append(domanda)
            return risposte.pop(0)
        monkeypatch.setattr("builtins.input", input_finto)

    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, dict(estrazione))), \
         patch.object(SemanticEnrichmentAgent, "_call_llm",
                      return_value=(True, "Motivazione formale.")) as arricchimento, \
         patch.object(DebuggerAgent, "_call_llm", return_value=(True, {"impatto_fallimento": "BASSO"})):
        risultato = orch.run_iterative_workflow()
    return risultato, domande, arricchimento


# --- Un campo manca: domanda, risposta, ripresa ---
def test_un_campo_mancante_diventa_una_domanda_e_il_workflow_riprende(orchestratore, monkeypatch):
    estrazione = {**ESTRAZIONE_COMPLETA, "cig": None}
    risultato, domande, _ = esegui(orchestratore, estrazione, monkeypatch, ["Z987654321"])
    assert domande == ["❓ Qual è il Codice Identificativo di Gara (CIG)? "]
    assert risultato["cig"] == "Z987654321"
    assert risultato["modalita_acquisto"] == "Ordine Diretto di Acquisto (OdA) su MEPA"


def test_una_risposta_vuota_ripropone_la_domanda(orchestratore, monkeypatch):
    estrazione = {**ESTRAZIONE_COMPLETA, "cig": None}
    risultato, domande, _ = esegui(orchestratore, estrazione, monkeypatch, ["   ", "Z987654321"])
    assert len(domande) == 2
    assert risultato["cig"] == "Z987654321"


# --- Rifiuti: nessuna ulteriore chiamata al modello ---
def test_un_costo_oltre_il_budget_viene_respinto(orchestratore):
    estrazione = {**ESTRAZIONE_COMPLETA, "costo_stimato": 20000.0}   # budget PRIN: 15000
    risultato, _, arricchimento = esegui(orchestratore, estrazione)
    assert risultato["esito"] == "RESPINTA"
    assert "exceeds the available budget" in risultato["motivazione"]
    assert not arricchimento.called


def test_un_progetto_sconosciuto_viene_respinto(orchestratore):
    # Prima della 1.0.2 riceveva un budget di default e veniva approvato.
    estrazione = {**ESTRAZIONE_COMPLETA, "progetto": "progetto-inventato", "costo_stimato": 900.0}
    risultato, _, arricchimento = esegui(orchestratore, estrazione)
    assert risultato["esito"] == "RESPINTA"
    assert "PROGETTO-INVENTATO" in risultato["motivazione"]
    assert not arricchimento.called


# --- La normativa sta nello YAML ---
def test_sopra_soglia_si_applica_la_procedura_dichiarata_nello_yaml(orchestratore):
    estrazione = {**ESTRAZIONE_COMPLETA, "costo_stimato": 8000.0}    # soglia 5000, budget 15000
    risultato, _, _ = esegui(orchestratore, estrazione)
    assert risultato["modalita_acquisto"] == "Procedura Negoziata senza Bando"
    assert risultato["riferimento_normativo_completo"] == "d.lgs. 36/2023, art. 76"


def test_cambiare_la_norma_nello_yaml_cambia_il_modulo(orchestratore):
    regole = orchestratore.config["business_rules"]["acquisti"]
    regole["procedura_sotto_soglia"]["normativa_rif"] = "nuovo codice 2027"
    regole["procedura_sotto_soglia"]["articolo_norma_rif"] = "art. 1"
    risultato, _, _ = esegui(orchestratore, ESTRAZIONE_COMPLETA)
    assert risultato["riferimento_normativo_completo"] == "nuovo codice 2027, art. 1"


def test_regole_di_acquisto_mancanti_sono_un_fallimento(orchestratore):
    del orchestratore.config["business_rules"]["acquisti"]["procedura_sopra_soglia"]
    risultato, _, _ = esegui(orchestratore, ESTRAZIONE_COMPLETA)
    assert risultato["status"] == "failed"
    assert risultato["failed_agent"] == "procurement_decision_agent"
    assert "procedura_sopra_soglia" in risultato["error"]
