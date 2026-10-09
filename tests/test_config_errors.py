# tests/test_config_errors.py
#
# Strato 1, contratto del core: un errore di chi scrive lo YAML ferma il
# workflow con un messaggio che nomina la regola. Questi casi, prima della
# 1.0.2, venivano registrati nel log e il workflow proseguiva: con un
# template sbagliato, per esempio, il modello riceveva un prompt vuoto.

import logging
from unittest.mock import patch

import pytest

from agents_administrative_assistant import DataExtractorAgent, get_agent_instance
from orchestrator import AdvancedOrchestrator, create_composite_factory


@pytest.fixture
def orchestratore(config_principale, percorso_config):
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), factory, config_principale)
    orch.state.set_request_type("richiesta_acquisto")
    orch.state.set_global_variable("user_request", "richiesta finta")
    return orch


def regola_estrattore(orch):
    return next(r for r in orch.router_rules if r["agent"] == "data_extractor_agent")


def esegui(orch):
    with patch.object(DataExtractorAgent, "_call_llm", return_value=(True, {})) as llm:
        orch.run_iterative_workflow()
    return llm


def test_un_template_inesistente_ferma_il_workflow_prima_del_modello(orchestratore):
    regola_estrattore(orchestratore)["task"]["template"] = "estrazione_dati_acquisto_tsk"
    with patch.object(DataExtractorAgent, "_call_llm") as llm:
        with pytest.raises(ValueError, match="estrazione_dati_acquisto_tsk"):
            orchestratore.run_iterative_workflow()
    assert not llm.called


def test_un_parametro_senza_path_ferma_il_workflow(orchestratore):
    regola_estrattore(orchestratore)["task"]["parameters"] = {"richiesta_utente": {"format": "json_string"}}
    with pytest.raises(ValueError, match="richiesta_utente"):
        esegui(orchestratore)


def test_un_if_che_non_e_una_lista_ferma_il_workflow(orchestratore):
    regola_estrattore(orchestratore)["update_state"] = [
        {"if": {"field": "output.x", "value": 1}, "then": []}]
    with pytest.raises(ValueError, match="expected a list"):
        esegui(orchestratore)


def test_un_azione_sconosciuta_in_update_state_ferma_il_workflow(orchestratore):
    regola_estrattore(orchestratore)["update_state"] = [
        {"asign": {"to": "state.current_phase", "value": "x"}}]
    with pytest.raises(ValueError, match="update_state"):
        esegui(orchestratore)


@pytest.mark.parametrize("chiave", ["activate_if", "agent"])
def test_una_regola_del_router_incompleta_ferma_il_workflow(orchestratore, chiave):
    del orchestratore.router_rules[-1][chiave]
    with pytest.raises(ValueError, match="router rule"):
        esegui(orchestratore)
