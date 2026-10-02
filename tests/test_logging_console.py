# tests/test_logging_console.py
#
# La console usa Rich, che interpreta come stile il testo tra parentesi
# quadre ([bold], [red]...). Nei log però finisce anche testo non fidato:
# richieste dell'utente, prompt, output dell'LLM, percorsi di file.
# Quel testo deve arrivare in console così com'è, senza essere interpretato.

import io
import logging

import pytest
from rich.console import Console
from rich.logging import RichHandler

import logger_config


@pytest.fixture
def console(tmp_path, monkeypatch):
    """Configura il logging vero e cattura la console Rich in un buffer."""
    monkeypatch.chdir(tmp_path)  # setup_logging scrive i file in ./logs
    radice = logging.getLogger()
    handler_prima, livello_prima = radice.handlers[:], radice.level

    logger_config.setup_logging()
    rich_handler = next(h for h in radice.handlers if isinstance(h, RichHandler))
    buffer = io.StringIO()
    rich_handler.console = Console(file=buffer, width=200, color_system=None)

    yield buffer

    # Ripristina il logging com'era: nessuna traccia nei test successivi.
    for h in radice.handlers[:]:
        radice.removeHandler(h)
        h.close()
    for h in handler_prima:
        radice.addHandler(h)
    radice.setLevel(livello_prima)


# Un logger con un nome ammesso dall'AppLogFilter.
log = logging.getLogger("orchestrator")


def test_un_tag_di_chiusura_non_ferma_il_programma(console):
    # Rich solleva un'eccezione su un tag di chiusura senza apertura.
    log.demo("Richiesta: 'valore [/bold] chiuso'")
    assert "valore [/bold] chiuso" in console.getvalue()


@pytest.mark.parametrize("testo", [
    "[vedi qui](https://esempio.it)",           # link Markdown in un output LLM
    "[red]testo colorato",                      # stile mai chiuso
    "[link=https://esempio.it]clicca[/link]",   # link nascosto
], ids=["link_markdown", "stile_aperto", "link_nascosto"])
def test_il_testo_non_fidato_arriva_cosi_com_e(console, testo):
    log.demo(f"Output: {testo}")
    assert testo in console.getvalue()


def test_lo_stile_resta_disponibile_su_richiesta(console):
    # Guardia: i messaggi scritti dal programma possono ancora usare gli stili.
    log.demo("[bold]Avvio[/bold]", extra={"markup": True})
    uscita = console.getvalue()
    assert "Avvio" in uscita
    assert "[bold]" not in uscita
