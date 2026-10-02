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


# --- 1. Custom Level Definitions ---

DEMO_LEVEL_NUM = 25
logging.addLevelName(DEMO_LEVEL_NUM, "DEMO")

USER_INFO_LEVEL_NUM = 35
logging.addLevelName(USER_INFO_LEVEL_NUM, "USER_INFO")

JSON_DEBUG_LEVEL_NUM = 5
logging.addLevelName(JSON_DEBUG_LEVEL_NUM, "JSON_DEBUG")

# --- GLOBAL SWITCH ---
# Set to DEMO_LEVEL_NUM for standard runs, JSON_DEBUG_LEVEL_NUM for full debug.
GLOBAL_LOG_LEVEL = DEMO_LEVEL_NUM
# GLOBAL_LOG_LEVEL = JSON_DEBUG_LEVEL_NUM


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

class MetricsJSONFormatter(logging.Formatter):
    """
    Compact formatter for high-level metrics and lifecycle events.

    Emits only lightweight fields: cycle, event_type, duration_ms.
    Suitable for operational dashboards and event-stream analysis.
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

    Configures three handlers:
    - Console (Rich): DEMO level and above, text shown verbatim
      (Rich markup only on explicit opt-in).
    - Metrics file (*_events.jsonl): all levels, compact JSON format.
    - Debug file (*_debug.jsonl): all levels, verbose JSON format.
      Added only when GLOBAL_LOG_LEVEL is set to JSON_DEBUG_LEVEL_NUM.

    The AppLogFilter is instantiated once and shared across all handlers.
    """
    run_id = str(uuid.uuid4())[:8]

    # --- 1. Log directory and base filename ---
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_filename = f"{timestamp}_{run_id}_workflow"

    root_logger = logging.getLogger()
    root_logger.setLevel(GLOBAL_LOG_LEVEL)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # --- 2. Application filter (shared across all handlers) ---
    # Instantiated before any handler is added: guarantees that only Civica's
    # own modules produce output on any channel, excluding third-party libraries
    # regardless of the active global log level.
    app_filter = AppLogFilter()

    # --- 3. Console handler (Rich) ---
    # RichHandler replaces StreamHandler for styled console output.
    # No explicit Formatter is needed: RichHandler provides its own.
    console_handler = RichHandler(
        rich_tracebacks=True,
        markup=False,
        log_time_format="[%X]",
    )
    console_handler.setLevel(DEMO_LEVEL_NUM)
    console_handler.addFilter(app_filter)
    root_logger.addHandler(console_handler)

    # --- 4. Metrics file handler ---
    # app_filter already instantiated above — shared without re-instantiating.
    metrics_log_path = os.path.join(log_dir, f"{base_filename}_events.jsonl")
    metrics_handler = logging.FileHandler(metrics_log_path, mode="a", encoding="utf-8")
    metrics_handler.setLevel(JSON_DEBUG_LEVEL_NUM)
    metrics_handler.setFormatter(MetricsJSONFormatter())
    metrics_handler.addFilter(app_filter)
    root_logger.addHandler(metrics_handler)

    # --- 5. Verbose debug file handler (conditional) ---
    # Added only when full debug mode is active.
    if GLOBAL_LOG_LEVEL <= JSON_DEBUG_LEVEL_NUM:
        debug_log_path = os.path.join(log_dir, f"{base_filename}_debug.jsonl")
        debug_handler = logging.FileHandler(debug_log_path, mode="a", encoding="utf-8")
        debug_handler.setLevel(JSON_DEBUG_LEVEL_NUM)
        debug_handler.setFormatter(VerboseJSONFormatter())
        debug_handler.addFilter(app_filter)
        root_logger.addHandler(debug_handler)

    # --- 6. Startup messages ---
    logger = logging.getLogger(__name__)
    logger.demo(
        f"Logging system [bold green]configured[/bold green]. "
        f"Run ID: [yellow]{run_id}[/yellow]",
        extra={"markup": True},
    )
    logger.demo(
        f"Event log saved to: [cyan]{metrics_log_path}[/cyan]",
        extra={"markup": True},
    )

    if GLOBAL_LOG_LEVEL <= JSON_DEBUG_LEVEL_NUM:
        logger.demo(
            f"Full debug log saved to: {debug_log_path}",
            extra={"markup": True},
            )

    return run_id