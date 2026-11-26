"""Which exit-code cells of the published contract each CLI actually emits.

The mutation rate says which one-line changes the tests notice. It does not say that a
module emits the codes the README publishes, and a flag whose name promises a comparison
is not a comparison: `live_oracle --referencia` takes the reference's *names* and never
judges against its values. So every cell is measured by running the CLI — and the cells
that are empty are measured too, declared with the code they do return, so the day an
empty cell starts firing this goes red instead of the README going stale.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20

MEDIDO = ""
SIN_SUJETO = "sin_sujeto"
POR_DISENO = "por_diseno"
SIN_NODO = "sin_nodo"


def _perfil(raiz: Path, n: int, *, fase: float = 0.0,
            semillas: tuple[float, ...] | None = None) -> str:
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from ts_py_anchor_guard.subpixel_probe import perfil_sintetico
    extra = {} if semillas is None else {"semillas": semillas}
    return " ".join(repr(v) for v in perfil_sintetico(n, fase=fase, **extra))


def _hay_nodo(raiz: Path) -> bool:
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from ts_py_anchor_guard.live_oracle import version_de_nodo
    return version_de_nodo() is not None


def casos(raiz: Path, caja: Path) -> list[dict]:
    """At least one row per code and module. `esperado` is what the process returns, not an ideal.

    Two codes carry more than one row because the same code can be reached by two different
    routes, and only one of them is a measurement: `2` from a missing file and `2` from a
    profile too short to band are both gaps, and `1` from a divergence and `1` from a crash
    are not the same verdict. `evaluar` rejects the crash outright.
    """
    (caja / "malo.json").write_text(json.dumps({"CANVAS_W": 999.0}))
    (caja / "vacia.json").write_text("{}")
    (caja / "vacio.txt").write_text("")
    (caja / "a.txt").write_text(_perfil(raiz, 600, fase=0.25))
    (caja / "b.txt").write_text(_perfil(raiz, 600, semillas=(0.037, 0.101, 0.229)))
    ref = str(raiz / "fixtures" / "anchors.json")
    eng = str(raiz / "fixtures" / "engine.ts")
    malo, a, b, falta = str(caja / "malo.json"), str(caja / "a.txt"), str(caja / "b.txt"), "/no-existe"
    vacia, vacio = str(caja / "vacia.json"), str(caja / "vacio.txt")
    nodo = _hay_nodo(raiz)
    # Sin node, el lector no puede medir y lo dice: la celda vacia es NO_MEDIDO, no un 0.
    lo_ok, lo_clase, lo_motivo = ((RC_OK, MEDIDO, "") if nodo else
                                  (RC_NO_MEDIDO, SIN_NODO,
                                   "sin node >= 22.6 el lector declara NO_MEDIDO en vez de verde"))
    lo_div_clase, lo_div_motivo = ((POR_DISENO,
                                    "el CLI es lector: devuelve los valores medidos y no juzga; "
                                    "la referencia aporta nombres, no valores. Juzga "
                                    "`anchor_oracle --backend node`") if nodo else
                                   (SIN_NODO, lo_motivo))
    filas = [
        ("anchor_oracle", RC_OK, ("--fuente", eng, "--referencia", ref), RC_OK, MEDIDO, ""),
        ("anchor_oracle", RC_DIVERGE, ("--fuente", eng, "--referencia", malo), RC_DIVERGE, MEDIDO, ""),
        ("anchor_oracle", RC_NO_MEDIDO, ("--fuente", falta + ".ts", "--referencia", ref),
         RC_NO_MEDIDO, MEDIDO, ""),
        ("anchor_oracle", RC_NO_MEDIDO, ("--fuente", eng, "--referencia", vacia),
         RC_NO_MEDIDO, MEDIDO, "una referencia sin nombres no conforma nada"),
        ("anchor_oracle", RC_ARITY, ("--inexistente",), RC_ARITY, MEDIDO, ""),

        ("live_oracle", RC_OK, ("--fuente", eng, "--referencia", ref), lo_ok, lo_clase, lo_motivo),
        ("live_oracle", RC_DIVERGE, ("--fuente", eng, "--referencia", malo), lo_ok,
         lo_div_clase, lo_div_motivo),
        ("live_oracle", RC_NO_MEDIDO, ("--fuente", falta + ".ts", "--referencia", ref),
         RC_NO_MEDIDO, MEDIDO, ""),
        ("live_oracle", RC_ARITY, ("--inexistente",), RC_ARITY, MEDIDO, ""),

        ("subpixel_probe", RC_OK, ("--a", a, "--b", a), RC_OK, MEDIDO, ""),
        ("subpixel_probe", RC_DIVERGE, ("--a", a, "--b", b), RC_NO_MEDIDO, POR_DISENO,
         "mide una fase; dos perfiles sin relacion no son una divergencia, son NO_MEDIDO"),
        ("subpixel_probe", RC_NO_MEDIDO, ("--a", falta + ".txt", "--b", b), RC_NO_MEDIDO, MEDIDO, ""),
        ("subpixel_probe", RC_NO_MEDIDO, ("--a", vacio, "--b", vacio), RC_NO_MEDIDO, MEDIDO,
         "un perfil vacio no se divide en bandas: NO_MEDIDO, no el 1 de un choque"),
        ("subpixel_probe", RC_ARITY, ("--inexistente",), RC_ARITY, MEDIDO, ""),

        ("viewport_embed", RC_OK, ("--canvas", "1080", "1920", "--ventana", "864", "960"),
         RC_OK, MEDIDO, ""),
        ("viewport_embed", RC_DIVERGE, ("--canvas", "1080", "1920", "--ventana", "1200", "960"),
         RC_DIVERGE, MEDIDO, ""),
        ("viewport_embed", RC_NO_MEDIDO, ("--canvas", "1080", "1920"), RC_ARITY, SIN_SUJETO,
         "no lee archivos: un insumo faltante es aridad, no INSUMO_FALTA"),
        ("viewport_embed", RC_ARITY, ("--inexistente",), RC_ARITY, MEDIDO, ""),
    ]
    return [{"modulo": m, "codigo": c, "esperado": e, "clase": clase, "motivo": motivo,
             "orden": [sys.executable, "-m", f"ts_py_anchor_guard.{m}", *args],
             "args": list(args)} for m, c, args, e, clase, motivo in filas]


def evaluar(filas: list[dict], *, raiz: Path) -> tuple[list[dict], int]:
    fallos = 0
    for fila in filas:
        proc = subprocess.run(fila["orden"], cwd=raiz, capture_output=True, text=True)
        fila["obtenido"] = proc.returncode
        # `1` is both "diverges" and the exit Python gives an uncaught exception, so a crash
        # satisfied a divergence cell by accident. A cell conforms only if it did not crash.
        fila["choque"] = "Traceback (most recent call last)" in proc.stderr
        fila["conforme"] = proc.returncode == fila["esperado"] and not fila["choque"]
        fallos += 0 if fila["conforme"] else 1
    return filas, (RC_OK if not fallos else RC_DIVERGE)


def _tabla(filas: list[dict]) -> str:
    ancho = max(len(f["modulo"]) for f in filas)
    lineas = []
    for f in filas:
        if f["conforme"]:
            marca = (f["clase"] or "medido").upper()
            extra = f"  ({f['motivo']})" if f["motivo"] else ""
            lineas.append(f"{f['modulo']:{ancho}s}  {f['codigo']:2d}  {marca}{extra}")
        else:
            causa = ("CHOQUE: revienta en vez de dar un veredicto"
                     if f.get("choque") else
                     f"devolvio {f['obtenido']}, se esperaba {f['esperado']}")
            lineas.append(f"{f['modulo']:{ancho}s}  {f['codigo']:2d}  DIVERGE: {causa}")
    return "\n".join(lineas)


def _autotest(raiz: Path) -> int:
    # El control negativo no arranca el sujeto: un control que comparte el modo de fallo
    # del sujeto no es un control. Un proceso que sale con 7 y una expectativa de 99
    # tienen que discrepar; si no, el verificador esta de acuerdo con cualquier cosa.
    falso = [{"modulo": "control", "codigo": RC_OK, "esperado": 99, "clase": MEDIDO,
              "motivo": "", "args": [],
              "orden": [sys.executable, "-c", "raise SystemExit(7)"]}]
    if evaluar(falso, raiz=raiz)[1] != RC_DIVERGE:
        print("FALLO: el verificador acepto una expectativa imposible", file=sys.stderr)
        return RC_DIVERGE
    # El segundo control: `1` es la divergencia y tambien la salida de una excepcion. Un
    # proceso que revienta no puede satisfacer una celda que espera `1`.
    choque = [{"modulo": "control", "codigo": RC_DIVERGE, "esperado": RC_DIVERGE,
               "clase": MEDIDO, "motivo": "", "args": [],
               "orden": [sys.executable, "-c", "raise RuntimeError('boom')"]}]
    if evaluar(choque, raiz=raiz)[1] != RC_DIVERGE:
        print("FALLO: un choque satisfizo una celda de divergencia", file=sys.stderr)
        return RC_DIVERGE
    with tempfile.TemporaryDirectory(prefix="censo-") as caja:
        celdas = len(casos(raiz, Path(caja)))
    print(f"AUTOTEST OK: {celdas} celdas de contrato · 2 controles negativos")
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raiz", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", "--autotest", dest="self_test", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return RC_ARITY if exc.code else RC_OK
    raiz = Path(args.raiz).resolve()
    if args.self_test:
        return _autotest(raiz)
    with tempfile.TemporaryDirectory(prefix="censo-") as caja:
        filas, rc = evaluar(casos(raiz, Path(caja)), raiz=raiz)
    if args.json:
        print(json.dumps({"rc": rc, "celdas": filas}, indent=2, sort_keys=True))
    else:
        print(_tabla(filas))
    return rc


if __name__ == "__main__":
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ts_py_anchor_guard._cli import correr

    raise SystemExit(correr(main))
