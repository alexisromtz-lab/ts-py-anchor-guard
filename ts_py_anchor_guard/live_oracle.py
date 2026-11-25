"""Measure a TypeScript source by executing it, instead of re-implementing it.

`anchor_oracle` evaluates the declarations it reads with its own arithmetic. That is a
second implementation of the same formulas, and comparing a port against a second
implementation is weaker than comparing it against the engine's own runtime: a shared
misreading of the source produces agreement.

This module removes the middleman. Node strips type annotations natively from 23.6 with no
flag, and from 22.6 behind `--experimental-strip-types`, so a plain `.ts` file can be
imported and its exported constants and pure functions called, with no bundler, no
`package.json`, no network and no browser. Those three boundaries were measured, not cited:
an `.mjs` probe importing a two-line `.ts` module returns a value under 22.6.0 and 23.5.0
only with the flag, and under 23.6.0 and 24.15.0 without it. On 23.6 the runtime also emits
an `ExperimentalWarning` on stderr while exiting 0, which this module tolerates because it
reads stderr only when the exit code is non-zero. The receipt then says which runtime
produced the reference values, because a number measured by an interpreter and one measured
by a model of that interpreter are not the same evidence.

The backend is optional by design. When node is absent or too old the module reports
`NO_MEDIDO` with the reason; it never silently falls back to the static evaluator, since
that would turn a declared mode into an undeclared one.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = ["version_de_nodo", "medir"]

_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)")

# 23.6 enabled type stripping by default; 22.6 behind a flag; anything older cannot run
# a `.ts` file at all.
_SIN_FLAG = (23, 6)
_CON_FLAG = (22, 6)

_PROBE = """
import * as motor from "./fuente.ts";
const referencia = JSON.parse(process.argv[2]);
const valor = (v) => {
  if (typeof v === "number") return Number.isFinite(v) ? v : String(v);
  return typeof v;
};
const miembro = (v, camino) => {
  for (const paso of camino) v = v == null ? undefined : v[paso];
  return v;
};
const salida = {};
for (const [nombre, esperado] of Object.entries(referencia)) {
  const [base, ...camino] = nombre.split(".");
  const f = motor[base];
  if (typeof f !== "function") {
    salida[nombre] = [valor(miembro(f, camino))];
    continue;
  }
  const puntos = esperado && Array.isArray(esperado.puntos) ? esperado.puntos : [null];
  salida[nombre] = puntos.map((p) =>
    valor(miembro(f(p === null ? undefined : p), camino)));
}
process.stdout.write(JSON.stringify(salida));
"""


def version_de_nodo() -> tuple[str, list[str]] | None:
    """Path and flags for a node able to import TypeScript, or `None`."""
    ruta = shutil.which("node")
    if not ruta:
        return None
    try:
        salida = subprocess.run([ruta, "--version"], capture_output=True, text=True,
                                timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    encontrado = _VERSION.match(salida.stdout.strip())
    if not encontrado:
        return None
    mayor, menor = int(encontrado.group(1)), int(encontrado.group(2))
    if (mayor, menor) >= _SIN_FLAG:
        return ruta, []
    if (mayor, menor) >= _CON_FLAG:
        return ruta, ["--experimental-strip-types"]
    return None


def medir(fuente: str, referencia: dict, *, nodo: tuple[str, list[str]] | None = None
          ) -> tuple[dict, str]:
    """Execute `fuente` and return `({nombre: [valores]}, "")` or `({}, motivo)`."""
    elegido = nodo if nodo is not None else version_de_nodo()
    if elegido is None:
        return {}, "node >= 22.6 no esta disponible para ejecutar la fuente"
    ruta, flags = elegido
    with tempfile.TemporaryDirectory(prefix="oraculo-vivo-") as caja:
        caja = Path(caja)
        # The extension has to stay `.ts`: that is the signal node uses to strip types.
        (caja / "fuente.ts").write_text(fuente)
        (caja / "probe.mjs").write_text(_PROBE)
        orden = [ruta, *flags, str(caja / "probe.mjs"), json.dumps(referencia)]
        try:
            corrida = subprocess.run(orden, capture_output=True, text=True, timeout=120,
                                     cwd=caja)
        except (OSError, subprocess.SubprocessError) as fallo:
            return {}, f"node no corrida: {fallo}"
        if corrida.returncode != 0:
            ultimo = (corrida.stderr or "").strip().splitlines()[-1:]
            return {}, f"node rc {corrida.returncode}: {' '.join(ultimo)}"
        try:
            crudo = json.loads(corrida.stdout)
        except json.JSONDecodeError:
            return {}, "node no devolvio JSON"
    # A value that is not a number was named in the reference but is not measurable: it is
    # kept as `None` so `comparar` reports the anchor instead of dropping it.
    return ({nombre: [v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
                      for v in valores]
             for nombre, valores in crudo.items()}, "")


_FUENTE_PRUEBA = """
export const A = 864;
export const CAJA = { ancho: 1080 } as const;
export const rect = (y?: number) => ({ top: y ?? 480, ancho: CAJA.ancho });
export const roto = (v: number) => String(v);
"""


def _autotest() -> int:
    nodo = version_de_nodo()
    if nodo is None:
        # Not a pass: without a runtime there is nothing measured, and saying OK here would
        # make the module look verified on exactly the machines that cannot verify it.
        print("AUTOTEST NO_MEDIDO: node >= 22.6 no esta disponible", file=sys.stderr)
        return 2
    fallos = []
    vivos, motivo = medir(_FUENTE_PRUEBA, {
        "A": 864, "CAJA.ancho": 1080,
        "rect.top": {"puntos": [None, 500], "valores": [480, 500]},
        "roto": {"puntos": [1], "valores": [1]},
    }, nodo=nodo)
    if motivo:
        fallos.append(f"medir: {motivo}")
    esperado = {"A": [864], "CAJA.ancho": [1080], "rect.top": [480, 500], "roto": [None]}
    for nombre, valores in esperado.items():
        if vivos.get(nombre) != valores:
            fallos.append(f"{nombre}: {vivos.get(nombre)!r} != {valores!r}")
    vacio, motivo_roto = medir("export const A = ;", {"A": 1}, nodo=nodo)
    if vacio or "node rc" not in motivo_roto:
        fallos.append("una fuente que no compila no se declaro")
    for mensaje in fallos:
        print(f"FALLO {mensaje}", file=sys.stderr)
    if fallos:
        print(f"AUTOTEST NO OK: {len(fallos)} ancla(s)", file=sys.stderr)
        return 1
    version = subprocess.run([nodo[0], "--version"], capture_output=True,
                             text=True).stdout.strip()
    print(f"AUTOTEST OK: 7 anclas de oraculo vivo · {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fuente", help="archivo TypeScript a ejecutar")
    parser.add_argument("--referencia", help="JSON {nombre: valor o {puntos, valores}}")
    parser.add_argument("--self-test", "--autotest", dest="self_test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _autotest()
    if not args.fuente or not args.referencia:
        print("uso: live_oracle.py --fuente F.ts --referencia ref.json", file=sys.stderr)
        return 20
    vivos, motivo = medir(Path(args.fuente).read_text(),
                          json.loads(Path(args.referencia).read_text()))
    if motivo:
        print(f"NO_MEDIDO · {motivo}", file=sys.stderr)
        return 2
    print(json.dumps(vivos, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
