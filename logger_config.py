# logger_config.py
#
# Configures the centralised logging system for Civica.
#
# Three custom log levels are defined on top of the standard Python hierarchy:
#
#   JSON_DEBUG (5)  — full structured payloads for black-box debugging
#   DEMO      (25)  — human-readable operational trace for demos and development
#   USER_INFO (35)  — messages explicitly directed at the end user
#
# A single AppLogFilter instance is shared across all handlers to ensure that
# only Civica's own modules produce output, regardless of the active log level.

import datetime
import json
import logging
import os
import uuid

from rich.logging import RichHandler
from rich.markup import escape


# --- 1. Custom Level Definitions ---

DEMO_LEVEL_NUM = 25
logging.addLevelName(DEMO_LEVEL_NUM, "DEMO")

USER_INFO_LEVEL_NUM = 35
logging.addLevelName(USER_INFO_LEVEL_NUM, "USER_INFO")

JSON_DEBUG_LEVEL_NUM = 5
logging.addLevelName(JSON_DEBUG_LEVEL_NUM, "JSON_DEBUG")

# --- TRACE SWITCH ---
# The event log (*_events.jsonl) is always written: one line per structured
# event (agent execution, workflow failure), without state snapshots.
# The trace log (*_trace.jsonl) adds the full state before and after every
# agent execution. It is written by default, because it is what allows a run
# to be checked against the rules declared in the configuration. Set the
# environment variable CIVICA_TRACE_LOG to 0, false, off or no to disable it
# (for instance when inputs are large and the trace is not needed).
TRACE_LOG_ENV_VAR = "CIVICA_TRACE_LOG"


def trace_log_enabled() -> bool:
    value = os.environ.get(TRACE_LOG_ENV_VAR, "1").strip().lower()
    return value not in {"0", "false", "off", "no"}


def demo(self, message, *args, **kws):
    if self.isEnabledFor(DEMO_LEVEL_NUM):
        self._log(DEMO_LEVEL_NUM, message, args, **kws)


def user_info(self, message, *args, **kws):
    if self.isEnabledFor(USER_INFO_LEVEL_NUM):
        self._log(USER_INFO_LEVEL_NUM, message, args, **kws)


def json_debug(self, message, *args, **kws):
    if self.isEnabledFor(JSON_DEBUG_LEVEL_NUM):
        self._log(JSON_DEBUG_LEVEL_NUM, message, args, **kws)


logging.Logger.demo = demo
logging.Logger.user_info = user_info
logging.Logger.json_debug = json_debug


# --- 2. Application Log Filter ---

class AppLogFilter(logging.Filter):
    """
    Restricts log output to Civica's own modules, excluding third-party
    libraries (openai, httpx, urllib3, …) regardless of the active log level.

    A single instance is shared across all handlers to avoid redundant
    instantiation.
    """

    def __init__(self, name=""):
        super().__init__(name)
        self.allowed_loggers = [
            "__main__",
            "orchestrator",
            "agents_administrative_assistant",
            "agents_research_assistant",
            "core_framework",
            "logger_config",
        ]

    def filter(self, record):
        return any(record.name.startswith(name) for name in self.allowed_loggers)


# --- 3. Specialised JSON Formatters ---

class StructuredEventFilter(logging.Filter):
    """Lets through only structured events (records carrying an event_type)."""

    def filter(self, record):
        return hasattr(record, "event_type")


class MetricsJSONFormatter(logging.Formatter):
    """
    Compact formatter for structured events.

    Emits the lightweight fields (cycle, event_type, duration_ms) and, from
    the payload, the agent, its success flag and the failure reason, but no
    agent output and no state snapshot. Suitable for aggregating runs.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "source": record.name,
        }
        lightweight_keys = ["cycle", "event_type", "duration_ms"]
        for key in lightweight_keys:
            if hasattr(record, key):
                log_object[key] = getattr(record, key)
        payload = getattr(record, "payload", None)
        if isinstance(payload, dict):
            for key in ("agent", "failed_agent", "success", "reason"):
                if key in payload:
                    log_object[key] = payload[key]
        return json.dumps(log_object, ensure_ascii=False, default=str)


class VerboseJSONFormatter(logging.Formatter):
    """
    Verbose formatter for full black-box debugging.

    Emits all available structured fields including complete state snapshots
    (state_before, state_after) and agent output payloads.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "source": record.name,
        }
        all_keys = [
            "cycle",
            "event_type",
            "duration_ms",
            "payload",
            "state_before",
            "state_after",
        ]
        for key in all_keys:
            if hasattr(record, key):
                log_object[key] = getattr(record, key)
        return json.dumps(log_object, ensure_ascii=False, default=str)


# --- 4. Logging Setup ---

def setup_logging() -> str:
    """
    Initialises the centralised logging system and returns the run ID.

    Configures up to three handlers:
    - Console (Rich): DEMO level and above, text shown verbatim
      (Rich markup only on explicit opt-in).
    - Event file (*_events.jsonl): structured events only, compact format.
      Always written.
    - Trace file (*_trace.jsonl): every record from Civica's modules, with
      the full state before and after each agent execution. Written unless
      CIVICA_TRACE_LOG disables it.

    The AppLogFilter is instantiated once and shared across all handlers.
    """
    run_id = str(uuid.uuid4())[:8]

    # --- 1. Log directory and base filename ---
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_filename = f"{timestamp}_{run_id}_workflow"

    # The root level must let structured events (JSON_DEBUG) through: each
    # handler then decides what it keeps. Before 1.0.2 the root level was
    # DEMO, so the structured events never reached the files.
    root_logger = logging.getLogger()
    root_logger.setLevel(JSON_DEBUG_LEVEL_NUM)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # --- 2. Application filter (shared across all handlers) ---
    # Only Civica's own modules produce output on any channel, excluding
    # third-party libraries (openai, httpx, …).
    app_filter = AppLogFilter()

    # --- 3. Console handler (Rich) ---
    console_handler = RichHandler(
        rich_tracebacks=True,
        markup=False,
        log_time_format="[%X]",
    )
    console_handler.setLevel(DEMO_LEVEL_NUM)
    console_handler.addFilter(app_filter)
    root_logger.addHandler(console_handler)

    # --- 4. Event file handler (always on) ---
    events_log_path = os.path.join(log_dir, f"{base_filename}_events.jsonl")
    events_handler = logging.FileHandler(events_log_path, mode="a", encoding="utf-8")
    events_handler.setLevel(JSON_DEBUG_LEVEL_NUM)
    events_handler.setFormatter(MetricsJSONFormatter())
    events_handler.addFilter(app_filter)
    events_handler.addFilter(StructuredEventFilter())
    root_logger.addHandler(events_handler)

    # --- 5. Trace file handler (on unless disabled) ---
    trace_log_path = None
    if trace_log_enabled():
        trace_log_path = os.path.join(log_dir, f"{base_filename}_trace.jsonl")
        trace_handler = logging.FileHandler(trace_log_path, mode="a", encoding="utf-8")
        trace_handler.setLevel(JSON_DEBUG_LEVEL_NUM)
        trace_handler.setFormatter(VerboseJSONFormatter())
        trace_handler.addFilter(app_filter)
        root_logger.addHandler(trace_handler)

    # --- 6. Startup messages ---
    logger = logging.getLogger(__name__)
    logger.demo(
        f"Logging system [bold green]configured[/bold green]. "
        f"Run ID: [yellow]{run_id}[/yellow]",
        extra={"markup": True},
    )
    logger.demo(
        f"Event log saved to: [cyan]{escape(events_log_path)}[/cyan]",
        extra={"markup": True},
    )
    if trace_log_path:
        logger.demo(
            f"Trace log (state snapshots) saved to: "
            f"[cyan]{escape(trace_log_path)}[/cyan]",
            extra={"markup": True},
        )
    else:
        logger.demo(f"Trace log disabled by {TRACE_LOG_ENV_VAR}.")

    return run_id
