"""The receipt, compressed to the one line a CI job has to read.

`GITHUB_OUTPUT` is read by a caller, not by a human: it wants the verdict, the counts and the
finding. A full census receipt of one real `constants` file is 34 141 B as a single line, and the
first external repository with a few hundred anchors would learn about that limit from a truncated
output nobody could parse. So the line carries a summary by construction and the whole receipt goes
to `receipt-file`, where size costs nothing.

What survives is decided by size, not by position. One walk, one budget: inside every object the
smallest values are placed first, so `rc`, `evaluables`, `declaradas` and `cobertura` -- the verdict
-- are carried before a 118-anchor body table can spend it. A node whose own contents do not fit is
collapsed to its size and its key names, and either way it says in `_resumido` which of its members
did not travel. Nothing is dropped silently: a summary that looked like a complete receipt would be
the same lie as a green over zero anchors.

That collapse is also the bound. A node can only be greedy, which is capped by its budget, or
collapsed, which costs a fixed handful of bytes -- so no receipt, however wide, can produce a line
over `limite`. The walk is deterministic -- ties broken by key name -- so the same receipt yields
the same line twice.

RC: 0 summarised · 2 the input was not a JSON object (a caller must not publish a line it cannot
trust).
"""

from __future__ import annotations

import json
import sys

RC_OK, RC_NO_MEDIDO = 0, 2

# `GITHUB_OUTPUT` allows more per value, but a job writes many values against a per-file limit, and
# a line under 2 KiB is readable in a log, greppable, and safe by a wide margin. Measured against
# the real 118-anchor receipt: see `ResumenDeReciboTest`.
LIMITE = 2048
_CLIP = 96
_CLIP_ESCUETO = 24
_CLAVES_ESCUETO = 4
_RESERVA = 64  # `bytes` and `limite` are added after the walk and are not part of its budget


def _crudo(valor) -> str:
    return json.dumps(valor, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _clipa(texto: str, tope: int = _CLIP) -> str:
    return texto if len(texto) <= tope else texto[:tope] + f"…(+{len(texto) - tope})"


def _escueto(valor):
    """What is left of a value that did not fit: how big it is, and what it is called."""
    if isinstance(valor, dict):
        return {"n": len(valor), "_claves": sorted(valor)[:_CLAVES_ESCUETO]}
    if isinstance(valor, list):
        return {"n": len(valor)}
    if isinstance(valor, str):
        return _clipa(valor, _CLIP_ESCUETO)
    return repr(valor)


def _tabular(valor: list, presupuesto: int):
    """A list of same-keyed objects as columns and rows, or None if it does not apply.

    A differential's `filas` is its whole finding, and its width is not information: every row
    repeats the same three key names. Spending the budget on that repetition would leave the
    summary saying "26 changed" without naming one, so the names travel once, as `columnas`, and
    the rows become arrays. Nothing is dropped -- the same 26 rows are all still there -- and the
    reduction only applies when the keys really are identical, so a ragged list keeps its shape.
    """
    if len(valor) < 3 or not all(isinstance(elemento, dict) for elemento in valor):
        return None
    columnas = sorted(valor[0])
    if any(sorted(elemento) != columnas for elemento in valor):
        return None
    tabla = {"columnas": columnas, "filas": [[elemento[c] for c in columnas] for elemento in valor]}
    return tabla if len(_crudo(tabla)) <= presupuesto else None


def _muestra(valor: list, presupuesto: int):
    """As many leading elements as fit, in order, plus how many did not travel.

    Order is the finding's own order, so the rows that do travel are the first ones rather than an
    arbitrary subset -- and `_resto` says the list was longer. A reader who needs all of them reads
    `receipt-file`; a reader who needs the shape of the finding gets it from the line.
    """
    cabeza: list = []
    usado = 2
    for elemento in valor:
        sub, _ = _compacta(elemento, max(presupuesto - usado - 24, 16))
        coste = len(_crudo(sub)) + 1
        if usado + coste > presupuesto - 24:
            break
        cabeza.append(sub)
        usado += coste
    if not cabeza:
        return _escueto(valor), True
    recorte = {"n": len(valor), "muestra": cabeza}
    if len(cabeza) < len(valor):
        recorte["_resto"] = len(valor) - len(cabeza)
    return recorte, True


def _compacta(valor, presupuesto: int):
    """`valor` inside `presupuesto` bytes; the second half says whether anything was cut."""
    if len(_crudo(valor)) <= presupuesto:
        return valor, False
    if isinstance(valor, list):
        # Lossless first: the repetition of key names is the largest share of a wide list's size
        # and removing it costs nothing a reader loses.
        tabla = _tabular(valor, presupuesto)
        return (tabla, True) if tabla is not None else _muestra(valor, presupuesto)
    if not isinstance(valor, dict):
        return _escueto(valor), True
    salida: dict = {}
    resumidos: list[str] = []
    usado = 2
    # Smallest first, ties by name: the scalars that are the verdict cost little and must not be
    # starved by the one key that happens to hold a whole file's declarations.
    for clave, sub_valor in sorted(valor.items(), key=lambda kv: (len(_crudo(kv[1])), kv[0])):
        disponible = presupuesto - usado - len(_crudo(clave)) - 4
        if disponible <= 8:
            resumidos.append(clave)
            continue
        sub, _ = _compacta(sub_valor, disponible)
        salida[clave] = sub
        usado += len(_crudo(sub)) + len(_crudo(clave)) + 4
    for clave in resumidos:
        salida[clave] = _escueto(valor[clave])
        usado += len(_crudo(salida[clave])) + len(_crudo(clave)) + 4
    if resumidos:
        salida["_resumido"] = sorted(resumidos)
    if len(_crudo(salida)) <= presupuesto:
        return salida, True
    # The greedy did not fit -- too many members, each already minimal. The node keeps its size and
    # a sample of its names: that is what tells a reader a population exists, and it costs a fixed
    # handful of bytes however wide the node was. Listing every name here would be the same overflow
    # in another shape.
    return _escueto(valor), True


def resumir(recibo: dict, limite: int = LIMITE, bytes_original: int | None = None) -> dict:
    """The receipt held under `limite` bytes, with every compressed key still named."""
    original = len(_crudo(recibo)) if bytes_original is None else bytes_original
    if original <= limite:
        # A receipt that already fits is published whole: compressing it would lose names for
        # nothing, and a differential receipt's `filas` *is* the evidence.
        return recibo
    corto, _ = _compacta(recibo, limite - _RESERVA)
    corto["bytes"] = original
    corto["limite"] = limite
    if len(_crudo(corto)) > limite:  # the reserve was not enough: say it, never overflow silently
        corto = {"rc": recibo.get("rc"), "bytes": original, "limite": limite,
                 "_resumido": sorted(recibo)}
    return corto


def main(argv: list[str] | None = None) -> int:
    crudo = sys.stdin.read()
    try:
        recibo = json.loads(crudo)
    except json.JSONDecodeError as exc:
        print(f"NO_MEDIDO · el recibo no es JSON: {exc}", file=sys.stderr)
        return RC_NO_MEDIDO
    if not isinstance(recibo, dict):
        print(f"NO_MEDIDO · el recibo no es un objeto: es {type(recibo).__name__}",
              file=sys.stderr)
        return RC_NO_MEDIDO
    # `bytes` is what the caller's line would have been -- the receipt with its newlines removed,
    # which is exactly how `action.yml` published it before this module -- not a re-serialisation
    # of the parsed object: a summary has to price the thing it replaced.
    print(_crudo(resumir(recibo, bytes_original=len(crudo.replace("\n", "").strip().encode()))))
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
