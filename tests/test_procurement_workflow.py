# tests/test_procurement_workflow.py
#
# Test di percorso sul workflow acquisti (caso fortunato: l'estrazione
# trova tutti i campi, nessuna domanda all'utente).
# Le chiamate all'LLM sono sostituite da risposte fisse (mock).

import logging
from unittest.mock import patch

import pytest

from agents_administrative_assistant import (
    DataExtractorAgent,
    SemanticEnrichmentAgent,
    get_agent_instance,
)
from orchestrator import AdvancedOrchestrator, create_composite_factory


# --- PREPARA: la risposta che "fingiamo" arrivi dall'LLM di estrazione ---
# Volutamente sporca come la restituirebbe un modello reale:
# progetto minuscolo, nome non capitalizzato.
ESTRAZIONE_FINTA = {
    "descrizione_bene": "Workstation per elaborazione dati sismici",
    "costo_stimato": 1200.0,
    "motivazione": "Serve per il progetto",
    "progetto": "prin2024-02",
    "nome_richiedente": "mario rossi",
    "fornitore_suggerito": "Rossi Informatica srl",
    "cf_fornitore": "01234567890",
    "cig": "B123456789",
    "numero_impegno": "2026/0042",
    "data_impegno": "2026-09-15",
    "capitolo_spesa": "1.03.02",
    "obiettivo_funzione": "OF-01",
    "urgenza": None,
}


@pytest.fixture
def risultato_acquisti(config_principale, percorso_config):
    """Monta l'orchestratore come fa il runner e lo esegue con i mock."""
    factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
    orchestrator = AdvancedOrchestrator(
        config_path=percorso_config("config_procurement.yaml"),
        agent_factory=factory,
        main_config=config_principale,
    )
    orchestrator.state.set_request_type("richiesta_acquisto")
    orchestrator.state.set_global_variable("user_request", "richiesta finta")

    # --- ESEGUI: con i due agenti AI "scollegati" dall'LLM ---
    with patch.object(
        DataExtractorAgent, "_call_llm",
        return_value=(True, dict(ESTRAZIONE_FINTA)),
    ), patch.object(
        SemanticEnrichmentAgent, "_call_llm",
        return_value=(True, "Motivazione arricchita dal mock."),
    ):
        return orchestrator.run_iterative_workflow()


# --- VERIFICA: un test = una domanda ---

def test_produce_un_modulo_con_procedura_semplificata(risultato_acquisti):
    assert isinstance(risultato_acquisti, dict)
    assert risultato_acquisti["modalita_acquisto"] == "Ordine Diretto di Acquisto (OdA) su MEPA"


def test_il_progetto_viene_normalizzato_in_maiuscolo(risultato_acquisti):
    assert risultato_acquisti["progetto"] == "PRIN2024-02"


def test_il_cup_del_progetto_prin_viene_recuperato(risultato_acquisti):
    assert risultato_acquisti["cup"] == "J34E24001230001"


def test_la_dicitura_obbligatoria_compare_nel_modulo(risultato_acquisti):
    assert "dicitura_obbligatoria" in risultato_acquisti