# tests/test_config_merge.py
#
# Strato 1, contratto del core: come si combinano il config globale
# (quello del runner) e il config del singolo workflow.
# Regola dichiarata: i dizionari si fondono chiave per chiave, UN solo
# livello; tutto il resto (liste, scalari) viene sostituito dal workflow.

import copy

import pytest
import yaml

from orchestrator import AdvancedOrchestrator

GLOBALE = {
    "prompt_templates": {"triage": "testo globale", "comune": "versione globale"},
    "ai_models": {"normal": {"model": "modello-g", "temperature": 0.2}},
    "settings": {"max_cycles": 10},
    "lista": ["g1", "g2"],
}

WORKFLOW = {
    "prompt_templates": {"estrazione": "testo workflow", "comune": "versione workflow"},
    "ai_models": {"normal": {"temperature": 0.7}},
    "lista": ["w1"],
    "router": [],
}


@pytest.fixture
def scrivi_yaml(tmp_path):
    """Scrive un dizionario come file YAML temporaneo e ne restituisce il percorso."""
    def _scrivi(contenuto, nome="workflow.yaml"):
        percorso = tmp_path / nome
        percorso.write_text(yaml.safe_dump(contenuto, allow_unicode=True), encoding="utf-8")
        return str(percorso)
    return _scrivi


@pytest.fixture
def config(scrivi_yaml):
    """Il config risultante dalla fusione di GLOBALE e WORKFLOW."""
    orch = AdvancedOrchestrator(scrivi_yaml(WORKFLOW), agent_factory=None,
                                main_config=copy.deepcopy(GLOBALE))
    return orch.config


# --- La regola di fusione ---
def test_una_chiave_solo_globale_resta_disponibile(config):
    assert config["settings"] == {"max_cycles": 10}


def test_una_chiave_solo_del_workflow_viene_aggiunta(config):
    assert config["router"] == []


def test_i_dizionari_si_fondono_chiave_per_chiave(config):
    assert config["prompt_templates"]["triage"] == "testo globale"
    assert config["prompt_templates"]["estrazione"] == "testo workflow"


def test_a_parita_di_chiave_vince_il_workflow(config):
    assert config["prompt_templates"]["comune"] == "versione workflow"


def test_liste_e_scalari_vengono_sostituiti_non_uniti(config):
    assert config["lista"] == ["w1"]


def test_la_fusione_e_a_un_solo_livello(config):
    # Il workflow ridefinisce ai_models.normal: la voce viene sostituita
    # per intero, "model" del globale NON sopravvive.
    assert config["ai_models"]["normal"] == {"temperature": 0.7}


def test_senza_config_globale_vale_solo_il_workflow(scrivi_yaml):
    orch = AdvancedOrchestrator(scrivi_yaml(WORKFLOW), agent_factory=None)
    assert "triage" not in orch.config["prompt_templates"]


# --- Isolamento tra esecuzioni ---
def test_il_config_globale_non_viene_modificato(scrivi_yaml):
    globale = copy.deepcopy(GLOBALE)
    AdvancedOrchestrator(scrivi_yaml(WORKFLOW), agent_factory=None, main_config=globale)
    assert globale == GLOBALE


def test_due_workflow_di_fila_non_si_contaminano(percorso_config):
    # Il caso reale: il runner riusa lo stesso main_config per ogni richiesta.
    with open(percorso_config("config_administrative_assistant.yaml"), encoding="utf-8") as f:
        globale = yaml.safe_load(f)

    acquisti = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), None, globale)
    missione = AdvancedOrchestrator(percorso_config("config_travel.yaml"), None, globale)

    solo_acquisti = set(acquisti.config["prompt_templates"]) - set(globale["prompt_templates"])
    assert solo_acquisti                                                   # la domanda ha senso
    assert not solo_acquisti & set(missione.config["prompt_templates"])    # e la risposta è no
