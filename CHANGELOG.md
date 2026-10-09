# Changelog

## 1.0.2 — 2026-10-09

### Fixed
- Structured events are written to the log by default. The root logger level was DEMO, so the `AGENT_OUTPUT` and `WORKFLOW_FAILED` events (emitted at JSON_DEBUG) never reached the files unless a constant was changed in the source.
- The state after an agent execution is recorded after the `update_state` rules. Previously it was recorded before them, so `state_after` equalled `state_before`.
- Malformed configuration that was logged and ignored now raises a `ValueError`: a prompt template that does not exist (the model received an empty prompt), a prompt parameter without `path`, an `if`/`activate_if` that is not a list, an unknown action in `update_state`, a router rule without `agent` or `activate_if`.
- An agent iterating over a list fails if one item fails, instead of producing a document with a gap: the response strategist (which inserted a placeholder reply and saved the letter as complete), the critique categoriser (which assigned the category `sconosciuta`) and the iterative timesheet enrichment (which kept the original text).
- Mission workflow: `timesheet_richiesto`, which decides a branch, is always asked to the user; a value returned by the extraction model is discarded. Extracted data are normalised before the first validation, as in the procurement workflow.
- Procurement workflow: a project absent from the demonstration budget table is rejected instead of receiving a default budget of 10,000 €. A cost that is not a number is a failure instead of being treated as 0.
- Console messages written by the program show their styles instead of literal tags (`[bold]`, `[blue]`), a side effect of the 1.0.0 fix that disabled markup by default. Values from users or models in those messages are escaped.

### Changed
- Logs: `*_events.jsonl` contains structured events only, with agent, success flag and failure reason; `*_trace.jsonl` (formerly `*_debug.jsonl`, off by default) contains the full state before and after each agent execution and is on by default. Set `CIVICA_TRACE_LOG=0` to disable it. The `GLOBAL_LOG_LEVEL` constant is removed.
- The legal references of the procurement procedures (law, article, purchasing method) moved from `ProcurementDecisionAgent` to `business_rules.acquisti` in `config_procurement.yaml`. Missing rules are a failure, with no default threshold.

### Tests
- 26 new tests (193 in total), on the structured log, malformed configuration, failures inside list-processing agents, the procurement paths other than the happy one (missing field and resumption, budget exceeded, unknown project, legal references from YAML), the mission timesheet flag and console styles. 22 of them fail on 1.0.1.

## 1.0.1 — 2026-10-07

### Fixed
- An exception raised by an agent no longer escapes the orchestrator and terminates the assistant. It now follows the same path as a reported failure: debugger diagnosis, structured log entry, failure envelope.
- A workflow that stops without a final output (no router rule matches the state, or the cycle limit is reached) now returns a failure envelope instead of a message string. Previously the administrative runner saved that string to a file labelled `output`, as if the run had completed.

### Changed
- The failure envelope has two new fields: `reason` (`agent_reported_failure`, `agent_exception`, `no_agent_activated`, `max_cycles_exhausted`) and `error`. Terminations also report `phase` and `cycle`; their `failed_agent` is `null` and they carry no `diagnosis`, since the cause is known from the rules.
- The research runner reports a failed workflow as an error instead of printing the envelope as a result.

### Tests
- Seven tests on the new failure paths (167 in total). Six of them fail on 1.0.0.

## 1.0.0 — 2026-10-05

First public release.
