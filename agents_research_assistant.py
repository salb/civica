# ===================================================================
# agents_research_assistant.py
#
# Defines the agent classes and factory for the research assistant
# workflows: peer review support and simulated review.
#
# The file is self-contained: all agents required by both workflows
# are registered in the single get_agent_instance factory at the bottom.
# ===================================================================

import logging
import os
from rich.markup import escape

from core_framework import BaseAgent, OpenAIClientMixin, create_agent_instance
from utils import substitute_placeholders


# --- RULE-BASED AGENTS ---


class FileReaderAgent(BaseAgent):
    """
    Rule-based agent that reads the content of one or two input files.

    Both file paths are optional: the agent reads only the paths provided
    in the task dict, without fallbacks. At least one path must be present.
    Output keys use Italian domain names (testo_review_originale,
    testo_draft_originale) consistent with the YAML workflow configuration.
    """

    def run(self, task: dict, current_state: any) -> tuple[bool, any]:
        self.logger.demo("📂 [File Reader Agent] Reading input files...")
        try:
            if not isinstance(task, dict):
                raise TypeError(
                    f"FileReaderAgent expects a dict task, got {type(task)}"
                )

            review_file_path = task.get("file_review")
            draft_file_path = task.get("file_draft")

            if not review_file_path and not draft_file_path:
                raise ValueError(
                    "No file path provided in the task for FileReaderAgent."
                )

            # Domain keys kept in Italian: referenced by YAML path expressions
            output_data = {
                "testo_review_originale": None,
                "testo_draft_originale": None,
            }

            if review_file_path:
                self.logger.demo(
                    f"  -> Reading review file: '{review_file_path}'"
                )
                with open(review_file_path, encoding="utf-8") as f:
                    output_data["testo_review_originale"] = f.read()
                self.logger.demo(
                    f"  -> File '{review_file_path}' read successfully."
                )

            if draft_file_path:
                self.logger.demo(
                    f"  -> Reading draft file: '{draft_file_path}'"
                )
                with open(draft_file_path, encoding="utf-8") as f:
                    output_data["testo_draft_originale"] = f.read()
                self.logger.demo(
                    f"  -> File '{draft_file_path}' read successfully."
                )

            return True, output_data

        except FileNotFoundError as e:
            self.logger.error(
                f"🔥 ERROR: File not found → {e.filename}. "
                f"Check that the file path is correct."
            )
            return False, {"failure_reason": f"File not found: {e.filename}"}
        except Exception as e:
            self.logger.error(
                f"🔥 ERROR: Could not read files. Details: {e}"
            )
            return False, {"failure_reason": f"File read error: {str(e)}"}


class FileWriterAgent(BaseAgent):
    """
    Rule-based agent that writes the final Markdown report to disk.

    Reads the report content from the 'report_finale_markdown' key in
    collected_data. The output directory and filename are specified in
    the task dict; both have sensible defaults.

    Returns a dict with key 'saved_file_path' pointing to the written file.
    """

    def run(self, task: dict, current_state: any) -> tuple[bool, any]:
        self.logger.demo("💾 [File Writer Agent] Saving final output...")
        try:
            content = current_state.get_data_field("report_finale_markdown")
            if not content:
                raise ValueError(
                    "No content found at 'report_finale_markdown' in "
                    "collected_data. Nothing to save."
                )

            output_dir = task.get("output_dir", "output")
            filename = task.get("filename", "output.md")

            os.makedirs(output_dir, exist_ok=True)
            full_path = os.path.join(output_dir, filename)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.logger.demo(
                f"  -> Report saved to: [bold cyan]{escape(full_path)}[/bold cyan]",
                extra={"markup": True},
            )
            return True, {"saved_file_path": full_path}

        except Exception as e:
            self.logger.error(
                f"🔥 ERROR during file save: {e}"
            )
            return False, {"failure_reason": str(e)}


class ResponseCompilerAgent(BaseAgent):
    """
    Rule-based agent that assembles the final Markdown response document
    from a list of comments with their drafted replies.

    The task is the list of comment dicts (each containing 'revisore', 'id',
    'testo', 'bozza_risposta'). The output template is retrieved from
    'output_templates.risposta_peer_review_md' in the state.
    """

    def run(self, task: list, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "📋 [Response Compiler Agent (Rules)] "
            "Assembling final Markdown document..."
        )
        try:
            comments = task
            if not isinstance(comments, list):
                return False, {
                    "failure_reason": (
                        "ResponseCompilerAgent expects a list task."
                    )
                }

            # Template name is fixed for this agent
            template_name = "risposta_peer_review_md"
            template = (
                current_state.as_dict()
                .get("output_templates", {})
                .get(template_name, "")
            )
            if not template:
                return False, {
                    "failure_reason": (
                        f"Output template '{template_name}' not found."
                    )
                }

            sections = []
            for comment in comments:
                section = (
                    f"**Reviewer {comment.get('revisore', 'N/A')}, "
                    f"Commento {comment.get('id', 'N/A')}:**\n"
                )
                section += f"> *{comment.get('testo', '').strip()}*\n\n"
                section += "**Risposta:**\n"
                section += f"{comment.get('bozza_risposta', '').strip()}\n"
                sections.append(section)

            formatted_responses = "\n---\n\n".join(sections)
            final_output = substitute_placeholders(
                template, {"lista_risposte_formattate": formatted_responses}
            )
            self.logger.demo(
                "  -> Final Markdown document assembled successfully."
            )
            return True, final_output

        except Exception as e:
            self.logger.error(
                f"🔥 Error during Markdown compilation: {e}", exc_info=True
            )
            return False, {"failure_reason": str(e)}

class ComparisonReportAssemblerAgent(BaseAgent):
    """
    Rule-based agent that formats the TextComparatorAgent JSON output
    into a Markdown report and writes it into the state key expected
    by FileWriterAgent ('report_finale_markdown').

    No LLM call. Reads the four fixed keys from collected_data and
    formats them directly in Python (see _format_list): the report
    structure requires converting JSON lists into Markdown bullet
    points, which the generic CompilerAgent template engine
    (fill_template_recursive, scalar {key} substitution only) cannot
    express. This is the only assembler in the codebase that needs
    this, hence the dedicated class rather than an output_templates
    entry.
    """

    def run(self, task: any, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "📄 [Comparison Report Assembler] Formatting comparison report..."
        )
        try:
            def _format_list(items: list) -> str:
                if not items:
                    return "_Nessun elemento individuato._"
                # A single string would otherwise be iterated character
                # by character, producing one bullet per letter.
                if isinstance(items, str):
                    items = [items]
                return "\n".join(f"- {item}" for item in items)

            state = current_state.as_dict()

            report = (
                f"# Report di analisi delle sovrapposizioni\n\n"
                f"**ID esecuzione:** {state.get('run_id', 'N/A')}\n"
                f"**Data:** {state.get('start_timestamp', 'N/A')}\n\n"
                f"---\n\n"
                f"## Elementi comuni\n"
                f"{_format_list(current_state.get_data_field('elementi_comuni'))}\n\n"
                f"## Divergenze\n"
                f"{_format_list(current_state.get_data_field('divergenze'))}\n\n"
                f"## Lacune individuate\n"
                f"{_format_list(current_state.get_data_field('gap_identificati'))}\n\n"
                f"## Raccomandazioni\n"
                f"{_format_list(current_state.get_data_field('raccomandazioni'))}\n"
            )

            self.logger.demo("  -> Markdown report assembled successfully.")
            return True, {"report_finale_markdown": report}

        except Exception as e:
            self.logger.error(f"🔥 Error during report assembly: {e}")
            return False, {"failure_reason": str(e)}

# --- AI-POWERED AGENTS ---

class ReviewParserAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent that structures the raw review text into a clean JSON object.

    Receives the fully formatted prompt as its task; expects the LLM to
    return a JSON with a 'commenti_revisori' list key.
    """

    model_tier = "low"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"📑 [Review Parser Agent (AI-{self.model_tier})] "
            f"Parsing review text..."
        )
        success, output = self._call_llm(
            system_prompt=task, user_prompt="", is_json=True
        )
        if success and "commenti_revisori" in output:
            self.logger.demo(
                f"  -> Extracted {len(output['commenti_revisori'])} comment(s)."
            )
            return True, output
        return False, output


class CritiqueCategoriserAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent that classifies each reviewer comment into a predefined category.

    Iterates over the list of comments received as task, calling the LLM once
    per comment. The prompt template is loaded at construction time from the
    'categorize_critic_task' entry in prompt_templates.
    """

    model_tier = "low"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)
        self.prompt_template = self.agent_config.get("prompt_templates", {}).get(
            "categorize_critic_task", ""
        )

    def run(self, task: list, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"🏷️  [Critique Categoriser Agent (AI-{self.model_tier})] "
            f"Categorising comments..."
        )
        if not isinstance(task, list):
            return False, {
                "failure_reason": (
                    "CritiqueCategoriserAgent expects a list of comments as task."
                )
            }

        categorised_comments = []
        for comment in task:
            modified_comment = comment.copy()
            prompt = substitute_placeholders(
                self.prompt_template, {"testo_commento": comment.get("testo", "")}
            )
            success, out = self._call_llm(
                system_prompt=prompt, user_prompt="", is_json=True
            )
            category = out.get("categoria", "sconosciuta") if success else "sconosciuta"
            modified_comment["categoria"] = category
            self.logger.demo(
                f"  -> Comment #{comment.get('id')} "
                f"(Rev {comment.get('revisore')}) → category: '{category}'"
            )
            categorised_comments.append(modified_comment)

        return True, {"commenti_revisori_categorizzati": categorised_comments}


class ResponseStrategistAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent that generates a contextualised draft reply for each reviewer
    comment received as task.

    Applies a two-role prompt pattern: the system prompt carries the strategic
    instructions (loaded from 'strategy_response_task_contextual'), while the
    user prompt carries the specific comment and the full manuscript draft.
    This separation keeps instructions stable across iterations and allows
    the LLM to focus context attention on the variable data.
    """

    model_tier = "high"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)
        # The instructions-only system prompt is loaded once at construction
        self.prompt_template_istruzioni = self.agent_config.get(
            "prompt_templates", {}
        ).get("strategy_response_task_contextual", "")

    def run(self, task: list, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"✍️  [Response Strategist Agent (AI-{self.model_tier})] "
            f"Generating contextualised draft replies..."
        )
        if not isinstance(task, list):
            return False, {
                "failure_reason": (
                    "ResponseStrategistAgent expects a list of comments as task."
                )
            }

        draft_text = current_state.get_data_field("testo_draft_originale", "")
        if not draft_text:
            self.logger.warning(
                "WARNING: Draft text not found in state. "
                "Responses may be generic."
            )

        comments_with_draft = []

        for comment in task:
            # Step 1: strategic instructions → system prompt (stable across iterations)
            system_prompt = self.prompt_template_istruzioni

            # Step 2: specific data for this comment → user prompt (variable per iteration)
            # The user prompt is in Italian to match the localised prompt template.
            user_prompt = f"""
            **CONTESTO COMPLETO**

            **1. Critica del Revisore da affrontare:**
            - Categoria: "{comment.get('categoria', 'sconosciuta')}"
            - Testo: "{comment.get('testo', '')}"

            **2. Testo completo del manoscritto originale (Draft) a cui si riferisce la critica:**
            ---
            {draft_text}
            ---

            Genera ora la tua analisi e la bozza di risposta.
            """

            # Step 3: execute with separated roles
            success, draft_text_output = self._call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                is_json=False,
            )

            draft = (
                draft_text_output
                if success
                else "[ERROR GENERATING DRAFT RESPONSE]"
            )
            modified_comment = comment.copy()
            modified_comment["bozza_risposta"] = draft
            self.logger.demo(
                f"  -> Draft generated for comment #{comment.get('id')} "
                f"(Rev {comment.get('revisore')})"
            )
            comments_with_draft.append(modified_comment)

        return True, {"commenti_con_risposta": comments_with_draft}


class CriticalReviewerAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent acting as a rigorous academic reviewer.
    Identifies weaknesses, methodological issues, and publication blockers
    in the manuscript. Returns a JSON with a 'commenti_critici' list.
    """

    model_tier = "high"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"🧐 [Critical Reviewer Agent (AI-{self.model_tier})] "
            f"Identifying weaknesses..."
        )
        success, output = self._call_llm(
            system_prompt=task, user_prompt="", is_json=True
        )
        if success:
            self.logger.demo(
                f"  -> Found {len(output.get('commenti_critici', []))} "
                f"critical point(s)."
            )
        return success, output


class ConstructiveReviewerAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent acting as a constructive academic mentor.
    Identifies strengths, impact opportunities, and enhancement suggestions
    in the manuscript. Returns a JSON with a 'commenti_propositivi' list.
    """

    model_tier = "high"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"👍 [Constructive Reviewer Agent (AI-{self.model_tier})] "
            f"Identifying strengths..."
        )
        success, output = self._call_llm(
            system_prompt=task, user_prompt="", is_json=True
        )
        if success:
            self.logger.demo(
                f"  -> Found {len(output.get('commenti_propositivi', []))} "
                f"improvement suggestion(s)."
            )
        return success, output


class EditorAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent acting as editor-in-chief.
    Synthesises the critical and constructive reviews into a structured
    editorial report with a publication recommendation and prioritised
    action list. Returns a free-text Markdown string.
    """

    model_tier = "high"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"🖋️  [Editor Agent (AI-{self.model_tier})] "
            f"Synthesising final editorial report..."
        )
        success, output = self._call_llm(
            system_prompt=task, user_prompt="", is_json=False
        )
        if success:
            self.logger.demo("  -> Final report generated.")
        return success, output

class TextComparatorAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent that performs a structured comparison between two texts or
    serialised data structures.

    Receives a fully-formatted prompt as its task (assembled by the
    orchestrator from the YAML template). Always returns a JSON object
    with four fixed keys:
        - elementi_comuni:   shared claims, methods, or findings
        - divergenze:        explicit contradictions or incompatible choices
        - gap_identificati:  aspects present in one text and absent in the other
        - raccomandazioni:   actionable suggestions based on the comparison

    The comparison criterion is entirely determined by the prompt template
    in the YAML configuration — no domain logic is hard-coded here.
    """

    model_tier = "normal"

    def __init__(
        self,
        agent_config: dict = None,
        model_name: str = None,
        logger: logging.Logger = None,
    ):
        BaseAgent.__init__(self, agent_config=agent_config, logger=logger)
        OpenAIClientMixin.__init__(self, agent_config=agent_config, model_name=model_name)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"🔍 [Text Comparator Agent (AI-{self.model_tier})] "
            f"Comparing documents..."
        )
        success, output = self._call_llm(
            system_prompt=task, user_prompt="", is_json=True
        )
        if success:
            n_comuni     = len(output.get("elementi_comuni",    []))
            n_divergenze = len(output.get("divergenze",         []))
            n_gap        = len(output.get("gap_identificati",   []))
            self.logger.demo(
                f"  -> Comparison complete: {n_comuni} common element(s), "
                f"{n_divergenze} divergence(s), {n_gap} gap(s) identified."
            )
        return success, output

# --- AGENT FACTORY ---


def get_agent_instance(
    agent_name: str, config: dict = None, logger: logging.Logger = None
) -> BaseAgent:
    """
    Factory function that creates and returns an instance of the requested
    research assistant agent.

    Delegates model resolution and instantiation to create_agent_instance
    from core_framework, which handles the AI-powered / rule-based split.

    Raises ValueError if the requested agent name is not registered.
    """
    config = config or {}
    local_logger = logger or logging.getLogger(__name__)

    available_agents = {
        "file_reader_agent": FileReaderAgent,
        "file_writer_agent": FileWriterAgent,
        "review_parser_agent": ReviewParserAgent,
        "critique_categoriser_agent": CritiqueCategoriserAgent,
        "response_strategist_agent": ResponseStrategistAgent,
        "response_compiler_agent": ResponseCompilerAgent,
        "critical_reviewer_agent": CriticalReviewerAgent,
        "constructive_reviewer_agent": ConstructiveReviewerAgent,
        "editor_agent": EditorAgent,
        "text_comparator_agent": TextComparatorAgent,
        "comparison_report_assembler_agent": ComparisonReportAssemblerAgent,
    }

    agent_class = available_agents.get(agent_name)
    if not agent_class:
        raise ValueError(
            f"Agent '{agent_name}' not found in research assistant factory. "
            f"Available: {sorted(available_agents.keys())}"
        )

    return create_agent_instance(agent_class, agent_name, config, local_logger)