# core_framework.py
#
# Base classes and abstractions shared by all agents in the system.
#
# Also contains cross-cutting utility agents not tied to any specific workflow.
# ===================================================================

import json
import logging
import traceback

from openai import OpenAI


class BaseAgent:
    """
    Abstract base class for all agents.
    Defines the common interface that every agent must implement.
    """

    def __init__(self, agent_config: dict = None, logger: logging.Logger = None):
        self.agent_config = agent_config or {}
        self.logger = logger or logging.getLogger(__name__)

    def run(self, task: any, current_state: any) -> tuple[bool, any]:
        """Executes the agent's primary task."""
        raise NotImplementedError(
            "The 'run' method must be implemented by the subclass."
        )


class OpenAIClientMixin:
    """
    Mixin that provides centralised management of the OpenAI client and LLM
    calls. Used exclusively by AI-powered agents.

    Relies on self.logger being already initialised by BaseAgent, which works
    because this mixin is always used in classes that also inherit from BaseAgent.
    """

    def __init__(self, agent_config: dict = None, model_name: str = None):
        self.client = None
        self.model = model_name
        if not self.model:
            if hasattr(self, "logger"):
                self.logger.warning("No model name provided to the AI agent.")
            return
        try:
            self.client = OpenAI()
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.error(
                    f"Unable to initialise the OpenAI client. "
                    f"Check the API key. Details: {e}"
                )

    def _call_llm(
        self, system_prompt: str, user_prompt: str, is_json: bool = True
    ) -> tuple[bool, any]:
        """
        Performs a single chat completion call to the configured OpenAI model.

        Returns a (success, result) tuple. On failure, result is a dict
        containing a 'failure_reason' key and a full traceback.
        """
        if not self.client:
            return False, {"failure_reason": "OpenAI client not initialised."}
        try:
            response_format = {"type": "json_object"} if is_json else {"type": "text"}
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                response_format=response_format,
            )
            output = response.choices[0].message.content
            return True, json.loads(output) if is_json else output
        except Exception as e:
            return False, {
                "failure_reason": f"OpenAI API error: {str(e)}",
                "traceback": traceback.format_exc(),
            }


#
# Cross-cutting utility agents — not tied to any specific workflow.
# ===================================================================


class DebuggerAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent specialised in analysing the failure context of another agent
    to provide a root-cause diagnosis and a corrective suggestion.

    The system prompt is hardwired as a class constant (DEFAULT_PROMPT) and is
    intentionally kept in Italian so that the LLM response keys are consistent
    with the Italian prompt templates used throughout the system.
    """

    # Prompt kept in Italian: the LLM must return keys in Italian
    # (analisi_causa_radice, suggerimento_correzione, impatto_fallimento)
    # which are then read by the orchestrator's log statements.
    DEFAULT_PROMPT = (
        "Sei un esperto di debug per sistemi AI multi-agente. Hai ricevuto un log di errore "
        "dettagliato da un orchestratore in formato JSON. Il tuo compito è analizzare il contesto del fallimento e "
        "restituire un'analisi JSON concisa.\n"
        "Il JSON deve contenere tre chiavi:\n"
        "1. `analisi_causa_radice`: Una breve e chiara spiegazione di cosa ha causato l'errore.\n"
        "2. `suggerimento_correzione`: Un consiglio pratico per risolvere il problema (es. modificare il prompt, correggere la configurazione YAML, o sistemare la logica dell'agente).\n"
        "3. `impatto_fallimento`: Una stima della gravità ('BASSO', 'MEDIO', 'ALTO')."
    )
    model_tier = "normal"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: dict, current_state: any) -> tuple[bool, any]:
        self.logger.demo("🕵️  [Debugger Agent] Starting failure analysis...")

        error_context_str = json.dumps(task, indent=2, ensure_ascii=False, default=str)
        full_prompt = (
            f"{self.DEFAULT_PROMPT}\n\n"
            f"--- CONTESTO DEL FALLIMENTO ---\n"
            f"{error_context_str}\n\n"
            f"--- FINE CONTESTO ---\n\n"
            f"Fornisci la tua analisi nel formato JSON richiesto."
        )

        success, output = self._call_llm(full_prompt, user_prompt="", is_json=True)

        if success:
            self.logger.demo("🕵️  [Debugger Agent] Analysis received.")
            return True, output
        else:
            self.logger.error(
                f"❗ [Debugger Agent] Error during self-analysis: "
                f"{output.get('failure_reason')}"
            )
            # Fallback dict uses Italian keys to remain consistent with what
            # the orchestrator expects from a successful DebuggerAgent response.
            fallback_error = {
                "analisi_causa_radice": "Critical failure of the Debugger Agent itself.",
                "suggerimento_correzione": (
                    "Check the DebuggerAgent API call, its prompt, or the API key."
                ),
                "impatto_fallimento": "ALTO",
            }
            return False, fallback_error


class MainTriageAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent acting as the main dispatcher. Interprets the user's free-text
    request and classifies it into one of the available macro-workflows.

    A fast (low-tier) model is appropriate here: the task is classification,
    not generation.
    """

    model_tier = "low"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        super().__init__(agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: str, current_state: any = None) -> tuple[bool, any]:
        """
        Executes the classification.

        The 'task' received is the fully formatted prompt, already assembled
        by the caller (run_*.py). The user prompt is left empty because all
        context is embedded in the system prompt.
        """
        return self._call_llm(system_prompt=task, user_prompt="", is_json=True)


class HumanInputAgent(BaseAgent):
    """
    Generic agent for handling user interaction at runtime.

    Supports two input modes:
    - Static: questions are provided directly as a list in the task field.
    - Dynamic: the task contains the sentinel value 'ask_from_state', which
      causes the agent to retrieve pending questions from the workflow state.
    """

    def run(self, task: any, current_state: any) -> tuple[bool, any]:
        self.logger.demo("\n--- 📝 WAITING FOR HUMAN INPUT ---")
        questions = []

        # Mode 1: task is a static list of questions defined in the YAML
        if isinstance(task, list):
            questions = task
        # Mode 2: task is the sentinel command to read questions from state
        elif isinstance(task, str) and task == "ask_from_state":
            questions = current_state.get_pending_questions()

        if not questions:
            self.logger.warning(
                "HumanInputAgent activated but no questions are pending."
            )
            return True, {}

        collected_answers = {}
        for item in questions:
            if isinstance(item, dict) and "question" in item and "key" in item:
                answer = input(f"❓ {item.get('question')} ")
                collected_answers[item.get("key")] = answer
            else:
                self.logger.error(f"Invalid question format: {item}")

        self.logger.demo("✅ Input received. Data updated.")
        return True, collected_answers


def create_agent_instance(
    agent_class: type, agent_name: str, config: dict, logger: logging.Logger
) -> BaseAgent:
    """
    Centralised utility function for instantiating an agent.

    Automatically resolves the model_tier for AI-powered agents by looking up
    the tier name in the 'ai_models' configuration map, avoiding duplicated
    resolution logic across domain factories.
    """
    if issubclass(agent_class, OpenAIClientMixin):
        model_tier = getattr(agent_class, "model_tier", "normal")
        models_map = config.get("ai_models", {})
        default_model = "gpt-5.4-mini"
        model_name = models_map.get(model_tier, default_model)

        logger.demo(
            f"  🏭 [Factory] Created AI agent '{agent_name}' "
            f"(tier: '{model_tier}' → model: '{model_name}')"
        )
        return agent_class(agent_config=config, model_name=model_name, logger=logger)
    else:
        logger.demo(f"  🏭 [Factory] Created rule-based agent '{agent_name}'")
        return agent_class(agent_config=config, logger=logger)


def get_utility_agent_instance(
    agent_name: str, config: dict = None, logger: logging.Logger = None
) -> BaseAgent:
    """
    Factory function for utility (cross-cutting) agents.

    Raises ValueError if the requested agent name is not registered.
    """
    config = config or {}
    local_logger = logger or logging.getLogger(__name__)

    available_agents = {
        "debugger_agent": DebuggerAgent,
        "human_input_agent": HumanInputAgent,
        "main_triage_agent": MainTriageAgent,
    }

    agent_class = available_agents.get(agent_name)
    if not agent_class:
        raise ValueError(
            f"Utility agent '{agent_name}' not found in registry. "
            f"Available: {sorted(available_agents.keys())}"
        )

    return create_agent_instance(agent_class, agent_name, config, local_logger)