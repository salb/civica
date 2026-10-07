from __future__ import annotations
import copy
import logging
import re
import time
import traceback
from typing import Any

import yaml
from rich.markup import escape

from core_framework import get_utility_agent_instance as utility_agent_factory
from utils import is_missing_value, to_json_string


class WorkflowState:
    """
    Represents and manages the workflow state in a robust, centralised way.

    The internal state is divided into two distinct semantic levels:

    - Typed state: keys with semantics known at design time, protected by
      dedicated getter/setter methods (current_phase, request_type,
      final_output, collected_data, …). Attempting to write them via
      set_global_variable raises ValueError.

    - Dynamic state: keys defined in YAML workflows and not known to the
      Python code (e.g. extraction_schema_str, temp_input,
      current_output_schema). These must be written exclusively via
      set_global_variable, the official and traceable entry point for
      dynamic state writes.
    """

    # Keys with a dedicated setter: writing them via set_global_variable is an
    # error that would bypass hooks, logging and setter-level validation.
    # The guard converts the silent mistake into an explicit exception.
    _RESERVED_KEYS: frozenset[str] = frozenset({
        "current_phase",
        "request_type",
        "final_output",
        "collected_data",
        "pending_questions",
        "current_cycle",
        # Configuration keys — written once by set_configuration
        "business_rules",
        "prompt_templates",
        "output_templates",
        "validation_schemas",
    })

    def __init__(self, initial_state: dict[str, Any]):
        self._data = initial_state

    def set_configuration(self, config: dict):
        """Merges configuration sections into the state for unified access."""
        self._data["business_rules"] = config.get("business_rules", {})
        self._data["prompt_templates"] = config.get("prompt_templates", {})
        self._data["output_templates"] = config.get("output_templates", {})
        self._data["validation_schemas"] = config.get("validation_schemas", {})

    def as_dict(self) -> dict[str, Any]:
        return self._data

    def set_global_variable(self, key: str, value: Any) -> None:
        """
        Writes a dynamic key to the root state.

        Use exclusively for keys not listed in _RESERVED_KEYS — typically
        intermediate variables introduced by context_preparators or YAML
        workflow phases (e.g. extraction_schema_str, temp_input).

        Do NOT use for keys with a dedicated setter: each typed setter may
        contain additional logic (validation, side effects) that would be
        bypassed.

        Raises:
            ValueError: if key is a reserved key that has a dedicated setter.
        """
        if key in self._RESERVED_KEYS:
            raise ValueError(
                f"WorkflowState.set_global_variable: '{key}' is a reserved key "
                f"with a dedicated setter. Use the appropriate method instead "
                f"(e.g. set_phase, set_request_type, update_collected_data, …) "
                f"rather than set_global_variable. "
                f"Reserved keys: {sorted(self._RESERVED_KEYS)}"
            )
        self._data[key] = value

    # --- TYPED GETTERS AND SETTERS ---

    def get_phase(self) -> str | None:
        return self._data.get("current_phase")

    def set_phase(self, new_phase: str) -> None:
        self._data["current_phase"] = new_phase

    def get_collected_data(self) -> dict[str, Any]:
        return self._data.get("collected_data", {})

    def update_collected_data(self, new_data: dict[str, Any]) -> None:
        if not isinstance(self._data.get("collected_data"), dict):
            self._data["collected_data"] = {}
        self._data["collected_data"].update(new_data)

    def get_data_field(self, key: str, default: Any = None) -> Any:
        return self._data.get("collected_data", {}).get(key, default)

    def set_data_field(self, key: str, value: Any) -> None:
        if not isinstance(self._data.get("collected_data"), dict):
            self._data["collected_data"] = {}
        self._data["collected_data"][key] = value

    def get_request_type(self) -> str | None:
        return self._data.get("request_type")

    def set_request_type(self, request_type: str) -> None:
        self._data["request_type"] = request_type

    def get_final_output(self) -> Any:
        return self._data.get("final_output")

    def set_final_output(self, output: Any) -> None:
        self._data["final_output"] = output

    def get_pending_questions(self) -> list[dict[str, str]]:
        return self._data.get("pending_questions", [])

    def set_pending_questions(self, questions: list[dict[str, str]]) -> None:
        self._data["pending_questions"] = questions

    def get_user_request(self) -> str | None:
        return self._data.get("user_request")

    def get_current_cycle(self) -> int | None:
        return self._data.get("current_cycle")

    def set_current_cycle(self, cycle: int) -> None:
        self._data["current_cycle"] = cycle

    def get_validation_schemas(self) -> dict[str, Any]:
        return self._data.get("validation_schemas", {})


def create_composite_factory(primary_factory, logger):
    """
    Creates a composite factory that first tries the primary (workflow-specific)
    factory and falls back to the utility factory if the agent is not found.
    """

    def composite_factory(agent_name: str, config: dict, logger: logging.Logger):
        try:
            # Attempt to create the agent using the workflow-specific factory
            return primary_factory(agent_name, config, logger)
        except ValueError:
            # Fall back to the utility factory
            return utility_agent_factory(agent_name, config, logger)

    return composite_factory


class AdvancedOrchestrator:
    def __init__(self, config_path, agent_factory, main_config=None):
        with open(config_path, encoding="utf-8") as f:
            workflow_config = yaml.safe_load(f)

        self.config = copy.deepcopy(main_config) if main_config else {}

        # Intelligent merge: local workflow values override or extend the global config.
        # Dictionaries (e.g. ai_models, prompt_templates) are merged key-by-key;
        # all other types (lists, scalars) are fully replaced by the local value.
        for key, value in workflow_config.items():
            if isinstance(value, dict) and isinstance(self.config.get(key), dict):
                self.config[key].update(value)
            else:
                self.config[key] = value

        self.state = WorkflowState(copy.deepcopy(self.config.get("initial_state", {})))
        self.state.set_configuration(self.config)

        self.agent_factory = agent_factory
        self.router_rules = self.config.get("router", [])
        self.settings = self.config.get("settings", {})
        self.logger = logging.getLogger(__name__)

    def _get_value_from_path(self, path: str, agent_output: dict = None) -> Any:
        """
        Retrieves a value from a source (state or agent output) using a dot-separated
        path string, e.g. 'state.key1.key2'.
        """
        if not isinstance(path, str):
            return None

        parts = path.split(".")
        source_name = parts[0]

        obj = None
        if source_name == "state":
            obj = self.state.as_dict()
        elif source_name == "output":
            # If the path is exactly 'output', return the entire agent output object.
            if len(parts) == 1:
                return agent_output
            obj = agent_output
        else:
            return None

        path_parts = parts[1:]
        for key in path_parts:
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj

    def _resolve_placeholders_recursive(self, data: Any) -> Any:
        """
        Sole responsible for placeholder resolution.

        Recursively traverses a data structure and resolves '{...}' placeholders
        found in strings, preserving non-string types where necessary.

        - Case 1: the string IS exactly one placeholder → the resolved value is
          returned with its original Python type (list, dict, etc.).
        - Case 2: the string CONTAINS one or more placeholders embedded in text →
          all resolved values are cast to str and interpolated in place.
        """
        if isinstance(data, dict):
            return {k: self._resolve_placeholders_recursive(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._resolve_placeholders_recursive(item) for item in data]
        elif isinstance(data, str):

            # Case 1: the string is EXACTLY a single placeholder (e.g. "{state.key}")
            # [^{}]* forbids braces inside the path: without it, a string such
            # as "{state.a}-{state.b}" would fullmatch as ONE placeholder with
            # path "state.a}-{state.b" and silently resolve to None.
            full_match = re.fullmatch(r"\{([^{}]*)\}", data)
            if full_match:
                return self._get_value_from_path(full_match.group(1))

            # Case 2: the string CONTAINS one or more placeholders
            # (e.g. "file_{state.id}.txt")
            def repl(match):
                resolved_value = self._get_value_from_path(match.group(1))
                return str(resolved_value) if resolved_value is not None else ""

            return re.sub(r"\{(.*?)\}", repl, data)

        return data

    _SUPPORTED_FORMATS = frozenset({"json_string"})

    def _run_context_preparators(self):
        """Executes declarative context preparator rules defined in the config."""
        preparator_rules = self.config.get("context_preparators", [])
        for rule in preparator_rules:
            # Guards: a malformed rule is a YAML authoring error.
            if "assign" not in rule:
                raise ValueError(
                    f"Malformed 'context_preparators' rule: only 'assign' "
                    f"is supported. Rule: {rule}"
                )
            assignment_rule = rule["assign"]
            for key in ("from", "to"):
                if key not in assignment_rule:
                    raise ValueError(
                        f"Malformed 'context_preparators' rule: missing key "
                        f"'{key}'. Rule: {rule}"
                    )
            value_format = assignment_rule.get("format")
            if value_format is not None and value_format not in self._SUPPORTED_FORMATS:
                raise ValueError(
                    f"Malformed 'context_preparators' rule: unknown format "
                    f"'{value_format}'. Supported: {sorted(self._SUPPORTED_FORMATS)}. "
                    f"Rule: {rule}"
                )

            value_to_assign = self._get_value_from_path(assignment_rule["from"])

            if value_format == "json_string":
                value_to_assign = to_json_string(value_to_assign)

            # Write the value using the safe assignment method
            self._execute_assign_action(
                {"to": assignment_rule["to"], "value": value_to_assign}
            )

    _SUPPORTED_OPERATORS = frozenset({"equals", "not_equals", "in", "exists"})

    def _evaluate_activation_rules(
        self, rules: list, agent_output: dict = None
    ) -> bool:
        """
        Evaluates a list of activation conditions against the current state
        (or the agent output). Returns True only if ALL conditions are met.

        Supported operators: equals, not_equals, in, exists.
        """
        if not isinstance(rules, list):
            self.logger.error(
                "'activate_if' or 'if' value is not a list — check YAML format."
            )
            return False
        for rule in rules:
            # Guards: a malformed condition is a YAML authoring error.
            # Without them, an unknown operator would match no clause below
            # and the condition would silently evaluate to True.
            if "field" not in rule:
                raise ValueError(
                    f"Malformed 'activate_if'/'if' condition: missing key "
                    f"'field'. Rule: {rule}"
                )
            operator = rule.get("operator", "equals")
            if operator not in self._SUPPORTED_OPERATORS:
                raise ValueError(
                    f"Malformed 'activate_if'/'if' condition: unknown operator "
                    f"'{operator}'. Supported: {sorted(self._SUPPORTED_OPERATORS)}. "
                    f"Rule: {rule}"
                )
            field_value = self._get_value_from_path(rule["field"], agent_output)
            expected_value = rule.get("value")
            if (
                operator == "equals" and field_value != expected_value
                or operator == "in" and field_value not in expected_value
                or operator == "not_equals" and field_value == expected_value
                or operator == "exists" and is_missing_value(field_value)
                                        ):
                return False
        return True

    def _resolve_task_input(self, task_rule: dict) -> Any:
        """
        Resolves a task rule into a concrete value in two distinct phases:

        Phase 1 — Resolution: all parameter values are retrieved from the state
        and collected into an intermediate dictionary. The template string is not
        touched yet.

        Phase 2 — Atomic substitution: a single re.sub call with a callable
        replaces all placeholders in one pass. This guarantees that substituted
        values are treated as opaque text and are never re-processed, eliminating
        the 'substring trap' (a resolved value containing literal '{B}' cannot
        accidentally trigger a second substitution of parameter B).
        """
        # Case 1: the task is a text prompt to be assembled from a template
        if isinstance(task_rule, dict) and "template" in task_rule:
            template_name = task_rule.get("template")
            if not template_name:
                return ""

            all_templates = self.state.as_dict().get("prompt_templates", {})
            template_prompt = all_templates.get(template_name)
            if not template_prompt:
                self.logger.error(f"Prompt template '{template_name}' not found.")
                return ""

            prompt_draft = template_prompt

            # PHASE 1: resolve ALL parameter values before touching the template.
            # Separating resolution from substitution is essential to avoid the
            # 'substring trap': if the value of parameter A contains the literal
            # string '{B}' and B is also a parameter, a sequential .replace()
            # loop would substitute {B} inside the already-inserted value of A,
            # silently corrupting the prompt.
            parameters = task_rule.get("parameters", {})
            resolved_params: dict[str, str] = {}

            for param_name, param_config in parameters.items():
                value_path = (
                    param_config
                    if isinstance(param_config, str)
                    else param_config.get("path")
                )

                # Guard A: path not configured in YAML (key "path" missing)
                if value_path is None:
                    self.logger.error(
                        f"_resolve_task_input: parameter '{param_name}' has no "
                        f"'path' configured. Check the YAML. "
                        f"The placeholder will be replaced with an empty string."
                    )
                    value = None
                else:
                    value = self._get_value_from_path(value_path)
                    # Guard B: path configured but not resolved in the state
                    if value is None:
                        self.logger.warning(
                            f"_resolve_task_input: parameter '{param_name}' "
                            f"(path: '{value_path}') resolved to None. "
                            f"Field missing or path incorrect. "
                            f"The placeholder will be replaced with an empty string."
                        )

                if isinstance(param_config, dict) and param_config.get("format") == "json_string":
                    value = to_json_string(value)

                # str(None) → "None": use "" to avoid artefacts in the prompt
                resolved_params[param_name] = str(value) if value is not None else ""

            # PHASE 2: atomic substitution in a single pass via re.sub + callable.
            # re.sub with a function never re-processes substitution strings:
            # values are inserted into the final result as opaque text,
            # regardless of any '{...}' they may contain.
            if resolved_params:
                _param_pattern = re.compile(
                    r"\{(" + "|".join(re.escape(k) for k in resolved_params) + r")\}"
                )
                prompt_draft = _param_pattern.sub(
                    lambda m: resolved_params[m.group(1)], prompt_draft
                )

            # Safely append large state content if specified
            if "append_from_state" in task_rule:
                content_path = task_rule["append_from_state"]
                content_to_append = self._get_value_from_path(content_path)
                prompt_draft += "\n\n" + str(
                    content_to_append if content_to_append is not None else ""
                )

            return prompt_draft

        # Case 2: the task is a direct instruction dictionary
        return task_rule

    def _execute_assign_action(
        self, assignment_rule: dict, agent_output: dict = None
    ):
        """
        Executes a single assignment action on the workflow state.

        Handles the full destination namespace:
        - state.current_phase, state.request_type, … → dedicated typed setters
        - state.collected_data → merges a dict via update_collected_data
        - state.collected_data.<key> → writes a single nested key via set_data_field
        - state.<dynamic_key> → writes an intermediate variable via set_global_variable
        """
        destination = assignment_rule.get("to")
        if not destination:
            raise ValueError(
                f"Malformed 'assign' action: missing key 'to'. "
                f"Rule: {assignment_rule}"
            )

        value_to_assign = None
        if "value" in assignment_rule:
            value_to_assign = assignment_rule["value"]
        elif "from" in assignment_rule:
            value_to_assign = self._get_value_from_path(
                assignment_rule["from"], agent_output
            )
        else:
            raise ValueError(
                f"Malformed 'assign' action: missing 'value' or 'from'. "
                f"Rule: {assignment_rule}"
            )

        destination_parts = destination.split(".")

        # --- ASSIGNMENT LOGIC ---

        # 1. Reserved keys: routed to their dedicated typed setters
        if destination == "state.current_phase":
            self.state.set_phase(value_to_assign)
        elif destination == "state.request_type":
            self.state.set_request_type(value_to_assign)
        elif destination == "state.final_output":
            self.state.set_final_output(value_to_assign)
        elif destination == "state.pending_questions":
            self.state.set_pending_questions(value_to_assign)
        elif destination == "state.collected_data":
            if isinstance(value_to_assign, dict):
                self.state.update_collected_data(value_to_assign)
            else:
                self.logger.error(
                    f"Cannot update collected_data with a non-dict value. "
                    f"Value: {value_to_assign}"
                )
        elif (
            len(destination_parts) == 3
            and destination_parts[0] == "state"
            and destination_parts[1] == "collected_data"
        ):
            # state.collected_data.<nested_key>
            nested_key = destination_parts[2]
            self.state.set_data_field(nested_key, value_to_assign)

        # 2. Dynamic root-level state keys (e.g. intermediate variables introduced
        #    by context_preparators or YAML workflow phases such as
        #    extraction_schema_str, temp_input, current_output_schema).
        #    set_global_variable is the official channel: it preserves
        #    WorkflowState encapsulation and raises ValueError if a reserved key
        #    with a dedicated setter is accidentally targeted.
        elif len(destination_parts) == 2 and destination_parts[0] == "state":
            key = destination_parts[1]
            self.state.set_global_variable(key, value_to_assign)
            self.logger.debug(
                f"Assigned value to dynamic state key '{key}'."
            )

        else:
            raise ValueError(
                f"Malformed 'assign' action: unrecognised destination "
                f"'{destination}'. Rule: {assignment_rule}"
            )

    def _execute_state_updates(self, action_list: list, agent_output: dict):
        """
        Iterates over a list of state-update actions parsed from the YAML router.

        Supported action types:
        - assign: direct key assignment via _execute_assign_action
        - if/then/else: conditional branching based on state or output values
        """
        for action in action_list:
            if "assign" in action:
                self._execute_assign_action(action["assign"], agent_output)
            elif "if" in action:
                condition_met = self._evaluate_activation_rules(
                    action["if"], agent_output
                )
                if condition_met and "then" in action:
                    self._execute_state_updates(action["then"], agent_output)
                elif not condition_met and "else" in action:
                    self._execute_state_updates(action["else"], agent_output)

    def run_iterative_workflow(self):
        """
        Main execution loop of the orchestrator.

        Iterates up to max_cycles times. At each cycle:
        1. Evaluates context preparators.
        2. Asks the router which agents to activate.
        3. Executes the selected agents sequentially.
        4. Updates the state based on each agent's output.
        5. Stops when final_output is set or no agents are activated.
        """
        max_cycles = self.settings.get("max_cycles", 20)

        self.logger.demo("--- INITIAL USER REQUEST ---")
        self.logger.demo(f'🗣️  "{self.state.get_user_request()}"')
        self.logger.demo("----------------------------\n")

        stop_reason = None
        for i in range(max_cycles):
            self.state.set_current_cycle(i)

            self.logger.demo(f"\n[bold]--- CYCLE {i+1}/{max_cycles} ---[/bold]")
            self.logger.debug(
                f"CURRENT STATE: phase='{self.state.get_phase()}', "
                f"request_type='{self.state.get_request_type()}'"
            )

            if self.state.get_final_output():
                self.logger.demo("✅ Final output produced. Workflow complete.")
                break

            self._run_context_preparators()

            agents_to_run = []
            for rule in self.router_rules:
                if "activate_if" in rule and self._evaluate_activation_rules(
                    rule["activate_if"]
                ):
                    agents_to_run.append(rule)

            self.logger.demo(
                f"🧠 [blue]Router[/blue] activated "
                f"[bold yellow]{len(agents_to_run)}[/bold yellow] agent(s)."
            )
            if not agents_to_run:
                self.logger.demo(
                    "No agents activated. The workflow may be blocked or complete."
                )
                stop_reason = "no_agent_activated"
                break

            # Respect the max_parallel_agents setting (guards against null in YAML)
            agent_limit = self.settings.get("max_parallel_agents") or 1
            selected_agents = agents_to_run[:agent_limit]

            for active_rule in selected_agents:
                agent_instance = self.agent_factory(
                    active_rule["agent"], self.config, logger=self.logger
                )

                # Task resolution — two-phase strategy, conditioned on task type.
                #
                # Phase 1 (_resolve_task_input) is always applied and is the
                # authoritative resolution mechanism for template-based tasks.
                # It guarantees atomic substitution: resolved parameter values are
                # treated as opaque text and never re-processed, eliminating the
                # substring trap.
                #
                # Phase 2 (_resolve_placeholders_recursive) is applied ONLY for
                # non-template tasks, where the task content is developer-authored
                # YAML (e.g. direct {state.X} references, filename strings with
                # embedded placeholders). In that context all {state.X} patterns
                # are intentional and safe to resolve.
                #
                # Rationale for the exclusion of Phase 2 from template tasks:
                # _resolve_task_input already produces a fully assembled prompt.
                # Applying _resolve_placeholders_recursive on top of it would
                # reintroduce exactly the substring trap that Phase 1 eliminates:
                # LLM-generated text or user input that accidentally contains
                # {state.X} patterns would be silently resolved, corrupting the
                # prompt without any error signal.
                #
                # Precondition for non-template tasks: values retrieved from state
                # via direct {state.X} references are assumed to originate from the
                # runner (not from LLM output) and to contain no further placeholders.
                task_rule = active_rule["task"]
 
                if isinstance(task_rule, dict) and "template" in task_rule:
                    # Template task: Phase 1 only.
                    # _resolve_task_input handles parameter resolution and
                    # append_from_state. Phase 2 is deliberately omitted.
                    task_input = self._resolve_task_input(task_rule)
                else:
                    # Non-template task: Phase 1 then Phase 2.
                    # Phase 2 resolves {state.X} placeholders embedded in
                    # developer-authored YAML values (direct state references,
                    # filename strings, task dicts without a template key).
                    raw_task_input = self._resolve_task_input(task_rule)
                    task_input = self._resolve_placeholders_recursive(raw_task_input)

                self.logger.demo(
                    f"  -> Activating '[bold green]{active_rule['agent']}[/bold green]' "
                    f"with task: '[dim]{escape(str(task_input)[:80])}...[/dim]'",
                    extra={"markup": True},                )
                self.logger.debug(
                    f"Activating agent '{active_rule['agent']}' "
                    f"with task: {str(task_input)}"
                )

                state_before = copy.deepcopy(self.state)
                start_time = time.time()

                # An agent may report failure by returning False, or fail by
                # raising. Both must take the same path: diagnosis, structured
                # log entry and failure envelope. Only the agent call is
                # guarded; configuration errors raised by the orchestrator
                # itself (malformed YAML in update_state) must stay loud.
                failure_reason = "agent_reported_failure"
                try:
                    success, output = agent_instance.run(task_input, self.state)
                except Exception as exc:
                    self.logger.exception(
                        f"🔥 Agent '{active_rule['agent']}' raised an exception."
                    )
                    success = False
                    failure_reason = "agent_exception"
                    output = {
                        "failure_reason": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }

                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000

                if success:
                    self._log_state_transition(
                        active_rule, True, output, state_before, duration_ms
                    )

                    if "update_state" in active_rule:
                        self._execute_state_updates(
                            active_rule["update_state"], output
                        )

                    self.logger.demo(
                        f"  <- State updated by '{active_rule['agent']}'."
                    )
                else:
                    self._log_state_transition(
                        active_rule, False, output, state_before, duration_ms
                    )
                    self.logger.error(
                        f"🔥 Failure reported by agent "
                        f"'{active_rule['agent']}'. Context: {output}"
                    )

                    # Build the error context for the Debugger Agent
                    error_context = {
                        "failed_agent": active_rule.get("agent"),
                        "cycle": i,
                        "task_input": task_input,
                        "error_output": output,
                        "state_at_failure": state_before.as_dict(),
                    }

                    # Instantiate and run the Debugger Agent
                    debugger = utility_agent_factory(
                        "debugger_agent", self.config, self.logger
                    )
                    debug_success, debug_analysis = debugger.run(
                        error_context, self.state
                    )

                    # Display the debugger's analysis
                    self.logger.demo("\n--- 🕵️ DEBUGGER ANALYSIS 🕵️ ---")
                    if debug_success:
                        self.logger.demo(
                            f"  ROOT CAUSE: "
                            f"{debug_analysis.get('analisi_causa_radice')}"
                        )
                        self.logger.demo(
                            f"  SUGGESTION: "
                            f"{debug_analysis.get('suggerimento_correzione')}"
                        )
                        self.logger.demo(
                            f"  IMPACT: "
                            f"{debug_analysis.get('impatto_fallimento')}"
                        )
                    else:
                        self.logger.demo("  Debugger Agent analysis failed.")
                    self.logger.demo("--------------------------------\n")

                    # Stop the workflow after the debug analysis.
                    # The failure is wrapped in an explicit envelope so that
                    # callers can tell it apart from a successful output.
                    self.state.set_final_output({
                        "status": "failed",
                        "reason": failure_reason,
                        "failed_agent": active_rule.get("agent"),
                        "error": output.get("failure_reason")
                        if isinstance(output, dict) else output,
                        "diagnosis": debug_analysis,
                    })
                    break

            if self.state.get_final_output():
                break
        else:
            # The for loop ran out of cycles without a break.
            stop_reason = "max_cycles_exhausted"

        # A workflow that stops without a final output has not completed:
        # it is reported as a failure, not returned as a message that a
        # caller could mistake for a result. The cause is known from the
        # rules alone, so no model is asked to diagnose it.
        if not self.state.get_final_output():
            self._set_termination_failure(stop_reason, max_cycles)

        return self.state.get_final_output()

    def _set_termination_failure(self, reason: str, max_cycles: int) -> None:
        """
        Wraps an anomalous termination (no agent activated, or cycle limit
        reached) in the same failure envelope used for agent failures, and
        emits a structured log entry so the run can be reconstructed.
        """
        messages = {
            "no_agent_activated": (
                "No router rule matched the current state: the workflow "
                "is blocked before producing a final output."
            ),
            "max_cycles_exhausted": (
                f"The cycle limit ({max_cycles}) was reached before a "
                f"final output was produced."
            ),
        }
        envelope = {
            "status": "failed",
            "reason": reason,
            "failed_agent": None,
            "error": messages[reason],
            "phase": self.state.get_phase(),
            "cycle": self.state.get_current_cycle(),
        }
        self.logger.error(f"❌ Workflow terminated: {messages[reason]}")
        self.logger.json_debug(
            "Workflow terminated without a final output.",
            extra={
                "cycle": self.state.get_current_cycle(),
                "event_type": "WORKFLOW_FAILED",
                "payload": envelope,
            },
        )
        self.state.set_final_output(envelope)


    def _log_state_transition(
        self, active_rule, success, output, state_before, duration_ms
    ):
        """
        Emits a structured JSON log entry for each agent execution.

        Static configuration keys (prompt_templates, output_templates, …) are
        excluded from the state snapshots to keep log entries compact.
        """
        static_keys = [
            "prompt_templates",
            "output_templates",
            "validation_schemas",
            "business_rules",
        ]
        loggable_state_before = {
            k: v
            for k, v in state_before.as_dict().items()
            if k not in static_keys
        }
        loggable_state_after = {
            k: v
            for k, v in self.state.as_dict().items()
            if k not in static_keys
        }
        extra_data = {
            "cycle": self.state.get_current_cycle(),
            "event_type": "AGENT_OUTPUT",
            "duration_ms": round(duration_ms, 2),
            "payload": {
                "agent": active_rule.get("agent", "N/A"),
                "success": success,
                "output": output,
            },
            "state_before": loggable_state_before,
            "state_after": loggable_state_after,
        }
        self.logger.json_debug("State transition completed.", extra=extra_data)