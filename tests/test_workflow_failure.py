# tests/test_workflow_failure.py
#
# Test di percorso sul caso di errore: un agente AI fallisce.
# Il risultato deve essere riconoscibile come fallimento, e il runner
# non deve salvarlo come se fosse un modulo compilato.

import logging
import os
import pytest
from unittest.mock import patch

from agents_administrative_assistant import DataExtractorAgent, DataNormalizerAgent, get_agent_instance
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




# --- Fallimenti non segnalati dall'agente ---
# Un agente può fallire senza restituire False: sollevando un'eccezione.
# Oppure il workflow può fermarsi senza che nessun agente fallisca:
# nessuna regola si attiva, o finiscono i cicli. In tutti questi casi
# il risultato deve restare un fallimento riconoscibile.


def _orchestratore_acquisti(config_principale, percorso_config):
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orchestrator = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), factory, config_principale)
    orchestrator.state.set_request_type("richiesta_acquisto")
    orchestrator.state.set_global_variable("user_request", "richiesta finta")
    return orchestrator


def test_eccezione_di_un_agente_diventa_fallimento(config_principale, percorso_config):
    orchestrator = _orchestratore_acquisti(config_principale, percorso_config)

    # L'estrattore funziona, il normalizzatore esplode al passo successivo.
    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, {"descrizione_bene": "pc"})), \
         patch.object(DataNormalizerAgent, "run", side_effect=TypeError("valore inatteso")), \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA) as debugger:
        risultato = orchestrator.run_iterative_workflow()

    assert risultato["status"] == "failed"
    assert risultato["reason"] == "agent_exception"
    assert risultato["failed_agent"] == "data_normalizer_agent"
    assert "TypeError: valore inatteso" in risultato["error"]
    # Il percorso è lo stesso del fallimento segnalato: il debugger viene chiamato.
    assert debugger.called


def test_il_fallimento_segnalato_dichiara_il_motivo(config_principale, percorso_config):
    orchestrator = _orchestratore_acquisti(config_principale, percorso_config)

    with patch.object(DataExtractorAgent, "_call_llm", return_value=ERRORE_FINTO), \
         patch.object(DebuggerAgent, "_call_llm", return_value=DIAGNOSI_FINTA):
        risultato = orchestrator.run_iterative_workflow()

    assert risultato["reason"] == "agent_reported_failure"
    assert risultato["error"] == "Errore simulato dal test"


def test_nessun_agente_attivato_e_un_fallimento(config_principale, percorso_config, caplog):
    orchestrator = _orchestratore_acquisti(config_principale, percorso_config)
    # Una fase che nessuna regola del router riconosce: il workflow è bloccato.
    orchestrator.state.set_phase("fase_inesistente")
    caplog.set_level(5)  # JSON_DEBUG

    with patch.object(DebuggerAgent, "_call_llm") as debugger:
        risultato = orchestrator.run_iterative_workflow()

    assert risultato["status"] == "failed"
    assert risultato["reason"] == "no_agent_activated"
    assert risultato["failed_agent"] is None
    assert risultato["phase"] == "fase_inesistente"
    # La causa è nota dalle regole: nessun modello viene interpellato.
    assert not debugger.called
    # La terminazione lascia un evento strutturato nel log.
    eventi = [r for r in caplog.records if getattr(r, "event_type", None) == "WORKFLOW_FAILED"]
    assert len(eventi) == 1


def test_cicli_esauriti_e_un_fallimento(config_principale, percorso_config):
    orchestrator = _orchestratore_acquisti(config_principale, percorso_config)
    orchestrator.settings["max_cycles"] = 1

    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, {"descrizione_bene": "pc"})):
        risultato = orchestrator.run_iterative_workflow()

    assert risultato["status"] == "failed"
    assert risultato["reason"] == "max_cycles_exhausted"
    assert risultato["phase"] == "data_normalization"


def test_errore_di_configurazione_resta_rumoroso(config_principale, percorso_config):
    # Solo la chiamata all'agente è protetta. Un errore nello YAML
    # (qui: un assign senza destinazione) deve interrompere l'esecuzione,
    # non diventare un fallimento con diagnosi.
    orchestrator = _orchestratore_acquisti(config_principale, percorso_config)
    regola = next(r for r in orchestrator.router_rules if r["agent"] == "data_extractor_agent")
    regola["update_state"] = [{"assign": {"from": "output"}}]

    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, {})):
        with pytest.raises(ValueError, match="missing key 'to'"):
            orchestrator.run_iterative_workflow()


_init_originale = AdvancedOrchestrator.__init__


def _init_con_cicli(n):
    # Costruisce l'orchestratore normalmente, poi riduce il limite di cicli:
    # il runner crea l'orchestratore da sé, quindi non lo si può impostare prima.
    def _init(self, *args, **kwargs):
        _init_originale(self, *args, **kwargs)
        self.settings["max_cycles"] = n
    return _init


def test_il_runner_non_salva_lo_stallo_come_modulo(tmp_path, monkeypatch, config_principale, percorso_config):
    # Prima della correzione, uno stallo veniva salvato con l'etichetta
    # "output", come un risultato riuscito.
    monkeypatch.chdir(tmp_path)

    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, {"descrizione_bene": "pc"})), \
         patch.object(AdvancedOrchestrator, "__init__", _init_con_cicli(1)):
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


def test_il_runner_sopravvive_a_un_eccezione(tmp_path, monkeypatch, config_principale, percorso_config):
    # Prima della correzione, l'eccezione usciva dal runner e chiudeva
    # l'intero assistente.
    monkeypatch.chdir(tmp_path)

    with patch.object(DataExtractorAgent, "run", side_effect=RuntimeError("guasto")), \
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