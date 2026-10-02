# utils.py
#
# Shared utility functions used across the Civica agent modules.

import json
import os
import re

from rich import print as rprint


def ask_valid_file_path(prompt_message: str) -> str:
    """
    Prompts the user for a file path and loops until a valid, existing path
    is provided.
    """
    while True:
        path = input(prompt_message)
        if os.path.exists(path):
            return path
        else:
            rprint("[bold red]ERROR: File not found. Please try again.[/bold red]")


def to_json_string(value) -> str:
    """
    Single 'json_string' conversion, shared by the context_preparators and
    the prompt parameters of the orchestrator.

    Only an absent value (None) becomes "{}". Empty or falsy values keep
    their type: [] stays "[]", 0 stays "0".
    ensure_ascii=False: the string ends up in a prompt, so accented letters
    must stay readable ("è", not "\u00e8").
    """
    if value is None:
        return "{}"
    return json.dumps(value, indent=2, ensure_ascii=False)

def is_missing_value(value) -> bool:
    """
    Single definition of "missing", shared by the formal validator and the
    'exists' operator of the orchestrator.

    None, blank strings and empty containers count as missing.
    False and 0 are legitimate values and do not.
    """
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, (list, dict)) and not value)
    )


def substitute_placeholders(template: str, values: dict) -> str:
    """
    Replaces {key} placeholders in template with values[key], in a single
    atomic pass (same rule as the orchestrator core).

    - Only the keys listed in values are placeholders: any other brace
      (a JSON example, a LaTeX command) is left untouched.
    - Inserted values are opaque text and are never re-processed.
    """
    if not values:
        return template
    pattern = re.compile(r"\{(" + "|".join(re.escape(k) for k in values) + r")\}")
    return pattern.sub(lambda m: str(values[m.group(1)]), template)


def fill_template_recursive(template, data_source):
    """
    Recursively fills a template structure (dict, list, or string) by
    substituting {key} placeholders with values from data_source.

    - Missing keys (value is None) are replaced with the string 'N/A'.
    - Non-string, non-container values are returned unchanged.
    """
    if isinstance(template, dict):
        return {k: fill_template_recursive(v, data_source) for k, v in template.items()}
    if isinstance(template, list):
        return [fill_template_recursive(item, data_source) for item in template]
    if isinstance(template, str):
        def replace_match(match):
            key = match.group(1).strip()
            value = data_source.get(key)
            if value is None:
                return "N/A"
            return str(value)

        return re.sub(r"\{(.*?)\}", replace_match, template)

    return template