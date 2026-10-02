# tests/test_assign_destinations.py
#
# Strato 1, contratto del core: dove finisce un valore quando lo YAML
# scrive  assign: {to: ..., value/from: ...}.
# Si passa dallo stesso ingresso usato dal router YAML: una lista di azioni.

import logging

import pytest

from orchestrator import AdvancedOrchestrator


@pytest.fixture
def orchestratore(percorso_config):
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), agent_factory=None)
    orch.state.update_collected_data({"esistente": "da conservare"})
    return orch


def assegna(orchestratore, regola, output_agente=None):
    """Esegue una sola azione assign, come se arrivasse dallo YAML."""
    orchestratore._execute_state_updates([{"assign": regola}], output_agente)
    return orchestratore.state.as_dict()


# --- Destinazioni in cima allo stato: tipizzate e dinamiche ---
@pytest.mark.parametrize("destinazione, chiave", [
    ("state.current_phase", "current_phase"),
    ("state.request_type", "request_type"),
    ("state.final_output", "final_output"),
    ("state.pending_questions", "pending_questions"),
    ("state.temp_input", "temp_input"),   # chiave dinamica
])
def test_il_valore_arriva_nella_chiave_giusta(orchestratore, destinazione, chiave):
    stato = assegna(orchestratore, {"to": destinazione, "value": "X"})
    assert stato[chiave] == "X"


# --- Destinazioni dentro collected_data ---
def test_un_campo_di_collected_data_viene_scritto_senza_toccare_gli_altri(orchestratore):
    stato = assegna(orchestratore, {"to": "state.collected_data.cup", "value": "J34"})
    assert stato["collected_data"]["cup"] == "J34"
    assert stato["collected_data"]["esistente"] == "da conservare"


def test_un_dizionario_su_collected_data_viene_fuso_non_sostituito(orchestratore):
    stato = assegna(orchestratore, {"to": "state.collected_data", "value": {"nuovo": 1}})
    assert stato["collected_data"] == {"esistente": "da conservare", "nuovo": 1}


# --- Origine del valore ---
def test_from_prende_il_valore_dall_output_dell_agente(orchestratore):
    stato = assegna(
        orchestratore,
        {"to": "state.collected_data.progetto", "from": "output.progetto"},
        output_agente={"progetto": "PRIN2024-02"},
    )
    assert stato["collected_data"]["progetto"] == "PRIN2024-02"


# --- Casi di errore ---
def test_una_chiave_di_configurazione_non_si_puo_assegnare(orchestratore):
    # La guardia di WorkflowState vale anche quando la scrittura arriva dallo YAML.
    with pytest.raises(ValueError, match="prompt_templates"):
        assegna(orchestratore, {"to": "state.prompt_templates", "value": {}})


# Regole malformate: sono errori di chi scrive lo YAML.
# Il workflow si ferma con un messaggio che nomina la regola.
@pytest.mark.parametrize("regola", [
    {"to": "stat.current_phase", "value": "X"},             # refuso nel prefisso
    {"to": "state.collected_data.a.b", "value": "X"},       # troppo profondo
    {"value": "X"},                                          # manca 'to'
    {"to": "state.current_phase"},                           # manca value/from
], ids=["refuso_nel_prefisso", "troppo_profondo", "manca_to", "manca_value_from"])
def test_una_regola_malformata_ferma_il_workflow(orchestratore, regola):
    with pytest.raises(ValueError, match="assign"):
        assegna(orchestratore, regola)


# Caratterizzazione: la regola è corretta, è il DATO che non va
# (per esempio un agente che restituisce testo invece di un dizionario).
# Comportamento attuale: errore nel log, stato invariato, si prosegue.
def test_un_dato_non_dizionario_su_collected_data_viene_registrato_e_ignorato(orchestratore, caplog):
    dati_prima = dict(orchestratore.state.get_collected_data())

    with caplog.at_level(logging.ERROR):
        assegna(orchestratore, {"to": "state.collected_data", "value": "non un dizionario"})

    assert orchestratore.state.get_collected_data() == dati_prima
    assert any(r.levelno == logging.ERROR for r in caplog.records)
