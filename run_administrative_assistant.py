# run_administrative_assistant.py
#
# Entry point for the AI Administrative Assistant.
# Handles the main interaction loop, top-level triage, and workflow dispatch.

import datetime
import json
import logging
import os
from datetime import date

import yaml
from dotenv import load_dotenv
from rich import print as rprint

from agents_administrative_assistant import get_agent_instance as administrative_agent_factory
from core_framework import get_utility_agent_instance
from logger_config import setup_logging
from orchestrator import AdvancedOrchestrator, create_composite_factory


def run_admin_workflow(
    workflow_type: str, config_path: str, initial_data: dict, main_config: dict
):
    """
    Helper that configures and runs a single administrative workflow.

    Injects initial state variables into the orchestrator, distinguishing
    between reserved keys (routed to typed setters) and dynamic keys
    (written via set_global_variable). Also injects today's date as the
    dynamic state variable 'current_date' for use by prompt templates.
    """
    logger = logging.getLogger(__name__)
    logger.demo(
        f"\n[bold]--- Starting workflow: [yellow]{workflow_type}[/yellow] ---[/bold]"
    )

    composite_factory_instance = create_composite_factory(
        administrative_agent_factory, logger
    )

    orchestrator = AdvancedOrchestrator(
        config_path=config_path,
        agent_factory=composite_factory_instance,
        main_config=main_config,
    )

    # Inject initial state variables.
    # Reserved keys must go through their dedicated typed setters:
    # set_global_variable raises ValueError if called with a reserved key.
    for key, value in initial_data.items():
        if key == "request_type":
            orchestrator.state.set_request_type(value)
        else:
            orchestrator.state.set_global_variable(key, value)

    # Always inject today's date as a dynamic (non-reserved) state variable,
    # available to prompt templates as {current_date}.
    orchestrator.state.set_global_variable(
        "current_date", date.today().strftime("%Y-%m-%d")
    )

    final_result = orchestrator.run_iterative_workflow()

    # Log and save the final result
    logger.demo(
        f"\n[bold]--- Workflow result: [yellow]{workflow_type}[/yellow] ---[/bold]"
    )
    try:
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        formatted_result = json.dumps(final_result, indent=2, ensure_ascii=False)
        logger.demo(formatted_result)

        save_timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = initial_data.get("run_id", "no-id")
        failed = isinstance(final_result, dict) and final_result.get("status") == "failed"
        label = "FAILED" if failed else "output"
        output_filename = f"{save_timestamp}_{run_id}_{label}_{workflow_type}.json"
        full_path = os.path.join(output_dir, output_filename)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        if failed:
            logger.error(f"❌ Workflow failed. Diagnosis saved to: {full_path}")
        else:
            logger.demo(f"\n📄 Result saved to: {full_path}")

    except (TypeError, json.JSONDecodeError):
        logger.demo(final_result)


def main():
    load_dotenv()

    run_id = setup_logging()
    logger = logging.getLogger(__name__)

    try:
        with open("config/config_administrative_assistant.yaml", encoding="utf-8") as f:
            main_config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(
            "Error: 'config/config_administrative_assistant.yaml' not found."
        )
        return

    triage_agent = get_utility_agent_instance("main_triage_agent", main_config, logger)

    rprint("\n[bold green]--- AI Administrative Assistant (v1.0) ---[/bold green]")
    rprint("Hello! I am your administrative AI partner.")
    rprint("[dim]Type 'quit' or 'exit' to terminate.[/dim]")

    while True:
        try:
            rprint("\n[bold]How can I assist you today? > [/bold]", end="")
            user_request = input()
            if user_request.lower() in ["quit", "exit"]:
                break
            if not user_request:
                continue

            logger.demo(f"Analysing request: '{user_request}'...")

            # The triage prompt template key is kept in Italian,
            # consistent with the localisation policy for prompt_templates.
            triage_prompt = main_config["prompt_templates"]["triage_amministrativo_task"]
            full_prompt = (
                f"{triage_prompt}\n\n"
                f"Richiesta utente da analizzare: '{user_request}'"
            )
            success, output = triage_agent.run(full_prompt, {})

            if not success:
                logger.error(
                    f"🔥 OpenAI communication error: {output}"
                )

            # 'tipo_workflow' is the JSON key returned by the Italian triage prompt
            workflow_type = (
                output.get("tipo_workflow", "unknown") if success else "unknown"
            )

            workflow_config = main_config.get("workflows", {}).get(workflow_type)

            if not workflow_config or not workflow_config.get("config_file"):
                logger.demo(
                    f"Request not understood or workflow '{workflow_type}' "
                    f"is not yet implemented."
                )
                continue

            logger.demo(
                f"Triage decision: launching workflow "
                f"'[bold cyan]{workflow_type}[/bold cyan]'."
            )

            specific_config_path = workflow_config["config_file"]
            initial_data = {
                "run_id": run_id,
                "user_request": user_request,
                "request_type": workflow_type,
            }

            run_admin_workflow(
                workflow_type=workflow_type,
                config_path=specific_config_path,
                initial_data=initial_data,
                main_config=main_config,
            )

        except (KeyboardInterrupt, EOFError):
            break

    rprint("\n[bold blue]Goodbye![/bold blue] 👋")


if __name__ == "__main__":
    main()