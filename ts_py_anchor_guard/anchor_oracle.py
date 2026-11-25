"""Do the numbers a TypeScript source declares evaluate to what the Python port computes?

"Looks visually identical" is not a contract. When a layout or camera engine is ported
from TypeScript to Python, the two sides must agree on the *arithmetic* -- the closed
form, the clamps, the order of operations -- before anyone argues about pixels. That
comparison is cheap if the numbers can be read and evaluated, and it is exact: two
implementations of the same closed form over the same inputs return the same float, so
the tolerance is `0.0` rather than a number chosen to make a test pass.

This module reads the declaration subset where that claim is meaningful and checkable:

    const VENTANA = 864;                     // numeric constant / arithmetic over them
    const ESCALA = 1725 / 1344;
    const FRACCION = (u: number) => u * u * u;   // single-expression arrow function

It evaluates them without a TypeScript toolchain, a browser, or an E2E suite, and
compares against values supplied by the Python side. What it does NOT evaluate is
anything it cannot read honestly -- object literals, blocks, imports, stateful code --
which is reported as `NO_MEDIDO` (exit code 2) and never as conforming.

When the divergence is real, `residuo_de_redondeo` says whether `floor`, `round` or `ceil`
of the Python value would have matched. A port that quantises where the engine keeps
`985.714` produces an error that grows with the coordinate; naming the residual turns
"the numbers differ" into "the numbers differ because one side rounds".

RC: 0 conforming (every anchor within tolerance) · 1 diverging (anchor and point named)
· 2 not measured (no readable anchor, or a requested anchor was not declared) · 20 bad
invocation.
"""

from __future__ import annotations

import json
import math
import re
import sys

RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20


class FuenteIlegible(ValueError):
    """The source cannot be read as the declaration subset this module claims to read."""


class AnclaDesconocida(KeyError):
    """The reference names an anchor the source does not declare."""


# --------------------------------------------------------------------- lectura

_COMENTARIO = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_DECLARACION = re.compile(
    r"^[ \t]*(?:export[ \t]+)?const[ \t]+([A-Za-z_$][\w$]*)[ \t]*(?::[^=\n]+)?=[ \t]*(.+?);?[ \t]*$",
    re.M)
_FLECHA = re.compile(r"^\(?([A-Za-z_$][\w$]*)[ \t]*(?::[^)=]+)?\)?[ \t]*=>[ \t]*(.+)$", re.S)


def extraer_anclas(texto: str) -> dict[str, dict]:
    """Declarations this module can evaluate honestly, keyed by name.

    Each entry is `{"tipo": "const" | "funcion", "cuerpo": str, "params": [...]}`. A
    declaration it cannot read (object literal, block body, call into something outside
    the expression) is skipped, not guessed: the caller learns what was measured from the
    receipt, and an anchor that is missing from it is `NO_MEDIDO`.
    """
    limpio = _COMENTARIO.sub("", texto)
    anclas: dict[str, dict] = {}
    for nombre, cuerpo in _DECLARACION.findall(limpio):
        cuerpo = cuerpo.strip()
        if not cuerpo or cuerpo[0] in "{[`'\"":
            continue
        flecha = _FLECHA.match(cuerpo)
        if flecha and flecha.group(2).strip().startswith("{"):
            continue
        if flecha:
            params = [p.strip() for p in flecha.group(1).split(",") if p.strip()]
            anclas[nombre] = {"tipo": "funcion", "cuerpo": flecha.group(2).strip(),
                              "params": params}
        else:
            anclas[nombre] = {"tipo": "const", "cuerpo": cuerpo, "params": []}
    return anclas


# ------------------------------------------------------------------ evaluacion

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)|([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
                    r"|(\*\*|[-+*/(),]))")

_CONSTANTES = {"Math.PI": math.pi, "Math.E": math.e}

_FUNCIONES = {
    "Math.floor": math.floor,
    "Math.ceil": math.ceil,
    "Math.round": lambda x: math.floor(x + 0.5),  # JS rounds half towards +infinity
    "Math.abs": abs,
    "Math.sqrt": math.sqrt,
    "Math.sign": lambda x: (x > 0) - (x < 0),
    "Math.min": min,
    "Math.max": max,
    "Math.pow": math.pow,
}


def _tokenizar(expr: str) -> list[tuple[str, object]]:
    tokens, pos = [], 0
    while pos < len(expr):
        if expr[pos:].strip() == "":
            break
        m = _TOKEN.match(expr, pos)
        if not m:
            raise FuenteIlegible(f"no se puede tokenizar en {pos}: {expr[pos:pos + 20]!r}")
        num, nombre, op = m.groups()
        if num is not None:
            tokens.append(("num", float(num)))
        elif nombre is not None:
            tokens.append(("nombre", nombre))
        else:
            tokens.append(("op", op))
        pos = m.end()
    return tokens


class _Evaluador:
    """Recursive descent over the arithmetic subset: literals, names, `+ - * / **`, calls."""

    def __init__(self, tokens: list[tuple[str, object]], entorno: dict[str, float]):
        self.tokens, self.i, self.entorno = tokens, 0, entorno

    def _mirar(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _tomar(self, valor=None, tipo=None):
        tok = self._mirar()
        if tok[0] is None or (tipo and tok[0] != tipo) or (valor and tok[1] != valor):
            raise FuenteIlegible(f"se esperaba {valor or tipo}, llego {tok[1]!r}")
        self.i += 1
        return tok

    def evaluar(self) -> float:
        valor = self._suma()
        if self.i != len(self.tokens):
            raise FuenteIlegible(f"sobra {self.tokens[self.i:]}")
        return valor

    def _suma(self) -> float:
        valor = self._producto()
        while self._mirar()[1] in ("+", "-"):
            op = self._tomar()[1]
            valor = valor + self._producto() if op == "+" else valor - self._producto()
        return valor

    def _producto(self) -> float:
        valor = self._potencia()
        while self._mirar()[1] in ("*", "/"):
            op = self._tomar()[1]
            derecho = self._potencia()
            valor = valor * derecho if op == "*" else valor / derecho
        return valor

    def _potencia(self) -> float:
        """`**` binds tighter than `*` and is right-associative: `3 * t ** 2` is `3*(t**2)`."""
        base = self._unario()
        if self._mirar()[1] == "**":
            self._tomar()
            return base ** self._potencia()
        return base

    def _unario(self) -> float:
        if self._mirar()[1] == "-":
            self._tomar()
            return -self._unario()
        if self._mirar()[1] == "+":
            self._tomar()
            return self._unario()
        return self._atomo()

    def _atomo(self) -> float:
        tipo, valor = self._mirar()
        if tipo == "num":
            self._tomar()
            return float(valor)
        if tipo == "op" and valor == "(":
            self._tomar()
            dentro = self._suma()
            self._tomar(")")
            return dentro
        if tipo == "nombre":
            self._tomar()
            if self._mirar()[1] == "(":
                self._tomar()
                args = []
                if self._mirar()[1] != ")":
                    args.append(self._suma())
                    while self._mirar()[1] == ",":
                        self._tomar()
                        args.append(self._suma())
                self._tomar(")")
                if valor not in _FUNCIONES:
                    raise FuenteIlegible(f"funcion no soportada: {valor}")
                return float(_FUNCIONES[valor](*args))
            if valor in _CONSTANTES:
                return float(_CONSTANTES[valor])
            if valor in self.entorno:
                return float(self.entorno[valor])
            raise FuenteIlegible(f"nombre no declarado: {valor}")
        raise FuenteIlegible(f"token inesperado: {valor!r}")


class _Entorno(dict):
    """Scope that resolves a constant on demand, memoised and cycle-checked."""

    def __init__(self, anclas: dict[str, dict], cache: dict[str, float],
                 en_curso: set[str]):
        super().__init__()
        self._anclas, self._cache, self._en_curso = anclas, cache, en_curso

    def __contains__(self, nombre) -> bool:
        return dict.__contains__(self, nombre) or (
            nombre in self._anclas and self._anclas[nombre]["tipo"] == "const")

    def __getitem__(self, nombre) -> float:
        if dict.__contains__(self, nombre):
            return dict.__getitem__(self, nombre)
        return _resolver(self._anclas, nombre, self._cache, self._en_curso)


def _resolver(anclas: dict[str, dict], nombre: str, cache: dict[str, float],
              en_curso: set[str]) -> float:
    if nombre in cache:
        return cache[nombre]
    if nombre in en_curso:
        raise FuenteIlegible(f"ciclo de constantes en {nombre}")
    en_curso.add(nombre)
    ancla = anclas[nombre]
    valor = _Evaluador(_tokenizar(ancla["cuerpo"]),
                       _Entorno(anclas, cache, en_curso)).evaluar()
    en_curso.discard(nombre)
    cache[nombre] = valor
    return valor


def evaluar(anclas: dict[str, dict], nombre: str, puntos=None,
            cache: dict[str, float] | None = None) -> float | list[float]:
    """Evaluate one anchor. A function is evaluated at each of `puntos`."""
    if nombre not in anclas:
        raise AnclaDesconocida(nombre)
    ancla = anclas[nombre]
    cache = {} if cache is None else cache
    constantes = _Entorno(anclas, cache, set())
    if ancla["tipo"] == "const":
        if puntos:
            raise FuenteIlegible(f"{nombre} es una constante, no se evalua en puntos")
        return _Evaluador(_tokenizar(ancla["cuerpo"]), constantes).evaluar()
    if not puntos:
        puntos = [0.0]
    if len(ancla["params"]) != 1:
        raise FuenteIlegible(
            f"{nombre} declara {len(ancla['params'])} parametros; este lector evalua funciones de uno")
    salida = []
    tokens = _tokenizar(ancla["cuerpo"])
    for u in puntos:
        entorno = _Entorno(anclas, cache, set())
        entorno[ancla["params"][0]] = float(u)
        salida.append(_Evaluador(tokens, entorno).evaluar())
    return salida


def residuo_de_redondeo(valor: float) -> dict:
    """What `floor`, `round` and `ceil` would do to a measured value, and how far each lands.

    This is the diagnostic that names the bug: when a port quantises an intermediate
    quantity the engine keeps fractional, the error is exactly `valor - round(valor)` and
    it grows with the coordinate. Reporting all three candidates avoids assuming which
    policy the port used -- the caller sees which one reproduces the number it computed.
    """
    candidatos = {"floor": math.floor(valor), "round": math.floor(valor + 0.5),
                  "ceil": math.ceil(valor)}
    return {k: {"valor": v, "residuo": round(valor - v, 12)} for k, v in candidatos.items()}


def comparar(texto: str | None, referencia: dict, *, tolerancia: float = 0.0,
             anclas: dict[str, dict] | None = None) -> dict:
    """Compare every anchor the reference names against the value it expects.

    `referencia` is `{nombre: valor}` for constants or
    `{nombre: {"puntos": [...], "valores": [...]}}` for functions. The receipt lists, per
    anchor: how many points were compared, the absolute worst error, its relative value
    and -- when it diverges -- the rounding residual of the measured value plus the policy
    (`floor` / `round` / `ceil`) that reproduces the number the port computed.
    """
    if anclas is None:
        if not texto:
            return {"rc": RC_NO_MEDIDO, "causa": "SIN_FUENTE",
                    "detalle": "sin fuente TypeScript que evaluar", "anclas": []}
        anclas = extraer_anclas(texto)
    if not anclas:
        return {"rc": RC_NO_MEDIDO, "causa": "SIN_ANCLAS",
                "detalle": "la fuente no declara ninguna ancla evaluable", "anclas": []}
    filas, divergen, no_medidas, cache = [], 0, [], {}
    for nombre, esperado in referencia.items():
        if nombre not in anclas:
            no_medidas.append(nombre)
            continue
        if isinstance(esperado, dict):
            puntos = [float(p) for p in esperado["puntos"]]
            valores = [float(v) for v in esperado["valores"]]
        else:
            puntos, valores = [], [float(esperado)]
        obtenidos = evaluar(anclas, nombre, puntos, cache)
        if not isinstance(obtenidos, list):
            obtenidos = [obtenidos]
        fila = {"ancla": nombre, "tipo": anclas[nombre]["tipo"], "puntos": len(obtenidos),
                "peor_abs": 0.0, "peor_rel": 0.0, "peor_punto": None, "ok": True}
        for punto, obtenido, valor in zip(puntos or [None], obtenidos, valores):
            error = abs(obtenido - valor)
            rel = error / abs(valor) if valor else (0.0 if error == 0 else math.inf)
            if error > fila["peor_abs"]:
                fila.update(peor_abs=error, peor_rel=rel, peor_punto=punto)
            if error > tolerancia:
                residuo = residuo_de_redondeo(obtenido)
                politica = min(residuo, key=lambda k: abs(residuo[k]["valor"] - valor))
                fila["ok"] = False
                fila["obtenido"] = obtenido
                fila["esperado"] = valor
                fila["residuo_px"] = residuo
                fila["cuantizacion"] = (
                    politica if abs(residuo[politica]["valor"] - valor) <= max(tolerancia, 0.0)
                    else None)
                divergen += 1
        filas.append(fila)
    if no_medidas:
        return {"rc": RC_NO_MEDIDO, "causa": "ANCLA_NO_DECLARADA",
                "detalle": f"la fuente no declara {', '.join(sorted(no_medidas))}",
                "anclas": filas}
    return {"rc": RC_DIVERGE if divergen else RC_OK,
            "causa": "DIVERGE" if divergen else "",
            "detalle": f"{divergen} punto(s) fuera de tolerancia {tolerancia:g}" if divergen else "",
            "tolerancia": tolerancia, "anclas": filas}


# --------------------------------------------------------------------- anclas

_FUENTE_SINTETICA = """
// Synthetic engine: a camera law and the layout constants around it.
export const VENTANA_ANCHO = 864;
const VENTANA_ALTO = 960;
const LIENZO_ANCHO = 1080;
const MARGEN = Math.floor((LIENZO_ANCHO - VENTANA_ANCHO) / 2);
const ESCALA = 1725 / 1344;
const LONA = 768 * ESCALA;
const FRACCION = (u: number) => u * u * u;
const DESPLAZAMIENTO = (t) => 17.4 * (t ** 3 - 3 * t ** 2 + 3 * t);
const REDONDEADO: { ancho: number } = { ancho: 986 };
"""


def _autotest() -> int:
    fallos = []

    def igual(nombre, obtenido, esperado, tol=1e-12):
        if isinstance(esperado, float):
            if abs(obtenido - esperado) > tol:
                fallos.append(f"{nombre}: {obtenido!r} != {esperado!r}")
        elif obtenido != esperado:
            fallos.append(f"{nombre}: {obtenido!r} != {esperado!r}")

    anclas = extraer_anclas(_FUENTE_SINTETICA)
    igual("anclas leidas", sorted(anclas), sorted(
        ["VENTANA_ANCHO", "VENTANA_ALTO", "LIENZO_ANCHO", "MARGEN", "ESCALA", "LONA",
         "FRACCION", "DESPLAZAMIENTO"]))
    if "REDONDEADO" in anclas:
        fallos.append("un literal de objeto se declaro evaluable")
    igual("constante", evaluar(anclas, "LONA"), 768 * (1725 / 1344))
    igual("Math.floor", evaluar(anclas, "MARGEN"), 108.0)
    igual("funcion cubo", evaluar(anclas, "FRACCION", [0.5])[0], 0.125)
    igual("funcion pulso", evaluar(anclas, "DESPLAZAMIENTO", [1.0])[0], 17.4)
    conforme = comparar(None, {"LONA": 768 * (1725 / 1344), "FRACCION":
                               {"puntos": [0.0, 0.5, 1.0], "valores": [0.0, 0.125, 1.0]}},
                        anclas=anclas)
    igual("conforme rc", conforme["rc"], RC_OK)
    divergente = comparar(None, {"LONA": 985.714176}, anclas=anclas)
    igual("deriva rc", divergente["rc"], RC_DIVERGE)
    cerca = comparar(None, {"LONA": 985.714176 + 1e-4}, tolerancia=1e-3, anclas=anclas)
    igual("tolerancia declarada", cerca["rc"], RC_OK)
    faltante = comparar(None, {"NO_EXISTE": 1.0}, anclas=anclas)
    igual("ancla ausente no mide", faltante["rc"], RC_NO_MEDIDO)
    igual("sin fuente", comparar(None, {"X": 1.0})["rc"], RC_NO_MEDIDO)
    residuo = residuo_de_redondeo(985.714176)
    igual("residuo floor", residuo["floor"]["residuo"], 0.714176)
    igual("residuo round", residuo["round"]["residuo"], -0.285824)
    for mensaje in fallos:
        print(f"FALLO {mensaje}", file=sys.stderr)
    if fallos:
        print(f"AUTOTEST NO OK: {len(fallos)} ancla(s)", file=sys.stderr)
        return RC_DIVERGE
    print("AUTOTEST OK: 15 anclas de oraculo")
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fuente", help="declaraciones TypeScript a evaluar")
    parser.add_argument("--referencia", help="JSON {nombre: valor} o {nombre: {puntos, valores}}")
    parser.add_argument("--tolerancia", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", "--autotest", dest="self_test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _autotest()
    if not args.fuente or not args.referencia:
        print("uso: anchor_oracle.py --fuente F.ts --referencia ref.json [--tolerancia T] [--json]",
              file=sys.stderr)
        return RC_ARITY
    from pathlib import Path

    texto = Path(args.fuente).read_text()
    referencia = json.loads(Path(args.referencia).read_text())
    recibo = comparar(texto, referencia, tolerancia=args.tolerancia)
    if args.json:
        print(json.dumps(recibo, indent=2, sort_keys=True))
    elif recibo["rc"] == RC_OK:
        total = sum(f["puntos"] for f in recibo["anclas"])
        print(f"CONFORME · {len(recibo['anclas'])} ancla(s) · {total} punto(s) · "
              f"peor error absoluto {max(f['peor_abs'] for f in recibo['anclas']):.3e}")
    elif recibo["rc"] == RC_DIVERGE:
        for fila in recibo["anclas"]:
            if not fila["ok"]:
                cuanto = fila["cuantizacion"] or "ninguna"
                print(f"DIVERGE {fila['ancla']} · punto {fila['peor_punto']} · "
                      f"obtenido {fila['obtenido']!r} esperado {fila['esperado']!r} · "
                      f"cuantizacion {cuanto} · "
                      f"residuo {fila['residuo_px']['round']['residuo']:+.6f}")
    else:
        print(f"NO_MEDIDO · {recibo['causa']} · {recibo['detalle']}", file=sys.stderr)
    return recibo["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
