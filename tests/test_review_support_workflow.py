# tests/test_review_support_workflow.py
#
# Strato 2, test di percorso sul workflow "supporto review":
# legge una review e un draft da file, estrae i commenti, li classifica,
# prepara una bozza di risposta per ciascuno e scrive un documento Markdown.
# Si passa dal runner vero (run_research_workflow) con file finti in tmp_path.

import logging

import pytest
from unittest.mock import patch

from agents_research_assistant import (
    CritiqueCategoriserAgent,
    ResponseCompilerAgent,
    ResponseStrategistAgent,
    ReviewParserAgent,
)
from orchestrator import WorkflowState
from run_research_assistant import run_research_workflow

TESTO_REVIEW = "Revisore 1\n- Manca la risoluzione della rete.\n- Refuso in figura 3."
TESTO_DRAFT = "Il nostro manoscritto sulla sismicità dei Campi Flegrei."

COMMENTI_FINTI = {"commenti_revisori": [
    {"revisore": "1", "id": 1, "testo": "Manca la risoluzione della rete."},
    {"revisore": "1", "id": 2, "testo": "Refuso in figura 3."},
]}
CATEGORIE_FINTE = [(True, {"categoria": "Critica Metodologica"}),
                   (True, {"categoria": "Errore Minore"})]
RISPOSTE_FINTE = [(True, "Risposta al primo commento."),
                  (True, "Risposta al secondo commento.")]


@pytest.fixture
def esecuzione(tmp_path, monkeypatch, percorso_config, config_ricerca):
    """Prepara i due file, esegue il workflow dal runner, raccoglie report e mock."""
    file_review = tmp_path / "review.md"
    file_draft = tmp_path / "draft.md"
    file_review.write_text(TESTO_REVIEW, encoding="utf-8")
    file_draft.write_text(TESTO_DRAFT, encoding="utf-8")

    # Il FileWriterAgent scrive in "output/" relativo alla cartella corrente.
    monkeypatch.chdir(tmp_path)

    with patch.object(ReviewParserAgent, "_call_llm",
                      return_value=(True, COMMENTI_FINTI)) as parser, \
         patch.object(CritiqueCategoriserAgent, "_call_llm",
                      side_effect=CATEGORIE_FINTE), \
         patch.object(ResponseStrategistAgent, "_call_llm",
                      side_effect=RISPOSTE_FINTE) as stratega:
        run_research_workflow(
            workflow_type="supporto_review",
            config_path=percorso_config("config_review_support.yaml"),
            initial_data={
                "run_id": "test",
                "start_timestamp": "20260930",
                "task_overrides": {"file_reader_agent": {
                    "file_review": str(file_review), "file_draft": str(file_draft)}},
            },
            main_config=config_ricerca,
        )

    salvati = list((tmp_path / "output").iterdir())
    return {"salvati": salvati, "parser": parser, "stratega": stratega}


# --- Il documento finale ---
def test_viene_scritto_un_solo_documento_markdown(esecuzione):
    assert [f.name for f in esecuzione["salvati"]] == ["20260930_test_supporto_review.md"]


def test_ogni_commento_ha_la_sua_risposta_nell_ordine(esecuzione):
    report = esecuzione["salvati"][0].read_text(encoding="utf-8")
    posizioni = [report.index(t) for t in (
        "Manca la risoluzione della rete.", "Risposta al primo commento.",
        "Refuso in figura 3.", "Risposta al secondo commento.",
    )]
    assert posizioni == sorted(posizioni)


# --- Cosa arriva agli LLM ---
def test_il_parser_riceve_il_testo_letto_dal_file(esecuzione):
    prompt = esecuzione["parser"].call_args.kwargs["system_prompt"]
    assert TESTO_REVIEW in prompt


def test_il_prompt_del_parser_non_contiene_graffe_doppie(esecuzione):
    # Le graffe doppie {{ }} sono la convenzione di str.format: il core non
    # le usa, quindi arriverebbero all'LLM così come sono, in un esempio JSON.
    prompt = esecuzione["parser"].call_args.kwargs["system_prompt"]
    assert "{{" not in prompt and "}}" not in prompt


def test_ogni_bozza_di_risposta_vede_il_draft(esecuzione):
    chiamate = esecuzione["stratega"].call_args_list
    assert len(chiamate) == 2
    assert all(TESTO_DRAFT in c.kwargs["user_prompt"] for c in chiamate)


# --- Graffe letterali nei template scritti dall'utente ---
# Un template YAML può contenere graffe che non sono segnaposto:
# un esempio JSON in un prompt, un comando LaTeX in una lettera.
def test_il_classificatore_accetta_un_esempio_json_nel_prompt():
    agente = CritiqueCategoriserAgent(
        agent_config={"prompt_templates": {"categorize_critic_task":
            'Rispondi così: {"categoria": "..."}\nCritica: "{testo_commento}"'}},
        logger=logging.getLogger("test"),
    )
    with patch.object(CritiqueCategoriserAgent, "_call_llm",
                      return_value=(True, {"categoria": "Errore Minore"})) as llm:
        agente.run([{"id": 1, "testo": "Refuso."}], WorkflowState({}))
    prompt = llm.call_args.kwargs["system_prompt"]
    assert prompt == 'Rispondi così: {"categoria": "..."}\nCritica: "Refuso."'


def test_il_compilatore_accetta_graffe_latex_nella_lettera():
    stato = WorkflowState({"output_templates": {"risposta_peer_review_md":
        "\\section*{Response}\n{lista_risposte_formattate}"}})
    agente = ResponseCompilerAgent(logger=logging.getLogger("test"))
    successo, lettera = agente.run(
        [{"revisore": "1", "id": 1, "testo": "t", "bozza_risposta": "r"}], stato)
    assert successo
    assert lettera.startswith("\\section*{Response}\n**Reviewer 1")
