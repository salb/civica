# tests/test_overlap_analysis_workflow.py
#
# Strato 2, test di percorso sul workflow "analisi di sovrapposizione":
# legge due documenti, un LLM li confronta e restituisce quattro liste
# (elementi comuni, divergenze, gap, raccomandazioni), un agente a regole
# le impagina in Markdown e il risultato viene scritto su file.
#
# Nota: il lettore di file ha due slot chiamati "review" e "draft".
# Il runner mette il documento A nel primo e il B nel secondo.

import pytest
from unittest.mock import patch

from agents_research_assistant import TextComparatorAgent
from run_research_assistant import run_research_workflow

TESTO_A = "Documento A: sismicità 2012-2014 ai Campi Flegrei."
TESTO_B = "Documento B: deformazione del suolo 2012-2014."

CONFRONTO_FINTO = {
    "elementi_comuni": ["Stesso periodo di osservazione."],
    "divergenze": ["Grandezze fisiche diverse."],
    "gap_identificati": ["Solo A tratta la sismicità."],
    "raccomandazioni": ["Integrare i due dataset."],
}


@pytest.fixture
def esegui_confronto(tmp_path, monkeypatch, percorso_config, config_ricerca):
    """Restituisce una funzione che esegue il workflow con una risposta LLM data."""
    def _esegui(risposta_llm):
        file_a = tmp_path / "a.md"
        file_b = tmp_path / "b.md"
        file_a.write_text(TESTO_A, encoding="utf-8")
        file_b.write_text(TESTO_B, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.object(TextComparatorAgent, "_call_llm",
                          return_value=(True, risposta_llm)) as comparatore:
            run_research_workflow(
                workflow_type="analisi_sovrapposizione",
                config_path=percorso_config("config_overlap_analysis.yaml"),
                initial_data={
                    "run_id": "test",
                    "start_timestamp": "20260930",
                    # Come nel runner: A nello slot "review", B nello slot "draft".
                    "task_overrides": {"file_reader_agent": {
                        "file_review": str(file_a), "file_draft": str(file_b)}},
                },
                main_config=config_ricerca,
            )

        salvati = list((tmp_path / "output").iterdir())
        return {"salvati": salvati, "comparatore": comparatore}
    return _esegui


def report_di(esecuzione):
    return esecuzione["salvati"][0].read_text(encoding="utf-8")


# --- Il documento finale ---
def test_il_nome_del_file_segue_la_convenzione_degli_altri_workflow(esegui_confronto):
    # {start_timestamp}_{run_id}_{workflow}.md: il run_id lega l'output al suo log.
    salvati = esegui_confronto(CONFRONTO_FINTO)["salvati"]
    assert [f.name for f in salvati] == ["20260930_test_analisi_sovrapposizione.md"]


def test_le_quattro_sezioni_contengono_le_voci_del_confronto(esegui_confronto):
    report = report_di(esegui_confronto(CONFRONTO_FINTO))
    for voci in CONFRONTO_FINTO.values():
        assert f"- {voci[0]}" in report


# --- Cosa arriva all'LLM ---
def test_a_e_b_arrivano_al_prompt_ciascuno_al_suo_posto(esegui_confronto):
    # Gli slot si chiamano "review" e "draft", ma l'ordine A/B deve reggere.
    prompt = esegui_confronto(CONFRONTO_FINTO)["comparatore"].call_args.kwargs["system_prompt"]
    assert prompt.index("TESTO A:") < prompt.index(TESTO_A) < prompt.index("TESTO B:") < prompt.index(TESTO_B)


# --- Risposte LLM imperfette ---
def test_una_voce_mancante_diventa_una_sezione_vuota(esegui_confronto):
    confronto = {k: v for k, v in CONFRONTO_FINTO.items() if k != "divergenze"}
    report = report_di(esegui_confronto(confronto))
    assert "## Divergenze\n_Nessun elemento individuato._" in report


def test_una_stringa_al_posto_della_lista_diventa_una_sola_voce(esegui_confronto):
    # Il prompt chiede liste, ma un LLM a volte restituisce una stringa sola.
    confronto = {**CONFRONTO_FINTO, "raccomandazioni": "Integrare i due dataset."}
    report = report_di(esegui_confronto(confronto))
    assert "## Raccomandazioni\n- Integrare i due dataset.\n" in report


# --- Lingua del report ---
def test_il_report_ha_i_titoli_in_italiano(esegui_confronto):
    report = report_di(esegui_confronto(CONFRONTO_FINTO))
    for titolo in ["# Report di analisi delle sovrapposizioni", "**ID esecuzione:**",
                   "**Data:**", "## Elementi comuni", "## Divergenze",
                   "## Lacune individuate", "## Raccomandazioni"]:
        assert titolo in report
