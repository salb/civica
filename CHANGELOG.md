# Changelog

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
