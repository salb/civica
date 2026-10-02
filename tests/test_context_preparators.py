# tests/test_context_preparators.py
#
# Strato 1, contratto del core: i context_preparators preparano lo stato
# all'inizio di ogni ciclo, prima che si decida quale agente parte.
# Ogni regola copia un valore da un punto a un altro dello stato,
# eventualmente trasformandolo (format: json_string).

import json

import pytest

from orchestrator import AdvancedOrchestrator

SCHEMA = {"destinazione": {"descrizione": "Città in cui si svolgerà la missione"}}


@pytest.fixture
def orchestratore(percorso_config):
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), agent_factory=None)
    orch.state.set_global_variable("schema", SCHEMA)
    return orch


def prepara(orchestratore, *regole):
    """Installa le regole come se venissero dallo YAML e le esegue."""
    orchestratore.config["context_preparators"] = list(regole)
    orchestratore._run_context_preparators()
    return orchestratore.state.as_dict()


# --- Il contratto ---
def test_il_valore_viene_copiato_senza_trasformazioni(orchestratore):
    stato = prepara(orchestratore, {"assign": {"from": "state.schema", "to": "state.copia"}})
    assert stato["copia"] == SCHEMA


def test_json_string_produce_un_testo_json_equivalente(orchestratore):
    stato = prepara(orchestratore, {"assign": {
        "from": "state.schema", "to": "state.testo", "format": "json_string"}})
    assert isinstance(stato["testo"], str)
    assert json.loads(stato["testo"]) == SCHEMA


def test_json_string_conserva_le_lettere_accentate(orchestratore):
    # Il testo finisce in un prompt: l'LLM deve leggere "Città", non "Citt\u00e0".
    stato = prepara(orchestratore, {"assign": {
        "from": "state.schema", "to": "state.testo", "format": "json_string"}})
    assert "Città" in stato["testo"]


def test_json_string_su_un_valore_assente_produce_un_oggetto_vuoto(orchestratore):
    stato = prepara(orchestratore, {"assign": {
        "from": "state.assente", "to": "state.testo", "format": "json_string"}})
    assert stato["testo"] == "{}"


def test_la_scrittura_passa_dalla_guardia_delle_chiavi_riservate(orchestratore):
    with pytest.raises(ValueError, match="prompt_templates"):
        prepara(orchestratore, {"assign": {"from": "state.schema", "to": "state.prompt_templates"}})


# --- L'unico uso reale: il workflow missione ---
def test_lo_schema_della_missione_arriva_al_prompt_con_gli_accenti(percorso_config):
    orch = AdvancedOrchestrator(percorso_config("config_travel.yaml"), agent_factory=None)
    orch._run_context_preparators()
    testo = orch.state.as_dict()["schema_per_estrazione_str"]
    assert "\\u00e8" not in testo      # nessuna "è" trasformata in codice
    assert "è" in testo


# --- Regole malformate ---
@pytest.mark.parametrize("regola", [
    {"asign": {"from": "state.schema", "to": "state.copia"}},                        # refuso
    {"assign": {"to": "state.copia"}},                                                # manca from
    {"assign": {"from": "state.schema"}},                                             # manca to
    {"assign": {"from": "state.schema", "to": "state.copia", "format": "json"}},      # formato ignoto
], ids=["refuso_assign", "manca_from", "manca_to", "formato_sconosciuto"])
def test_una_regola_malformata_ferma_il_workflow(orchestratore, regola):
    with pytest.raises(ValueError, match="context_preparators"):
        prepara(orchestratore, regola)

# Solo un valore assente diventa "{}": un valore vuoto o falso resta sé stesso.
@pytest.mark.parametrize("valore, atteso", [
    ([], "[]"),   # lista vuota: resta una lista
    ({}, "{}"),   # dizionario vuoto: guardia, già corretto
    (0, "0"),     # zero: è un valore
], ids=["lista_vuota", "dizionario_vuoto", "zero"])
def test_json_string_su_un_valore_vuoto_ne_conserva_il_tipo(orchestratore, valore, atteso):
    orchestratore.state.set_global_variable("vuoto", valore)
    stato = prepara(orchestratore, {"assign": {
        "from": "state.vuoto", "to": "state.testo", "format": "json_string"}})
    assert stato["testo"] == atteso

