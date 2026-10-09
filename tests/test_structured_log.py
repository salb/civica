# tests/test_structured_log.py
#
# Il log strutturato con la configurazione di default, come la usano i
# runner: setup_logging() e nient'altro. Ogni esecuzione di un agente deve
# lasciare un evento nel file degli eventi e, nel file di traccia, lo stato
# prima e DOPO le regole di aggiornamento: è il dato che permette di
# confrontare una run con le regole dichiarate nello YAML.

import glob
import json
import logging
from unittest.mock import patch

import pytest

import logger_config
from agents_administrative_assistant import (
    DataExtractorAgent,
    SemanticEnrichmentAgent,
    get_agent_instance,
)
from orchestrator import AdvancedOrchestrator, create_composite_factory

ESTRAZIONE_FINTA = {
    "descrizione_bene": "Workstation", "costo_stimato": 1200.0,
    "motivazione": "Serve", "progetto": "prin2024-02",
    "nome_richiedente": "mario rossi", "fornitore_suggerito": "Rossi srl",
    "cf_fornitore": "01234567890", "cig": "B123", "numero_impegno": "2026/42",
    "data_impegno": "2026-09-15", "capitolo_spesa": "1.03", "obiettivo_funzione": "OF-01",
    "urgenza": None,
}


@pytest.fixture
def log_di_default(tmp_path, monkeypatch):
    """Configura il logging come i runner, dentro tmp_path; poi lo ripristina."""
    monkeypatch.chdir(tmp_path)
    radice = logging.getLogger()
    handler_prima, livello_prima = radice.handlers[:], radice.level

    def _configura():
        logger_config.setup_logging()

    yield _configura

    for h in radice.handlers[:]:
        radice.removeHandler(h)
        h.close()
    for h in handler_prima:
        radice.addHandler(h)
    radice.setLevel(livello_prima)


def esegui_acquisto(config_principale, percorso_config, fase_iniziale=None):
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), factory, config_principale)
    orch.state.set_request_type("richiesta_acquisto")
    orch.state.set_global_variable("user_request", "richiesta finta")
    if fase_iniziale:
        orch.state.set_phase(fase_iniziale)
    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, dict(ESTRAZIONE_FINTA))), \
         patch.object(SemanticEnrichmentAgent, "_call_llm", return_value=(True, "Motivazione formale.")):
        return orch.run_iterative_workflow()


def righe(suffisso):
    """Le righe JSON del file di log con quel suffisso (uno solo per run)."""
    file = glob.glob(f"logs/*_{suffisso}.jsonl")
    assert len(file) == 1, file
    with open(file[0], encoding="utf-8") as f:
        return [json.loads(r) for r in f if r.strip()]


def test_il_file_eventi_ha_un_evento_per_ogni_agente(log_di_default, config_principale, percorso_config):
    log_di_default()
    esegui_acquisto(config_principale, percorso_config)
    eventi = [e for e in righe("events") if e.get("event_type") == "AGENT_OUTPUT"]
    assert [e["agent"] for e in eventi] == [
        "data_extractor_agent", "data_normalizer_agent", "formal_validator_agent",
        "procurement_decision_agent", "budget_validator_agent",
        "semantic_enrichment_agent", "compiler_agent",
    ]
    assert all(e["success"] is True and "duration_ms" in e for e in eventi)


def test_il_file_eventi_contiene_solo_eventi_strutturati(log_di_default, config_principale, percorso_config):
    log_di_default()
    esegui_acquisto(config_principale, percorso_config)
    assert all("event_type" in e for e in righe("events"))


def test_la_traccia_registra_lo_stato_dopo_le_regole(log_di_default, config_principale, percorso_config):
    # Prima della 1.0.2 lo stato "dopo" era fotografato prima di update_state:
    # coincideva con lo stato "prima".
    log_di_default()
    esegui_acquisto(config_principale, percorso_config)
    eventi = [e for e in righe("trace") if e.get("event_type") == "AGENT_OUTPUT"]
    estrattore = eventi[0]
    assert estrattore["state_before"]["current_phase"] == "data_extraction"
    assert estrattore["state_after"]["current_phase"] == "data_normalization"
    assert estrattore["state_after"]["collected_data"]["cig"] == "B123"
    # Ogni transizione cambia la fase, come dichiarato nel router.
    assert all(e["state_before"]["current_phase"] != e["state_after"]["current_phase"]
               for e in eventi)


def test_una_terminazione_lascia_un_evento_con_il_motivo(log_di_default, config_principale, percorso_config):
    log_di_default()
    esegui_acquisto(config_principale, percorso_config, fase_iniziale="fase_inesistente")
    fallimenti = [e for e in righe("events") if e.get("event_type") == "WORKFLOW_FAILED"]
    assert len(fallimenti) == 1
    assert fallimenti[0]["reason"] == "no_agent_activated"


@pytest.mark.parametrize("valore", ["0", "false", "OFF", "no"])
def test_la_traccia_si_disattiva_con_la_variabile_d_ambiente(
        log_di_default, monkeypatch, config_principale, percorso_config, valore):
    monkeypatch.setenv("CIVICA_TRACE_LOG", valore)
    log_di_default()
    esegui_acquisto(config_principale, percorso_config)
    assert glob.glob("logs/*_trace.jsonl") == []
    assert any(e.get("event_type") == "AGENT_OUTPUT" for e in righe("events"))
