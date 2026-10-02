# tests/test_travel_workflow.py
#
# Strato 2, test di percorso sul workflow missione.
# Particolarità: il workflow interroga l'utente. Il campo
# timesheet_richiesto non viene mai estratto dal testo, quindi la
# domanda arriva sempre, e la risposta decide tra due percorsi:
#   "no" -> solo il modulo missione
#   "si" -> modulo missione + voce di timesheet collegata

import logging
from unittest.mock import patch

import pytest

from agents_administrative_assistant import (
    DataExtractorAgent,
    SemanticEnrichmentAgent,
    get_agent_instance,
)
from orchestrator import AdvancedOrchestrator, create_composite_factory

# Estrazione completa tranne timesheet_richiesto (il prompt lo vuole null).
ESTRAZIONE_FINTA = {
    "nome_richiedente": "mario rossi",
    "progetto": "prin2024-02",
    "destinazione": "Napoli",
    "data_partenza": "2026-10-12",
    "data_ritorno": "2026-10-14",
    "motivo": "campagna sismica",
    "costo_stimato": 450.0,
    "mezzo_trasporto": "treno",
    "timesheet_richiesto": None,
}

ARRICCHIMENTI_FINTI = [(True, "Motivo formale"), (True, "Attività formale")]


@pytest.fixture
def esegui_missione(config_principale, percorso_config, monkeypatch):
    """Restituisce una funzione che esegue la missione con una risposta data."""
    def _esegui(risposta):
        domande = []

        def input_finto(domanda):
            domande.append(domanda)     # registra cosa è stato chiesto
            return risposta             # e risponde come l'utente

        monkeypatch.setattr("builtins.input", input_finto)

        factory = create_composite_factory(get_agent_instance, logging.getLogger("test"))
        orchestrator = AdvancedOrchestrator(
            config_path=percorso_config("config_travel.yaml"),
            agent_factory=factory,
            main_config=config_principale,
        )
        orchestrator.state.set_request_type("richiesta_missione")
        orchestrator.state.set_global_variable("user_request", "richiesta finta")
        orchestrator.state.set_global_variable("current_date", "2026-09-30")

        with patch.object(DataExtractorAgent, "_call_llm",
                          return_value=(True, dict(ESTRAZIONE_FINTA))), \
             patch.object(SemanticEnrichmentAgent, "_call_llm",
                          side_effect=ARRICCHIMENTI_FINTI) as arricchimento:
            risultato = orchestrator.run_iterative_workflow()

        return {"risultato": risultato, "domande": domande, "arricchimento": arricchimento}
    return _esegui


# --- L'interazione ---
def test_viene_posta_una_sola_domanda_quella_sul_timesheet(esegui_missione):
    domande = esegui_missione("no")["domande"]
    assert len(domande) == 1
    assert "timesheet" in domande[0]


# --- Percorso "no" ---
def test_con_no_esce_solo_il_modulo_missione(esegui_missione):
    risultato = esegui_missione("no")["risultato"]
    assert list(risultato) == ["missione"]


def test_il_modulo_missione_e_normalizzato_e_arricchito(esegui_missione):
    missione = esegui_missione("no")["risultato"]["missione"]
    assert missione["nome_richiedente"] == "Mario Rossi"
    assert missione["dettagli"]["progetto"] == "PRIN2024-02"
    assert missione["dettagli"]["motivo"] == "Motivo formale"


# --- Percorso "si" ---
def test_con_si_escono_missione_e_timesheet(esegui_missione):
    risultato = esegui_missione("si")["risultato"]
    assert [list(parte) for parte in risultato] == [["missione"], ["registrazione_timesheet"]]


def test_il_timesheet_eredita_le_date_della_missione(esegui_missione):
    timesheet = esegui_missione("si")["risultato"][1]["registrazione_timesheet"]
    assert timesheet["periodo"] == {"dal": "2026-10-12", "al": "2026-10-14"}


def test_il_timesheet_ha_la_sua_descrizione_arricchita(esegui_missione):
    esecuzione = esegui_missione("si")
    timesheet = esecuzione["risultato"][1]["registrazione_timesheet"]
    assert timesheet["dettaglio_attivita"] == "Attività formale"
    assert esecuzione["arricchimento"].call_count == 2


# --- Come risponde davvero un utente italiano ---
@pytest.mark.parametrize("risposta", ["si", "SI", "sì", "Sì", " sì "],
                         ids=["si", "SI", "si_accentato", "Si_accentato", "si_accentato_con_spazi"])
def test_ogni_forma_di_si_produce_il_timesheet(esegui_missione, risposta):
    risultato = esegui_missione(risposta)["risultato"]
    assert isinstance(risultato, list) and len(risultato) == 2
