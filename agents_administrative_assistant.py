# ===================================================================
# agents_administrative_assistant.py
#
# Defines the agent classes that compose the administrative workflows.
#
# Hybrid Architecture (Rule-based + AI):
# - Rule-based agents: execute deterministic Python logic.
#   Fast, cheap, and predictable. (e.g. CompilerAgent)
# - AI-powered agents: leverage an LLM for complex tasks.
#   Flexible but require an API call. (e.g. DataExtractorAgent)
#
# Model Tier System:
# Each AI agent declares a model tier ('low', 'normal' or 'high').
# The factory function get_agent_instance resolves the tier to an actual
# model name by reading the 'ai_models' map from the global configuration,
# keeping agents agnostic to model names.
# # ===================================================================

import datetime
import logging
import re

from dateutil.parser import parse as parse_date

from core_framework import BaseAgent, OpenAIClientMixin, create_agent_instance
from utils import fill_template_recursive, is_missing_value


def _parse_date_it(value: str):
    """
    Parses a date string with Italian conventions.

    ISO format (YYYY-MM-DD) is tried first: it is what the extraction
    prompts ask the LLM to produce, and dayfirst=True would misread it
    (2026-04-03 → 2026-03-04). Any other format is interpreted day-first,
    as in Italian usage (03/04/2026 → 3 April).
    """
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return parse_date(value, dayfirst=True, fuzzy=False)


# --- AI-POWERED AGENTS ---
# These agents inherit from OpenAIClientMixin and declare a model_tier.


class DataExtractorAgent(BaseAgent, OpenAIClientMixin):
    """
    AI agent that extracts structured data from the user's free text.

    Uses a generic prompt populated with the schema specific to the request
    type, making the agent flexible and scalable across workflow variants.
    A low-tier model is sufficient for JSON extraction tasks.
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
        """
        Executes the LLM call for data extraction.
        The task received from the orchestrator is already a fully formatted
        prompt; the user_prompt is left empty because all context is embedded
        in the system prompt.
        """
        self.logger.demo(
            f"🔎 [Data Extractor Agent (AI-{self.model_tier})] "
            f"Extracting structured information..."
        )

        success, output = self._call_llm(system_prompt=task, user_prompt="")

        if success:
            self.logger.demo(
                f"🔎 [Data Extractor Agent (AI-{self.model_tier})] "
                f"Data extracted successfully: {output}"
            )
            return True, output
        else:
            self.logger.demo(
                f"🔎 [Data Extractor Agent (AI-{self.model_tier})] "
                f"Data extraction failed."
            )
            return False, output


class SemanticEnrichmentAgent(BaseAgent, OpenAIClientMixin):
    """
    AI-powered agent that rewrites and enriches a short activity description,
    using the context embedded in the prompt to produce a more formal and
    professional text.

    The agent is field-agnostic: the specific text to enrich is injected into
    the prompt by the orchestrator before the agent is invoked.
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
        """
        Executes the LLM call for semantic enrichment.
        The task is the fully formatted prompt; user_prompt is empty because
        all information, including the text to enrich, is already in the
        system prompt.
        """
        self.logger.demo(
            f"✍️  [Semantic Enrichment Agent (AI-{self.model_tier})] "
            f"Enriching text..."
        )

        success, output = self._call_llm(
            system_prompt=task,
            user_prompt="",
            is_json=False,
        )

        if success:
            if output:
                self.logger.demo(
                    f"✍️  [Semantic Enrichment Agent (AI-{self.model_tier})] "
                    f"Enriched text generated."
                )
                return True, output
            else:
                self.logger.demo(
                    f"✍️  [Semantic Enrichment Agent (AI-{self.model_tier})] "
                    f"Enrichment produced empty text — proceeding."
                )
                return True, ""
        else:
            self.logger.demo(
                f"✍️  [Semantic Enrichment Agent (AI-{self.model_tier})] "
                f"Enrichment failed."
            )
            return False, output


class IterativeEnrichmentAgent(BaseAgent, OpenAIClientMixin):
    """
    AI-powered agent that iterates over a list of objects (e.g. timesheet
    periods) and enriches a specified text field in each item, if present.

    The task is a pipe-delimited string: 'list_key|text_key|doc_type|field_name'.
    The prompt template is loaded once at construction time from the
    'arricchimento_testo_formale' entry in the configuration's prompt_templates.
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
        # Load the prompt template once at construction time
        self.prompt_template = self.agent_config.get("prompt_templates", {}).get(
            "arricchimento_testo_formale", ""
        )

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"✍️  [Iterative Enrichment Agent (AI-{self.model_tier})] "
            f"Starting list enrichment..."
        )

        try:
            list_key, text_key, doc_type, field_name = task.split("|")
        except ValueError:
            self.logger.error(
                f"Invalid task format for IterativeEnrichmentAgent: '{task}'. "
                f"Expected format: 'list_key|text_key|doc_type|field_name'."
            )
            return False, {"failure_reason": f"Malformed YAML task format: {task}"}

        original_list = current_state.get_data_field(list_key, [])
        enriched_list = []

        for item in original_list:
            text_to_enrich = item.get(text_key)
            modified_item = item.copy()

            if text_to_enrich:
                self.logger.demo(f"  -> Enriching: '{text_to_enrich}'...")

                # Populate the prompt via str.replace() to avoid the substring
                # trap: str.format() would raise KeyError on any unrecognised
                # placeholder and could silently corrupt the prompt if the
                # template is later extended.
                specific_prompt = self.prompt_template.replace(
                    "{testo_originale}", str(text_to_enrich)
                )

                # Defensive guard: unresolved placeholders signal a mismatch
                # between the YAML template and the code.
                if re.search(r'\{[^}]+\}', specific_prompt):
                    self.logger.warning(
                        "[IterativeEnrichmentAgent] The template contains "
                        "unresolved placeholders — the prompt may be malformed."
                    )

                success, output = self._call_llm(
                    system_prompt=specific_prompt, user_prompt="", is_json=False
                )

                if not success:
                    # Keeping the original text silently would produce a
                    # timesheet that looks enriched but is not.
                    return False, {
                        "failure_reason": (
                            f"Enrichment failed for item '{text_to_enrich}': "
                            f"{output.get('failure_reason') if isinstance(output, dict) else output}"
                        )
                    }
                modified_item[text_key] = output

            enriched_list.append(modified_item)

        self.logger.demo(
            "✍️  [Iterative Enrichment Agent] List processing complete."
        )
        return True, {list_key: enriched_list}


# --- RULE-BASED AGENTS ---
# These agents use pure Python logic and do not inherit from OpenAIClientMixin.


class FormalValidatorAgent(BaseAgent):
    """
    Rule-based agent that validates the presence and type of required fields.

    Deliberately avoids AI to guarantee reliability and predictability.
    Produces a list of pending questions for any field that is missing or
    has an incorrect type, which are then forwarded to HumanInputAgent.

    Output dict keys:
    - 'success' (bool): True if all required fields are valid.
    - 'pending_questions' (list): question dicts with 'key' and 'question'
      fields, consumed by HumanInputAgent.
    """

    def __init__(self, agent_config: dict = None, logger: logging.Logger = None):
        super().__init__(agent_config=agent_config, logger=logger)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "🧐 [Formal Validator Agent (Rules)] Validating collected data..."
        )

        request_type = current_state.get_request_type()
        collected_data = current_state.get_collected_data()

        schemas = current_state.get_validation_schemas()
        rules_to_apply = schemas.get(request_type, {})

        if not rules_to_apply:
            self.logger.demo(
                f"🧐 No validation rules found for type '{request_type}'. "
                f"Proceeding."
            )
            return True, {"success": True, "pending_questions": []}

        questions_to_ask = []
        for field, rule in rules_to_apply.items():
            value = collected_data.get(field)

            # Presence check: shared definition, see utils.is_missing_value.
            is_missing = is_missing_value(value)
            if rule.get("required", False) and is_missing:
                question_text = rule.get(
                    "question",
                    f"Required field '{field}' is missing.",
                )
                questions_to_ask.append({"key": field, "question": question_text})
                continue

            if not value:
                continue

            # Type check
            expected_type = rule.get("type")
            is_valid = True
            if expected_type == "int":
                try:
                    int(value)
                except (ValueError, TypeError):
                    is_valid = False
            elif expected_type == "float":
                try:
                    float(value)
                except (ValueError, TypeError):
                    is_valid = False
            elif expected_type == "date":
                try:
                    from dateutil.parser import parse
                    parse(value, fuzzy=False)
                except (ValueError, TypeError, ImportError):
                    is_valid = False

            if not is_valid:
                questions_to_ask.append(
                    {
                        "key": field,
                        "question": (
                            f"The value '{value}' for '{field}' is not of "
                            f"the expected type ('{expected_type}')."
                        ),
                    }
                )

        success = not bool(questions_to_ask)
        if not success:
            self.logger.demo(
                f"🧐 Validation failed. Questions for the user: "
                f"{questions_to_ask}"
            )
        else:
            self.logger.demo(
                f"🧐 Validation passed for request type '{request_type}'."
            )

        return True, {"success": success, "pending_questions": questions_to_ask}


# Recognised yes/no forms for boolean fields, compared after strip() and lower().
# Italian forms are included as localisation examples. Anything outside both
# sets is treated as missing, never silently as "no".
_BOOL_TRUE = {"true", "s", "si", "sì", "vero", "1", "on", "y", "yes"}
_BOOL_FALSE = {"false", "n", "no", "falso", "0", "off"}

class DataNormalizerAgent(BaseAgent):
    """
    Rule-based agent that cleans and standardises collected data by reading
    normalisation directives from the active validation schema.

    Handles the following normalisation types:
    - Null coercion: string 'null' (case-insensitive) → Python None
    - Whitespace trimming: applied to all string values
    - Date formatting: parsed via dateutil and formatted as YYYY-MM-DD
    - titlecase / uppercase: applied when declared in the schema
    - Boolean coercion: maps common affirmative strings to True/False
      (includes Italian affirmatives 'si', 'vero' as localisation examples)
    """

    def __init__(self, agent_config: dict = None, logger: logging.Logger = None):
        super().__init__(agent_config=agent_config, logger=logger)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "🧼 [Data Normalizer Agent (Rules)] Normalising data..."
        )

        collected_data = current_state.get_collected_data()
        schemas = current_state.get_validation_schemas()
        request_type = current_state.get_request_type()

        schema_to_use = schemas.get(request_type, {})
        normalised_data = collected_data.copy()

        for key, value in normalised_data.items():
            # Null coercion: convert string 'null' to Python None
            if isinstance(value, str) and value.strip().lower() == "null":
                normalised_data[key] = None
                self.logger.demo(
                    f"  -> Normalised '{key}': string 'null' → None."
                )
                continue

            # Skip non-string or empty values
            if not isinstance(value, str) or not value:
                continue

            # Step 1: always strip leading/trailing whitespace
            clean_value = value.strip()
            modified = clean_value != value

            # Step 2: schema-driven normalisation
            if key in schema_to_use:
                rule = schema_to_use[key]
                normalisation_type = rule.get("normalization")

                original_value_for_log = clean_value

                if rule.get("type") == "date":
                    try:
                        clean_value = _parse_date_it(clean_value).strftime("%Y-%m-%d")
                        modified = True
                    except (ValueError, TypeError):
                        self.logger.demo(
                            f"  ⚠️ Could not normalise date for '{key}': "
                            f"value '{clean_value}' not recognised."
                        )

                elif normalisation_type == "titlecase":
                    clean_value = clean_value.title()
                    modified = True

                elif normalisation_type == "uppercase":
                    clean_value = clean_value.upper()
                    modified = True

                elif rule.get("type") == "bool":
                    val_lower = clean_value.lower()
                    if val_lower in _BOOL_TRUE:
                        clean_value = True
                    elif val_lower in _BOOL_FALSE:
                        clean_value = False
                    else:
                        # Neither yes nor no: leave the field missing so the
                        # formal validator asks the question again.
                        clean_value = None
                        self.logger.demo(
                            f"  ⚠️ Could not interpret '{key}' as yes/no: "
                            f"value '{original_value_for_log}' left missing."
                        )
                    modified = True

                if modified and original_value_for_log != clean_value:
                    self.logger.demo(
                        f"  -> Normalised '{key}': "
                        f"'{original_value_for_log}' → '{clean_value}'"
                    )

            normalised_data[key] = clean_value

        return True, normalised_data


class BudgetValidatorAgent(BaseAgent):
    """
    Rule-based agent that simulates a budget check against an in-memory
    project database and retrieves supplementary project metadata
    (mandatory notice text, CUP code) if the request is approved.
    A project absent from the database is rejected, never given a default
    budget.

    The project database is intentionally hardcoded as a self-contained
    demo fixture; production deployments should replace it with a call
    to the institutional ERP or financial management system.
    """

    def __init__(self, agent_config: dict = None, logger: logging.Logger = None):
        super().__init__(agent_config=agent_config, logger=logger)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "💰 [Budget Validator Agent (Rules)] "
            "Checking budget coverage and project data..."
        )

        cost_str = current_state.get_data_field("costo_stimato", "0")
        project = current_state.get_data_field("progetto", "")

        try:
            cost = float(cost_str)
        except (ValueError, TypeError):
            # A cost that is not a number cannot be checked against a budget.
            return False, {
                "failure_reason": f"Estimated cost '{cost_str}' is not a number."
            }

        # --- DEMO PROJECT DATABASE ---
        project_database = {
            "PRIN2024-02": {
                "budget": 15000.0,
                "cup": "J34E24001230001",
                "dicitura_obbligatoria": (
                    "Acquisto effettuato con i fondi del progetto "
                    "PRIN 2024-02 - G.A. 12345."
                ),
            },
            "MONITOR-2025": {
                "budget": 5000.0,
                "cup": None,
                "dicitura_obbligatoria": None,
            },
        }

        # --- BUDGET CHECK LOGIC ---

        # 1. Retrieve the full project information object. An unknown project
        #    is rejected: before 1.0.2 it fell back to a default budget, so
        #    any invented project code was approved up to that amount.
        project_info = project_database.get(project)
        if project_info is None:
            reason = (
                f"Project '{project}' not found in the project register: "
                f"budget coverage cannot be verified."
            )
            self.logger.demo(
                f"💰 [Budget Validator Agent (Rules)] REJECTED: {reason}"
            )
            return True, {"esito": "RESPINTA", "motivazione": reason}

        # 2. Extract individual fields
        available_budget = project_info.get("budget", 0.0)
        mandatory_notice = project_info.get("dicitura_obbligatoria")
        project_cup = project_info.get("cup")

        # 3. Budget comparison
        if cost > available_budget:
            reason = (
                f"Estimated cost ({cost}€) exceeds the available budget "
                f"({available_budget}€) for project '{project}'."
            )
            self.logger.demo(
                f"💰 [Budget Validator Agent (Rules)] REJECTED: {reason}"
            )
            return True, {"esito": "RESPINTA", "motivazione": reason}

        # 4. Approved: return enriched output with project metadata
        self.logger.demo(
            "💰 [Budget Validator Agent (Rules)] APPROVED: "
            "Sufficient budget coverage."
        )
        if mandatory_notice:
            self.logger.demo(
                f"  -> Mandatory notice found for project '{project}'."
            )
        if project_cup:
            self.logger.demo(
                f"  -> CUP found for project '{project}': {project_cup}."
            )

        enriched_output = {
            "esito": "APPROVATA",
            "motivazione": "Copertura finanziaria verificata.",
            "dicitura_obbligatoria": mandatory_notice,
            "cup": project_cup,
        }

        return True, enriched_output


class ProcurementDecisionAgent(BaseAgent):
    """
    Rule-based agent that determines the procurement procedure by comparing
    the estimated cost with a threshold read from the configuration.

    Everything that depends on regulation is configuration, under
    config['business_rules']['acquisti']:
    - 'soglia_procedura_semplificata': the threshold;
    - 'procedura_sotto_soglia' / 'procedura_sopra_soglia': the fields of the
      procedure applied below and at/above it (procedure name, legal
      references, purchasing method).
    Missing rules are an authoring error: the agent fails instead of falling
    back to defaults. Administrative constants (RUP name, section, etc.) are
    merged into the output from config['administrative_constants'].
    """

    _REQUIRED_RULES = (
        "soglia_procedura_semplificata",
        "procedura_sotto_soglia",
        "procedura_sopra_soglia",
    )

    def __init__(self, agent_config: dict = None, logger: logging.Logger = None):
        super().__init__(agent_config=agent_config, logger=logger)

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "⚖️  [Procurement Decision Agent (Rules)] "
            "Determining procurement procedure..."
        )

        rules = self.agent_config.get("business_rules", {}).get("acquisti", {})
        missing = [key for key in self._REQUIRED_RULES if key not in rules]
        if missing:
            return False, {
                "failure_reason": (
                    f"Missing procurement rules in business_rules.acquisti: "
                    f"{missing}"
                )
            }

        cost_str = current_state.get_data_field("costo_stimato", "0")
        try:
            cost = float(cost_str)
        except (ValueError, TypeError):
            return False, {
                "failure_reason": f"Estimated cost '{cost_str}' is not a number."
            }

        threshold = rules["soglia_procedura_semplificata"]
        if cost < threshold:
            self.logger.demo(
                f"  -> Cost ({cost}€) below threshold ({threshold}€)."
            )
            procedure = rules["procedura_sotto_soglia"]
        else:
            self.logger.demo(
                f"  -> Cost ({cost}€) at or above threshold ({threshold}€)."
            )
            procedure = rules["procedura_sopra_soglia"]

        output_data = {**procedure, "importo_soglia": threshold}

        # Merge administrative constants into the output
        constants = self.agent_config.get("administrative_constants", {})
        output_data.update(constants)

        return True, output_data


class CompilerAgent(BaseAgent):
    """
    Rule-based agent that fills a JSON output template with values from the
    collected data, producing a structured document ready for export.

    The template name is specified in the task dict under 'use_template'.
    Templates are retrieved from the 'output_templates' section of the state.
    """

    def __init__(self, agent_config: dict = None, logger: logging.Logger = None):
        super().__init__(agent_config=agent_config, logger=logger)

    def run(self, task: dict, current_state: any) -> tuple[bool, any]:
        template_name = task.get("use_template")
        self.logger.demo(
            f"✍️  [Compiler Agent (Rules)] "
            f"Filling template '{template_name}'..."
        )

        try:
            state_dict = current_state.as_dict()
            all_templates = state_dict.get("output_templates", {})
            template_to_use = all_templates.get(template_name, {})

            data = state_dict.get("collected_data", {})

            output = fill_template_recursive(template_to_use, data)

            self.logger.demo("✍️  [Compiler Agent (Rules)] Template filled.")
            return True, output
        except Exception as e:
            return False, {"failure_reason": str(e)}


class IterativeCompilerAgent(BaseAgent):
    """
    Rule-based agent that iterates over a list of data items and fills one
    output template per item.

    Before filling, common top-level fields (e.g. requester name, project)
    are merged with the item-specific fields so that the compiled output
    for each item is self-contained.

    The current output schema is read from the dynamic state key
    'current_output_schema', which must be set by a preceding YAML
    aggiorna_stato / update_state rule before this agent is activated.
    """

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            f"⚙️  [Iterative Compiler Agent] "
            f"Batch compilation for list key '{task}'..."
        )

        full_collected_data = current_state.get_collected_data()
        data_list = full_collected_data.get(task)

        if not isinstance(data_list, list):
            self.logger.error(
                f"IterativeCompilerAgent expected a list at key '{task}', "
                f"but found {type(data_list)}."
            )
            return False, {"failure_reason": "Invalid input data for iterative compiler."}

        template = current_state.as_dict().get("current_output_schema", {})
        if not template:
            self.logger.error(
                "Template not found at 'current_output_schema'. "
                "Cannot compile."
            )
            return False, {"failure_reason": "Compilation template missing."}

        final_outputs = []

        # Extract top-level (non-list) fields shared across all items
        common_data = {
            k: v
            for k, v in full_collected_data.items()
            if not isinstance(v, list)
        }

        for item_data in data_list:
            # Merge common fields with item-specific fields
            combined_data = {**common_data, **item_data}
            compiled_output = fill_template_recursive(template, combined_data)
            final_outputs.append(compiled_output)

        self.logger.demo(
            f"⚙️  [Iterative Compiler Agent] "
            f"Generated {len(final_outputs)} compiled item(s)."
        )
        return True, final_outputs


class OutputCombinerAgent(BaseAgent):
    """
    Rule-based agent that collects partial JSON outputs stored in the
    collected_data dict (json_missione, json_timesheet) and combines them
    into a single final output.

    If only one partial output is present, it is returned directly rather
    than wrapped in a list, to avoid unnecessary nesting.
    """

    def run(self, task: str, current_state: any) -> tuple[bool, any]:
        self.logger.demo(
            "🧩 [Output Combiner Agent] Combining partial outputs..."
        )

        data = current_state.get_collected_data()
        combined_output = []

        if "json_missione" in data:
            combined_output.append(data["json_missione"])
        if "json_timesheet" in data:
            combined_output.append(data["json_timesheet"])

        if len(combined_output) == 1:
            self.logger.demo("  -> Single output found. Finalised.")
            return True, combined_output[0]

        self.logger.demo(
            f"  -> {len(combined_output)} outputs found. Finalised as list."
        )
        return True, combined_output


# --- AGENT FACTORY ---


def get_agent_instance(
    agent_name: str, config: dict = None, logger: logging.Logger = None
) -> BaseAgent:
    """
    Factory function that creates and returns an instance of the requested
    administrative agent.

    Delegates model resolution and instantiation to create_agent_instance
    from core_framework, which handles the AI-powered / rule-based split.

    Raises ValueError if the requested agent name is not registered.
    """
    config = config or {}

    available_agents = {
        "data_extractor_agent": DataExtractorAgent,
        "formal_validator_agent": FormalValidatorAgent,
        "budget_validator_agent": BudgetValidatorAgent,
        "semantic_enrichment_agent": SemanticEnrichmentAgent,
        "compiler_agent": CompilerAgent,
        "data_normalizer_agent": DataNormalizerAgent,
        "procurement_decision_agent": ProcurementDecisionAgent,
        "iterative_compiler_agent": IterativeCompilerAgent,
        "iterative_enrichment_agent": IterativeEnrichmentAgent,
        "output_combiner_agent": OutputCombinerAgent,
    }

    agent_class = available_agents.get(agent_name)
    if not agent_class:
        raise ValueError(
            f"Agent '{agent_name}' not found in administrative factory. "
            f"Available: {sorted(available_agents.keys())}"
        )

    local_logger = logger or logging.getLogger(__name__)
    return create_agent_instance(agent_class, agent_name, config, local_logger)