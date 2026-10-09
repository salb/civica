# tests/test_agent_failures.py
#
# Strato 2: un agente che itera su una lista e fallisce su un elemento
# fa fallire il workflow. Prima della 1.0.2 questi fallimenti venivano
# assorbiti: un segnaposto nella lettera di risposta, una categoria
# "sconosciuta", un'attività del timesheet non arricchita. Il documento
# veniva comunque prodotto come se fosse completo.

import logging
from unittest.mock import patch

import pytest

from agents_administrative_assistant import (
    DataExtractorAgent,
    IterativeEnrichmentAgent,
    get_agent_instance as fabbrica_amministrativa,
)
from agents_research_assistant import (
    CritiqueCategoriserAgent,
    ResponseStrategistAgent,
    ReviewParserAgent,
    get_agent_instance as fabbrica_ricerca,
)
from core_framework import DebuggerAgent
from orchestrator import AdvancedOrchestrator, create_composite_factory

DIAGNOSI_FINTA = (True, {"impatto_fallimento": "BASSO"})
ERRORE_API = (False, {"failure_reason": "API non raggiungibile"})

COMMENTI = {"commenti_revisori": [
    {"revisore": "1", "id": 1, "testo": "Manca la risoluzione della rete."},
    {"revisore": "1", "id": 2, "testo": "Refuso in figura 3."},
]}


@pytest.fixture
def supporto_review(tmp_path, monkeypatch, percorso_config, config_ricerca):
    """Un orchestratore del supporto review con due file veri in tmp_path."""
    (tmp_path / "review.md").write_text("Revisore 1 ...", encoding="utf-8")
    (tmp_path / "draft.md").write_text("Il manoscritto.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    factory = create_composite_factory(fabbrica_ricerca, logging.getLogger("test"))
    orch = AdvancedOrchestrator(percorso_config("config_review_support.yaml"), factory, config_ricerca)
    orch.state.set_global_variable("run_id", "test")
    orch.state.set_global_variable("start_timestamp", "20261009")
    orch.state.set_global_variable("task_overrides", {"file_reader_agent": {
        "file_review": "review.md", "file_draft": "draft.md"}})
    return orch


def test_una_risposta_non_generata_fa_fallire_il_supporto_review(supporto_review, tmp_path):
    with patch.object(ReviewParserAgent, "_call_llm", return_value=(True, COMMENTI)), \
         patch.object(CritiqueCategoriserAgent, "_call_llm", return_value=(True, {"categoria": "Errore Minore"})), \
         patch.object(ResponseStrategistAgent, "_call_llm", side_effect=[(True, "Risposta."), ERRORE_API]), \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA):
        risultato = supporto_review.run_iterative_workflow()

    assert risultato["status"] == "failed"
    assert risultato["failed_agent"] == "response_strategist_agent"
    assert "#2" in risultato["error"] and "API non raggiungibile" in risultato["error"]
    # Nessuna lettera salvata come se fosse completa.
    assert not (tmp_path / "output").exists()


def test_una_categoria_non_assegnata_fa_fallire_il_supporto_review(supporto_review):
    with patch.object(ReviewParserAgent, "_call_llm", return_value=(True, COMMENTI)), \
         patch.object(CritiqueCategoriserAgent, "_call_llm", side_effect=[(True, {"categoria": "x"}), ERRORE_API]), \
         patch.object(ResponseStrategistAgent, "_call_llm") as stratega, \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA):
        risultato = supporto_review.run_iterative_workflow()

    assert risultato["status"] == "failed"
    assert risultato["failed_agent"] == "critique_categoriser_agent"
    assert not stratega.called


def test_un_arricchimento_non_riuscito_fa_fallire_il_timesheet(config_principale, percorso_config):
    factory = create_composite_factory(fabbrica_amministrativa, logging.getLogger("test"))
    orch = AdvancedOrchestrator(percorso_config("config_timesheet.yaml"), factory, config_principale)
    orch.state.set_request_type("compilazione_timesheet")
    orch.state.set_global_variable("user_request", "richiesta finta")
    orch.state.set_global_variable("current_date", "2026-09-30")
    estrazione = {"nome_richiedente": "mario rossi", "progetto": "prin2024-02", "periodi": [
        {"data_inizio": "2026-09-01", "data_fine": "2026-09-05", "descrizione_attivita": "analisi"},
        {"data_inizio": "2026-09-08", "data_fine": "2026-09-12", "descrizione_attivita": "report"},
    ]}

    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, estrazione)), \
         patch.object(IterativeEnrichmentAgent, "_call_llm", side_effect=[(True, "Formale"), ERRORE_API]), \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA):
        risultato = orch.run_iterative_workflow()

    assert risultato["status"] == "failed"
    assert risultato["failed_agent"] == "iterative_enrichment_agent"
