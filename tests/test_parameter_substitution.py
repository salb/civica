# tests/test_parameter_substitution.py
#
# Strato 1, contratto del core: la sostituzione dei parametri nei
# template dei prompt è atomica. Il valore di un parametro viene
# inserito come testo opaco e non viene mai rielaborato.

import pytest

from orchestrator import AdvancedOrchestrator


@pytest.fixture
def orchestratore(percorso_config):
    """Un orchestratore con un solo template di prova: {A} poi {B}."""
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), agent_factory=None)
    orch.state.set_configuration({"prompt_templates": {"prova": "Primo: {A} | Secondo: {B}"}})
    return orch


def componi_prompt(orchestratore, valore_a, valore_b):
    """Mette due valori nello stato e compone il template 'prova'."""
    orchestratore.state.set_global_variable("valore_a", valore_a)
    orchestratore.state.set_global_variable("valore_b", valore_b)
    return orchestratore._resolve_task_input({
        "template": "prova",
        "parameters": {"A": "state.valore_a", "B": "state.valore_b"},
    })


def test_i_parametri_vengono_sostituiti(orchestratore):
    # Caso di base: senza trappole, la sostituzione fa il suo lavoro.
    assert componi_prompt(orchestratore, "uno", "due") == "Primo: uno | Secondo: due"


# La trappola in entrambe le direzioni: il testo inserito (scritto
# dall'utente o prodotto dall'LLM) contiene per caso il nome
# dell'ALTRO parametro. Il testo deve arrivare nel prompt così com'è.
@pytest.mark.parametrize("valore_a, valore_b, atteso", [
    ("ho scritto {B}", "SEGRETO", "Primo: ho scritto {B} | Secondo: SEGRETO"),
    ("SEGRETO", "ho scritto {A}", "Primo: SEGRETO | Secondo: ho scritto {A}"),
])
def test_il_valore_inserito_non_viene_rielaborato(orchestratore, valore_a, valore_b, atteso):
    assert componi_prompt(orchestratore, valore_a, valore_b) == atteso


def test_json_string_nei_parametri_conserva_la_lista_vuota(orchestratore):
    # Stessa regola dei context_preparators, sul secondo punto in cui il core
    # converte in JSON: i parametri dei prompt con format: json_string.
    orchestratore.state.set_global_variable("valore_a", [])
    orchestratore.state.set_global_variable("valore_b", "due")
    prompt = orchestratore._resolve_task_input({
        "template": "prova",
        "parameters": {"A": {"path": "state.valore_a", "format": "json_string"},
                       "B": "state.valore_b"},
    })
    assert prompt == "Primo: [] | Secondo: due"
