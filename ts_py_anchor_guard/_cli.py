"""The two edges of the contract that argparse does not honour by itself.

`argparse` exits `2` on a bad invocation -- an unknown flag, an `int` argument that is not
an `int`. This package reserves `2` for "not measured", and the two meanings are opposite:
`2` tells a CI runner "there is a gap here, do not read this as conforming", while a typo
in the command tells it nothing about the subject. Collapsing them produced a real
report: `--no-existe-esta-flag` exited `2` in all four modules, so a misspelled flag was
indistinguishable from a measurement that could not be taken.

A missing input file has the same failure mode from the other side: `Path(...).read_text()`
raises `FileNotFoundError`, the traceback exits `1`, and `1` means "diverging -- the port
is wrong". Nothing was measured, so the answer is `2`, and it is printed as a receipt line
rather than a stack trace.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from . import RC_ARITY, RC_NO_MEDIDO


class ParserDeContrato(argparse.ArgumentParser):
    """`ArgumentParser` whose bad-invocation exit code is the contract's `20`, not `2`."""

    def error(self, message: str) -> None:  # noqa: D102 - argparse hook
        self.print_usage(sys.stderr)
        self.exit(RC_ARITY, f"{self.prog}: error: {message}\n")


class InsumoFalta(Exception):
    """An input the receipt needs could not be read."""


def leer_texto(ruta: str, papel: str) -> str:
    """Text of `ruta`, or :class:`InsumoFalta` naming `papel` and the OS reason."""
    from pathlib import Path

    try:
        return Path(ruta).read_text()
    except OSError as exc:
        raise InsumoFalta(f"{papel} {ruta!r}: {exc.strerror or exc}") from exc


def no_medido(causa: str, detalle: str) -> int:
    """Print the not-measured receipt line and return its code."""
    print(f"NO_MEDIDO · {causa} · {detalle}", file=sys.stderr)
    return RC_NO_MEDIDO


def correr(principal: Callable[[list[str] | None], int],
           argv: list[str] | None = None) -> int:
    """Run `principal` at the process boundary, turning a crash into a gap.

    `1` tells a runner "the subject diverges", and it is also what Python returns when an
    exception escapes: a crash inside the instrument would be read as a verdict about the
    subject. So the boundary answers `2` and names the failure, while `principal` itself
    keeps raising -- a test still sees the defect instead of a polite receipt.
    """
    try:
        return principal(argv)
    except SystemExit:
        raise
    except Exception as fallo:  # noqa: BLE001 - the boundary is where a last net belongs
        print(f"NO_MEDIDO · FALLA_INTERNA · {type(fallo).__name__}: {fallo}", file=sys.stderr)
        return RC_NO_MEDIDO
