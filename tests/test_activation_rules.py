# tests/test_activation_rules.py
#
# Strato 1, contratto del core: come vengono valutate le condizioni
# activate_if (quale agente parte) e if (quale ramo di update_state).
# Una lista di condizioni è vera solo se sono vere TUTTE.

import pytest

from orchestrator import AdvancedOrchestrator


@pytest.fixture
def orchestratore(percorso_config):
    """Uno stato con valori noti, uno per ogni situazione da provare."""
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), agent_factory=None)
    orch.state.set_global_variable("valore", "a")
    orch.state.set_global_variable("vuoto", "")
    orch.state.set_global_variable("zero", 0)
    orch.state.set_global_variable("falso", False)
    orch.state.set_global_variable("spazi", "   ")
    orch.state.set_global_variable("lista_vuota", [])
    orch.state.set_global_variable("dizionario_vuoto", {})
    return orch


def valuta(orchestratore, regole, output_agente=None):
    return orchestratore._evaluate_activation_rules(regole, output_agente)


# --- Ogni operatore, una volta vero e una volta falso ---
@pytest.mark.parametrize("regola, atteso", [
    ({"field": "state.valore", "value": "a"}, True),                              # equals implicito
    ({"field": "state.valore", "value": "b"}, False),
    ({"field": "state.valore", "operator": "equals", "value": "a"}, True),
    ({"field": "state.valore", "operator": "not_equals", "value": "b"}, True),
    ({"field": "state.valore", "operator": "not_equals", "value": "a"}, False),
    ({"field": "state.valore", "operator": "in", "value": ["a", "b"]}, True),
    ({"field": "state.valore", "operator": "in", "value": ["x", "y"]}, False),
    ({"field": "state.valore", "operator": "exists"}, True),
    ({"field": "state.zero", "operator": "exists"}, True),                        # 0 è un valore
    ({"field": "state.vuoto", "operator": "exists"}, False),
    ({"field": "state.assente", "operator": "exists"}, False),
], ids=[
    "equals_implicito_vero", "equals_implicito_falso", "equals_esplicito",
    "not_equals_vero", "not_equals_falso", "in_vero", "in_falso",
    "exists_valore", "exists_zero", "exists_stringa_vuota", "exists_campo_assente",
])
def test_operatore(orchestratore, regola, atteso):
    assert valuta(orchestratore, [regola]) is atteso


def test_la_condizione_puo_leggere_l_output_dell_agente(orchestratore):
    # Il caso reale degli YAML: if output.success == False
    regola = {"field": "output.success", "operator": "equals", "value": False}
    assert valuta(orchestratore, [regola], output_agente={"success": False}) is True


# --- Più condizioni: AND ---
def test_tutte_vere_da_vero(orchestratore):
    regole = [{"field": "state.valore", "value": "a"},
              {"field": "state.zero", "operator": "exists"}]
    assert valuta(orchestratore, regole) is True


def test_basta_una_falsa_per_dare_falso(orchestratore):
    regole = [{"field": "state.valore", "value": "a"},
              {"field": "state.vuoto", "operator": "exists"}]
    assert valuta(orchestratore, regole) is False


# --- Regole malformate: errori di chi scrive lo YAML ---
@pytest.mark.parametrize("regola", [
    {"field": "state.valore", "operator": "equal", "value": "b"},     # refuso nell'operatore
    {"field": "state.valore", "operator": "exist"},                   # refuso nell'operatore
    {"operator": "equals", "value": "a"},                             # manca 'field'
], ids=["refuso_equal", "refuso_exist", "manca_field"])
def test_una_condizione_malformata_ferma_il_workflow(orchestratore, regola):
    with pytest.raises(ValueError, match="activate_if"):
        valuta(orchestratore, [regola])


# --- exists usa la stessa nozione di "mancante" del validatore formale ---
@pytest.mark.parametrize("campo, atteso", [
    ("state.falso", True),              # False è un valore, come 0
    ("state.spazi", False),             # solo spazi: mancante
    ("state.lista_vuota", False),       # contenitore vuoto: mancante
    ("state.dizionario_vuoto", False),  # contenitore vuoto: mancante
], ids=["falso", "solo_spazi", "lista_vuota", "dizionario_vuoto"])
def test_exists_coerente_con_il_validatore(orchestratore, campo, atteso):
    regola = {"field": campo, "operator": "exists"}
    assert valuta(orchestratore, [regola]) is atteso