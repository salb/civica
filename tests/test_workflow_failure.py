# tests/test_workflow_failure.py
#
# Test di percorso sul caso di errore: un agente AI fallisce.
# Il risultato deve essere riconoscibile come fallimento, e il runner
# non deve salvarlo come se fosse un modulo compilato.

import logging
import os
from unittest.mock import patch

from agents_administrative_assistant import DataExtractorAgent, get_agent_instance
from core_framework import DebuggerAgent
from orchestrator import AdvancedOrchestrator, create_composite_factory
from run_administrative_assistant import run_admin_workflow

# --- PREPARA: le due risposte finte ---
# L'estrattore fallisce apposta, come farebbe con un errore di rete o di API.
ERRORE_FINTO = (False, {"failure_reason": "Errore simulato dal test"})
# Il debugger, che a sua volta chiamerebbe l'LLM, risponde con una diagnosi fissa.
DIAGNOSI_FINTA = (True, {
    "analisi_causa_radice": "Errore simulato",
    "suggerimento_correzione": "Nessuno, è un test",
    "impatto_fallimento": "BASSO",
})


def test_il_fallimento_e_riconoscibile_nel_risultato(config_principale, percorso_config):
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orchestrator = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), factory, config_principale)
    orchestrator.state.set_request_type("richiesta_acquisto")
    orchestrator.state.set_global_variable("user_request", "richiesta finta")

    # ESEGUI
    with patch.object(DataExtractorAgent, "_call_llm", return_value=ERRORE_FINTO), \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA):
        risultato = orchestrator.run_iterative_workflow()

    # VERIFICA
    assert risultato["status"] == "failed"
    assert risultato["failed_agent"] == "data_extractor_agent"
    assert risultato["diagnosis"]["impatto_fallimento"] == "BASSO"


def test_il_runner_non_salva_il_fallimento_come_modulo(tmp_path, monkeypatch, config_principale, percorso_config):
    # tmp_path: cartella temporanea creata da pytest, cancellata a fine test.
    # monkeypatch.chdir: il runner scrive in "output/" relativo alla
    # cartella corrente, quindi lo facciamo lavorare dentro tmp_path.
    monkeypatch.chdir(tmp_path)

    with patch.object(DataExtractorAgent, "_call_llm", return_value=ERRORE_FINTO), \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA):
        run_admin_workflow(
            workflow_type="richiesta_acquisto",
            config_path=percorso_config("config_procurement.yaml"),
            initial_data={"run_id": "test", "user_request": "richiesta finta",
                          "request_type": "richiesta_acquisto"},
            main_config=config_principale,
        )

    file_salvati = os.listdir(tmp_path / "output")
    assert len(file_salvati) == 1
    assert "FAILED" in file_salvati[0]
    assert "_output_" not in file_salvati[0]