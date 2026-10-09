# run_research_assistant.py
#
# Entry point for the AI Research Assistant.
# Handles the main interaction loop, top-level triage, and workflow dispatch
# for the peer review support and simulated review workflows.

import datetime
import logging

import yaml
from dotenv import load_dotenv
from rich import print as rprint
from rich.markup import escape

from agents_research_assistant import get_agent_instance as research_agent_factory
from core_framework import get_utility_agent_instance
from logger_config import setup_logging
from orchestrator import AdvancedOrchestrator, create_composite_factory
from utils import ask_valid_file_path


def run_research_workflow(
    workflow_type: str, config_path: str, initial_data: dict, main_config: dict
):
    """
    Generic helper that configures and runs a single research workflow.

    All initial_data keys are injected as dynamic (non-reserved) state
    variables via set_global_variable: unlike the administrative runner,
    the research workflows do not require setting a typed request_type.
    """
    logger = logging.getLogger(__name__)
    logger.demo(
        f"\n[bold]--- Starting workflow: [yellow]{escape(workflow_type)}[/yellow] ---[/bold]",
        extra={"markup": True},
    )

    composite_factory_instance = create_composite_factory(
        research_agent_factory, logger
    )

    orchestrator = AdvancedOrchestrator(
        config_path=config_path,
        agent_factory=composite_factory_instance,
        main_config=main_config,
    )

    for key, value in initial_data.items():
        orchestrator.state.set_global_variable(key, value)

    final_result = orchestrator.run_iterative_workflow()

    logger.demo(
        f"\n[bold]--- Workflow result: [yellow]{escape(workflow_type)}[/yellow] ---[/bold]",
        extra={"markup": True},
    )
    if isinstance(final_result, dict) and final_result.get("status") == "failed":
        logger.error(
            f"❌ Workflow failed ({final_result.get('reason')}): "
            f"{final_result.get('error')}"
        )
        logger.demo(
            "[dim]Details available in the trace log under logs/.[/dim]",
            extra={"markup": True},
        )
    elif isinstance(final_result, dict) and "saved_file_path" in final_result:
        logger.demo(
            f"✅ [bold green]Success![/bold green] Output file written to: "
            f"[cyan]{escape(final_result['saved_file_path'])}[/cyan]",
            extra={"markup": True},
        )
    elif isinstance(final_result, str):
        max_len = 1000
        truncated_output = (
            (final_result[:max_len] + "...")
            if len(final_result) > max_len
            else final_result
        )
        logger.demo(truncated_output)
        logger.demo(
            "[dim]Full output available in the trace log under logs/.[/dim]",
            extra={"markup": True},
        )
    else:
        # Fallback for other output types (e.g. error dicts from the debugger)
        logger.demo(final_result)


def main():
    load_dotenv()

    run_id = setup_logging()
    logger = logging.getLogger(__name__)

    try:
        with open("config/config_research_assistant.yaml", encoding="utf-8") as f:
            main_config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(
            "Error: 'config/config_research_assistant.yaml' not found."
        )
        return

    triage_agent = get_utility_agent_instance(
        "main_triage_agent", main_config, logger
    )

    rprint("\n[bold green]--- AI Research Assistant (v1.0) ---[/bold green]")
    rprint("Hello! I am your AI research partner.")
    rprint("[dim]Type 'quit' or 'exit' to terminate.[/dim]")

    while True:
        try:
            rprint("\n[bold]How can I help you? > [/bold]", end="")
            user_request = input()
            if user_request.lower() in ["quit", "exit"]:
                break
            if not user_request:
                continue

            logger.demo(f"Analysing request: '{user_request}'...")

            # The triage prompt template key is kept in Italian,
            # consistent with the localisation policy for prompt_templates.
            full_prompt = (
                f"{main_config['prompt_templates']['triage_principale_task']}"
                f"\n\nRichiesta utente da analizzare: '{user_request}'"
            )
            success, output = triage_agent.run(full_prompt, {})

            if not success:
                logger.error(f"🔥 OpenAI communication error: {output}")

            # 'tipo_workflow' is the JSON key returned by the Italian triage prompt
            workflow_type = (
                output.get("tipo_workflow", "unknown") if success else "unknown"
            )

            logger.demo(
                f"Triage decision: launching workflow "
                f"'[bold cyan]{escape(str(workflow_type))}[/bold cyan]'.",
                extra={"markup": True},
            )

            workflow_config = main_config.get("workflows", {}).get(workflow_type)

            if not workflow_config or not workflow_config.get("config_file"):
                logger.demo(
                    f"Workflow '{workflow_type}' is not configured or not yet "
                    f"implemented. Please rephrase your request."
                )
                continue

            specific_config_path = workflow_config["config_file"]

            # Inject a start timestamp into the state so that output filenames
            # are unique and traceable per run.
            start_timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            common_initial_data = {
                "run_id": run_id,
                "start_timestamp": start_timestamp,
            }
            initial_data = {}

            # Workflow type identifiers are the values produced by the Italian
            # triage prompt — they are intentionally kept in Italian to remain
            # consistent with the prompt templates (localisation example).
            if workflow_type == "supporto_review":
                logger.demo(
                    "To assist with your review I need two files."
                )
                file_review = ask_valid_file_path(
                    "Path to the file with reviewer comments (e.g. review.md): "
                )
                file_draft = ask_valid_file_path(
                    "Path to the file with your manuscript draft (e.g. draft.md): "
                )
                task_data = {
                    "file_review": file_review,
                    "file_draft": file_draft,
                }
                initial_data = {
                    **common_initial_data,
                    "task_overrides": {"file_reader_agent": task_data},
                }
                run_research_workflow(
                    workflow_type="supporto_review",
                    config_path=specific_config_path,
                    initial_data=initial_data,
                    main_config=main_config,
                )

            elif workflow_type == "review_simulata":
                logger.demo(
                    "You selected 'Simulated Review'. I need your manuscript."
                )
                file_draft = ask_valid_file_path(
                    "Path to the file with your manuscript draft (e.g. draft.md): "
                )
                task_data = {
                    "file_draft": file_draft,
                    "file_review": None,
                }
                initial_data = {
                    **common_initial_data,
                    "task_overrides": {"file_reader_agent": task_data},
                }
                run_research_workflow(
                    workflow_type="review_simulata",
                    config_path=specific_config_path,
                    initial_data=initial_data,
                    main_config=main_config,
                )

            elif workflow_type == "analisi_sovrapposizione":
                logger.demo(
                    "You selected 'Overlap Analysis'. I need two documents to compare."
                )
                file_a = ask_valid_file_path(
                    "Path to Document A (e.g. paper_a.md): "
                )
                file_b = ask_valid_file_path(
                    "Path to Document B (e.g. paper_b.md): "
                )
                task_data = {
                    "file_review": file_a,
                    "file_draft":  file_b,
                }
                initial_data = {
                    **common_initial_data,
                    "task_overrides": {"file_reader_agent": task_data},
                }
                run_research_workflow(
                    workflow_type="analisi_sovrapposizione",
                    config_path=specific_config_path,
                    initial_data=initial_data,
                    main_config=main_config,
                )

            else:
                logger.demo(
                    "Request not understood. Please rephrase."
                )

        except (KeyboardInterrupt, EOFError):
            break

    rprint("\n[bold blue]Thank you for using the assistant. Goodbye![/bold blue] 👋")


if __name__ == "__main__":
    main()