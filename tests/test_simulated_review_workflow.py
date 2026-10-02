# tests/test_simulated_review_workflow.py
#
# Strato 2, test di percorso sul workflow "review simulata":
# un revisore critico e uno propositivo leggono il draft, poi un editor
# sintetizza le due review in un report che viene scritto su file.
# Tre chiamate all'LLM in sequenza, ognuna con il draft in coda al prompt.

import pytest
from unittest.mock import patch

from agents_research_assistant import (
    ConstructiveReviewerAgent,
    CriticalReviewerAgent,
    EditorAgent,
)
from run_research_assistant import run_research_workflow

TESTO_DRAFT = "Il nostro manoscritto sulla sismicità dei Campi Flegrei."

REVIEW_CRITICA = {
    "commenti_critici": [{"area": "Metodologia", "critica": "Rete troppo rada."}],
    "valutazione_complessiva": "Lavoro solido ma metodologia da rafforzare.",
}
REVIEW_PROPOSITIVA = {
    "commenti_propositivi": [{"punto_di_forza": "Dataset originale."}],
    "potenziale_impatto": "Alto per la comunità vulcanologica.",
    "raccomandazioni_strategiche": ["Confrontare con il 2012-2014."],
}
REPORT_EDITORIALE = "# Decisione Editoriale\nRevisioni Maggiori."


@pytest.fixture
def esecuzione(tmp_path, monkeypatch, percorso_config, config_ricerca):
    file_draft = tmp_path / "draft.md"
    file_draft.write_text(TESTO_DRAFT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with patch.object(CriticalReviewerAgent, "_call_llm",
                      return_value=(True, REVIEW_CRITICA)) as critico, \
         patch.object(ConstructiveReviewerAgent, "_call_llm",
                      return_value=(True, REVIEW_PROPOSITIVA)) as propositivo, \
         patch.object(EditorAgent, "_call_llm",
                      return_value=(True, REPORT_EDITORIALE)) as editor:
        run_research_workflow(
            workflow_type="review_simulata",
            config_path=percorso_config("config_simulated_review.yaml"),
            initial_data={
                "run_id": "test",
                "start_timestamp": "20260930",
                "task_overrides": {"file_reader_agent": {
                    "file_draft": str(file_draft), "file_review": None}},
            },
            main_config=config_ricerca,
        )

    return {
        "salvati": list((tmp_path / "output").iterdir()),
        "critico": critico, "propositivo": propositivo, "editor": editor,
    }


def prompt_di(mock):
    return mock.call_args.kwargs["system_prompt"]


# --- Il documento finale ---
def test_il_report_dell_editor_viene_scritto_su_file(esecuzione):
    salvati = esecuzione["salvati"]
    assert [f.name for f in salvati] == ["20260930_test_review_simulata.md"]
    assert salvati[0].read_text(encoding="utf-8") == REPORT_EDITORIALE


# --- Cosa vede ciascun agente ---
@pytest.mark.parametrize("agente", ["critico", "propositivo", "editor"])
def test_ogni_agente_riceve_il_draft_in_coda_al_prompt(esecuzione, agente):
    assert prompt_di(esecuzione[agente]).rstrip().endswith(TESTO_DRAFT)


def test_l_editor_vede_i_commenti_dei_due_revisori(esecuzione):
    prompt = prompt_di(esecuzione["editor"])
    assert "Rete troppo rada." in prompt
    assert "Dataset originale." in prompt


@pytest.mark.parametrize("giudizio", [
    "Lavoro solido ma metodologia da rafforzare.",   # valutazione_complessiva
    "Alto per la comunità vulcanologica.",            # potenziale_impatto
    "Confrontare con il 2012-2014.",                  # raccomandazioni_strategiche
], ids=["valutazione_complessiva", "potenziale_impatto", "raccomandazioni_strategiche"])
def test_l_editor_vede_i_giudizi_di_sintesi_dei_revisori(esecuzione, giudizio):
    # I prompt dei revisori chiedono questi campi: devono arrivare all'editor.
    assert giudizio in prompt_di(esecuzione["editor"])
