# tests/test_placeholder_resolution.py
#
# Test unitari sulla risoluzione dei placeholder {state.X} nei task YAML
# non-template (es. nomi di file, riferimenti diretti allo stato).

import pytest

from orchestrator import AdvancedOrchestrator


@pytest.fixture
def orchestratore(percorso_config):
    """Un orchestratore qualsiasi, con tre variabili note nello stato."""
    orch = AdvancedOrchestrator(percorso_config("config_procurement.yaml"), agent_factory=None)
    orch.state.set_global_variable("a", "uno")
    orch.state.set_global_variable("b", "due")
    orch.state.set_global_variable("lista", [1, 2, 3])
    return orch


@pytest.mark.parametrize("ingresso, atteso", [
    # Un solo placeholder: il valore mantiene il suo tipo Python
    ("{state.lista}", [1, 2, 3]),
    # Placeholder dentro testo: interpolazione come stringa
    ("file_{state.a}.txt", "file_uno.txt"),
    ("{state.a}_{state.b}.md", "uno_due.md"),
    # IL CASO LATENTE: inizia con { e finisce con }, ma i placeholder sono due
    ("{state.a}-{state.b}", "uno-due"),
])
def test_risoluzione_placeholder(orchestratore, ingresso, atteso):
    assert orchestratore._resolve_placeholders_recursive(ingresso) == atteso