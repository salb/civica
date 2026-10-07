# Civica

[![tests](https://github.com/salb/civica/actions/workflows/tests.yml/badge.svg)](https://github.com/salb/civica/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.14-blue)
![License](https://img.shields.io/badge/license-BSD--3--Clause-blue)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23162104.svg)](https://doi.org/10.5281/zenodo.23162104)

*Tecnologia che libera. Ricerca che evolve.* — Technology that frees. Research that evolves.

Civica is a YAML-driven orchestrator for hybrid symbolic–AI document workflows. A workflow is declared, not programmed: a YAML file describes which agents run, under which conditions, and how their output updates a shared state. Rule-based agents handle what must be deterministic (validation, normalisation, thresholds, form compilation); LLM-based agents handle what requires language (extraction from free text, enrichment, critique). When required information is missing, the workflow asks the user and resumes.

Civica was developed at the Istituto Nazionale di Geofisica e Vulcanologia (INGV) to reduce the administrative and editorial friction of public research work. It ships with six workflows from two domains: administrative procedures and research support.

---

## Why

Much of the work in a public research institution is document work: turning an informal request into a compliant form, checking it against rules, answering reviewers, comparing texts. These tasks combine parts that must be exact with parts that need judgement over language. Civica keeps the two separate and explicit:

- **Business logic lives in configuration.** Routing, prompts, validation schemas and output templates are YAML. Changing a procedure means editing a readable file, not the engine.
- **Determinism where it matters.** Anything that can be checked by a rule is checked by code, not delegated to the LLM.
- **The human stays in the loop.** Missing or unclear fields become questions to the user, not guesses.
- **Every run is traceable.** Each state transition is logged as structured JSON alongside a readable console trace.

---

## How it works

The orchestrator runs in cycles over a shared `WorkflowState`. At each cycle:

1. **Context preparators** copy (and optionally format) values within the state.
2. The **router** selects the agents whose `activate_if` conditions are all true.
3. Each selected agent receives a **task**: a fixed string, or a prompt template whose `{parameters}` are resolved from the state.
4. The agent's output is written back through **`update_state`** rules, optionally branched with `if` / `then` / `else`.

A fragment of the procurement workflow (`config/config_procurement.yaml`):

```yaml
router:
  - agent: data_extractor_agent
    activate_if: [{field: state.current_phase, value: 'data_extraction'}]
    task:
      template: estrazione_dati_acquisto_task
      parameters:
        richiesta_utente: state.user_request
    update_state:
      - {assign: {to: state.collected_data, from: output}}
      - {assign: {to: state.current_phase, value: 'data_normalization'}}

  - agent: formal_validator_agent
    activate_if: [{field: state.current_phase, value: 'data_validation'}]
    task: "richiesta_acquisto"
    update_state:
      - if: [{field: output.success, operator: equals, value: false}]
        then:
          - {assign: {to: state.pending_questions, from: output.pending_questions}}
          - {assign: {to: state.current_phase, value: 'awaiting_user_input'}}
        else:
          - {assign: {to: state.current_phase, value: 'procedure_decision'}}
```

The configuration language has four constructs: `activate_if`/`if` conditions (operators `equals`, `not_equals`, `in`, `exists`), `assign` rules (`value` or `from`), `context_preparators` (with an optional `json_string` format), and prompt `parameters`. Each workflow file also declares the sections it needs among `validation_schemas`, `prompt_templates`, `output_templates` and `settings` (e.g. `max_cycles`).

AI agents declare a model tier (`low`, `normal`, `high`), resolved to a concrete model through the `ai_models` map of the main configuration. Agents never name a model directly.

### Guarantees enforced by the core

The following properties are covered by the test suite, not only stated:

- **Malformed configuration stops the workflow.** An unknown operator, a missing key, or an unsupported format in `activate_if`, `assign` or `context_preparators` raises a `ValueError` instead of being silently ignored.
- **Reserved state keys are protected.** Configuration sections loaded into the state (e.g. `prompt_templates`) cannot be overwritten by `assign` rules.
- **Prompt substitution is atomic.** A parameter value is inserted as opaque text: if a user's text contains `{another_parameter}`, it reaches the LLM unchanged.
- **Runs are isolated.** Running two workflows in sequence does not leak configuration or state from one to the other.
- **Failures are explicit.** A workflow that does not complete returns an envelope with `status: failed` and a `reason`: the agent reported failure, the agent raised an exception, no router rule matched the state, or the cycle limit was reached. Agent failures also carry the failed agent and a `diagnosis` generated by the debugger; terminations are diagnosed from the rules alone, without a model call. The administrative runner saves the envelope to a file marked `FAILED`, never as a completed form.
- - **Untrusted text is shown verbatim.** User input, prompts and LLM output in the console log are never interpreted as formatting markup.

---

## Included workflows

| Assistant | Workflow | What it does |
|---|---|---|
| Administrative | Procurement request | Extracts data from an informal request, asks for missing fields, applies the simplified-procedure threshold, checks the project budget, compiles the request form. |
| Administrative | Mission request | Collects mission details through a dialogue with the user and compiles the mission form; optionally generates the corresponding timesheet entries. |
| Administrative | Timesheet | Turns a description of activities over time into formal timesheet entries. |
| Research | Peer-review support | Parses received review comments, categorises the critiques, and drafts a response strategy grounded in the manuscript. |
| Research | Simulated review | A critical reviewer and a constructive reviewer assess a Markdown draft; an editor merges them into a single report. |
| Research | Overlap analysis | Compares two texts and reports common elements, divergences, gaps and recommendations. |

**Localisation.** Code, comments and documentation are in English. Prompts, workflow identifiers and generated documents are in Italian, the working language of the institution for which the workflows were built. The Italian layer is confined to the YAML files and serves as a localisation example.

---

## Requirements

- Python 3.11 or later (tested on 3.11 and 3.14)
- An OpenAI API key, to run the workflows. **The test suite does not need one.**

## Installation

```bash
git clone https://github.com/salb/civica.git
cd civica
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[test]"
cp .env.example .env               # then add your key: OPENAI_API_KEY=...
```

## Usage

```bash
python run_administrative_assistant.py
python run_research_assistant.py
```

Each assistant asks for a request in natural language, classifies it into one of its workflows, and runs it. Generated documents are written to `output/`; structured event logs to `logs/`. Both folders are created on first run.

## Testing

```bash
pytest                                       # full suite
pytest --cov --cov-report=term-missing       # with coverage
```

The suite runs without network access and without an API key: every LLM call is replaced by a mock, and a guard in `tests/conftest.py` makes any test that attempts a real connection fail. Continuous integration runs the suite on Python 3.11 and 3.14 for every push.

The tests are organised in three layers:

- **Core contract.** Condition evaluation, `assign` destinations, context preparators, parameter substitution, reserved keys, configuration merging, console logging.
- **Rule-based agents.** Date normalisation (ISO and Italian formats), boolean answers, formal validation of required fields.
- **One end-to-end path per workflow.** The real orchestrator and YAML files, with mocked LLM responses, including malformed ones (missing keys, a string where a list is expected).

What the tests can verify is what reaches the LLM and what the system does with its answer, not the quality of the answer itself.

---

## Repository layout

```
.
├── orchestrator.py                     # state, router, condition evaluation, update rules
├── core_framework.py                   # base agent, LLM client mixin, utility agents, factory
├── agents_administrative_assistant.py  # agents for the administrative workflows
├── agents_research_assistant.py        # agents for the research workflows
├── run_administrative_assistant.py     # interactive entry point (administrative)
├── run_research_assistant.py           # interactive entry point (research)
├── logger_config.py                    # console and JSON logging
├── utils.py                            # shared helpers (placeholders, templates, presence checks)
├── config/                             # main configurations and one YAML file per workflow
├── tests/                              # pytest suite
├── pyproject.toml
├── .github/workflows/tests.yml         # CI on Python 3.11 and 3.14
├── .env.example                        # template for the API key
└── LICENSE
```

## Adding a workflow

1. Write a new YAML file in `config/` with its `validation_schemas`, `prompt_templates`, `output_templates` and `router`, reusing existing agents where possible.
2. Register it under `workflows` in the main configuration of the relevant assistant, and add its identifier to the triage prompt.
3. If a new agent is needed, subclass `BaseAgent` (adding `OpenAIClientMixin` for an LLM agent) and register it in the domain factory.
4. Add an end-to-end test with mocked LLM responses, following the existing workflow tests.

---

## Known limitations

- **Demonstration data.** The project budget table used by the procurement workflow and the administrative constants are fixtures. A production deployment would replace them with the institution's accounting and staff systems.
- **Triage outside the declarative layer.** Classification of the initial request into a workflow is done by the runners in Python, not declared in YAML.
- **Validation at run time.** Malformed configuration is detected when the faulty rule is first evaluated, not when the file is loaded. Static validation of the whole configuration is future work.
- **Unknown model tier.** An agent whose tier is missing from the `ai_models` map falls back to a default model instead of stopping the workflow.
- **Shallow configuration merge.** Workflow configurations are merged with the main configuration one level deep.
- **Single LLM provider.** The client mixin targets the OpenAI API.
- **Text-only form values.** Compiled forms render numbers as text, and missing optional values as `N/A`.
- **Dates with month names.** The normaliser recognises numeric dates (ISO and Italian formats); dates written with month names, such as "3 marzo 2026", are not normalised.

---

## Origin

Civica was not commissioned from a vendor. It was built from inside a public research institution by a researcher with management experience, as a self-directed reskilling path, and grew from a single script into the orchestrator described here. It is offered as a starting point: study it, take it apart, adapt it to your own procedures.

## Citation

If you use Civica, please cite:

> Barba, S. *Civica: a YAML-driven orchestrator for hybrid symbolic–AI document workflows.* SoftwareX (submitted).

A DOI for the archived release will be added here.

## License

Released under the BSD 3-Clause License. See [`LICENSE`](LICENSE).
