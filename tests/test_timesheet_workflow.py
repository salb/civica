# tests/test_timesheet_workflow.py
#
# Strato 2, test di percorso sul workflow timesheet (caso fortunato:
# l'estrazione trova tutto, nessuna domanda all'utente).
# Particolarità: più periodi nella stessa richiesta, quindi logica
# iterativa (un arricchimento e una voce compilata per ogni periodo).

import logging
from unittest.mock import patch

import pytest

from agents_administrative_assistant import (
    DataExtractorAgent,
    IterativeEnrichmentAgent,
    get_agent_instance,
)
from orchestrator import AdvancedOrchestrator, create_composite_factory

# Il runner inietta date.today(); il test la fissa per essere riproducibile.
DATA_ODIERNA = "2026-09-30"

# Risposta finta dell'estrattore, volutamente sporca: minuscole ovunque.
ESTRAZIONE_FINTA = {
    "nome_richiedente": "mario rossi",
    "progetto": "prin2024-02",
    "periodi": [
        {"data_inizio": "2026-09-01", "data_fine": "2026-09-05",
         "descrizione_attivita": "analisi dati"},
        {"data_inizio": "2026-09-08", "data_fine": "2026-09-12",
         "descrizione_attivita": "scrittura report"},
    ],
}

# Una risposta finta per ogni chiamata di arricchimento, nell'ordine.
ARRICCHIMENTI_FINTI = [(True, "Formale uno"), (True, "Formale due")]


@pytest.fixture
def esecuzione(config_principale, percorso_config):
    """Esegue il workflow e restituisce il risultato insieme ai due mock."""
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orchestrator = AdvancedOrchestrator(
        config_path=percorso_config("config_timesheet.yaml"),
        agent_factory=factory,
        main_config=config_principale,
    )
    orchestrator.state.set_request_type("compilazione_timesheet")
    orchestrator.state.set_global_variable("user_request", "richiesta finta")
    orchestrator.state.set_global_variable("current_date", DATA_ODIERNA)

    with patch.object(DataExtractorAgent, "_call_llm",
                      return_value=(True, ESTRAZIONE_FINTA)) as estrattore, \
         patch.object(IterativeEnrichmentAgent, "_call_llm",
                      side_effect=ARRICCHIMENTI_FINTI) as arricchimento:
        risultato = orchestrator.run_iterative_workflow()

    return {"risultato": risultato, "estrattore": estrattore, "arricchimento": arricchimento}


def test_una_voce_per_ogni_periodo(esecuzione):
    assert len(esecuzione["risultato"]) == 2


def test_i_campi_comuni_compaiono_normalizzati_in_ogni_voce(esecuzione):
    for voce in esecuzione["risultato"]:
        assert voce["richiedente"] == "Mario Rossi"
        assert voce["progetto_timesheet"] == "PRIN2024-02"


def test_ogni_voce_ha_le_date_del_suo_periodo(esecuzione):
    periodi = [(v["periodo_dal"], v["periodo_al"]) for v in esecuzione["risultato"]]
    assert periodi == [("2026-09-01", "2026-09-05"), ("2026-09-08", "2026-09-12")]


def test_le_descrizioni_sono_arricchite_nell_ordine_giusto(esecuzione):
    attivita = [v["attivita_svolta"] for v in esecuzione["risultato"]]
    assert attivita == ["Formale uno", "Formale due"]


def test_una_chiamata_all_llm_per_ogni_periodo(esecuzione):
    assert esecuzione["arricchimento"].call_count == 2


def test_il_prompt_di_estrazione_contiene_la_data_odierna(esecuzione):
    # Senza la data di oggi l'LLM non può risolvere "la settimana scorsa"
    # né decidere l'anno di "dal 1 al 5 settembre".
    prompt = esecuzione["estrattore"].call_args.kwargs["system_prompt"]
    assert DATA_ODIERNA in prompt
