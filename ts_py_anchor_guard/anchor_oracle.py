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
import subprocess
import sys

RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20


class FuenteIlegible(ValueError):
    """The source cannot be read as the declaration subset this module claims to read."""


class AnclaDesconocida(KeyError):
    """The reference names an anchor the source does not declare."""


# --------------------------------------------------------------------- lectura

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_ABRE, _CIERRA = set("([{"), set(")]}")
# `as const` is a TypeScript assertion, not arithmetic: it must disappear before parsing
# and it cannot change the value, so dropping it loses nothing.
_AS_CONST = re.compile(r"\s+as\s+const\b")
_CLAVE_DECLARACION = ("const", "export", "function", "class", "type", "interface",
                      "import", "let", "enum")


def _mascara(texto: str) -> bytearray:
    """1 where the character is code, 0 inside a comment, a string or a template literal.

    Counting braces on raw text lies the moment one string carries one: a real engine's
    `` `translateY(${dy}px) scale(${escala})` `` opens two levels that never close, and a
    `//` comment holding `}` would close a block. Masking first keeps the structure
    honest; a template interpolation is masked with its literal so `${...}` cannot
    unbalance a declaration.
    """
    m = bytearray(b"\x01") * len(texto)
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] != "\n":
                m[i] = 0
                i += 1
        elif c == "/" and i + 1 < n and texto[i + 1] == "*":
            fin = texto.find("*/", i + 2)
            fin = n if fin < 0 else fin + 2
            while i < fin:
                if texto[i] != "\n":
                    m[i] = 0
                i += 1
        elif c in "'\"`":
            i = _cerrar_cadena(texto, m, i)
        else:
            i += 1
    return m


def _cerrar_cadena(texto: str, m: bytearray, i: int) -> int:
    comilla, n = texto[i], len(texto)
    j = i
    while j < n:
        m[j] = 0
        if texto[j] == "\\" and j + 1 < n:
            m[j + 1] = 0
            j += 2
            continue
        if texto[j] == comilla:
            return j + 1
        j += 1
    return n


def _es_palabra(texto: str, i: int, palabra: str) -> bool:
    if not texto.startswith(palabra, i):
        return False
    fin = i + len(palabra)
    if fin < len(texto) and (texto[fin].isalnum() or texto[fin] in "_$"):
        return False
    return i == 0 or not (texto[i - 1].isalnum() or texto[i - 1] in "_$")


def _empieza_declaracion(resto: str) -> bool:
    if resto.startswith("}"):
        return True
    return any(_es_palabra(resto, 0, palabra) for palabra in _CLAVE_DECLARACION)


def _fin_de_cuerpo(texto: str, m: bytearray, i: int) -> int:
    """Index of the `;` that ends a body, or of the line break that ends it by ASI."""
    n, prof = len(texto), 0
    while i < n:
        if not m[i]:
            i += 1
            continue
        c = texto[i]
        if c in _ABRE:
            prof += 1
        elif c in _CIERRA:
            prof -= 1
        elif prof == 0 and c == ";":
            return i
        elif prof == 0 and c == "\n" and _empieza_declaracion(texto[i + 1:].lstrip()):
            return i
        i += 1
    return n


def _leer_declaracion(texto: str, m: bytearray, i: int):
    """`(nombre, cuerpo, fin)` for the `const` whose keyword starts at `i`, else None."""
    j = i + len("const")
    while j < len(texto) and texto[j] in " \t":
        j += 1
    idn = _IDENT.match(texto, j)
    if not idn:
        return None                       # `const {a, b} = ...`: destructuring, not an anchor
    nombre, j, prof = idn.group(), idn.end(), 0
    while j < len(texto):
        if not m[j]:
            j += 1
            continue
        c = texto[j]
        if c in _ABRE:
            prof += 1
        elif c in _CIERRA:
            prof -= 1
        elif prof == 0 and c == "=":
            break
        elif prof == 0 and c == ";":
            return None                   # `declare const X: number;` has no body
        j += 1
    else:
        return None
    inicio = j + 1
    fin = _fin_de_cuerpo(texto, m, inicio)
    return nombre, texto[inicio:fin].strip(), fin


_FLECHA = re.compile(
    r"^(?:\((?P<ps>[^()]*)\)|(?P<solo>[A-Za-z_$][\w$]*))[ \t]*(?::[^=]*)?=>[ \t]*(?P<cuerpo>.+)$",
    re.S)


def _parametros(ps: str) -> list[str]:
    trozos, prof, actual = [], 0, ""
    for c in ps:
        if c in _ABRE:
            prof += 1
        elif c in _CIERRA:
            prof -= 1
        if c == "," and prof == 0:
            trozos.append(actual)
            actual = ""
        else:
            actual += c
    trozos.append(actual)
    nombres = []
    for bruto in trozos:
        bruto = bruto.strip().rstrip("?").strip()
        if not bruto:
            continue
        corte = bruto.find(":")
        nombres.append((bruto[:corte] if corte > 0 else bruto).strip().rstrip("?").strip())
    return nombres


def extraer_anclas(texto: str) -> dict[str, dict]:
    """Declarations this module can evaluate honestly, keyed by name.

    Each entry is `{"tipo": "const" | "funcion", "cuerpo": str, "params": [...]}`. The
    reader is structural, not line-based, because a line-based one is wrong on real
    sources in three measured ways: it truncates a declaration whose arrow spans lines,
    it reads a return-annotated arrow (`(v: number): boolean => {`) as a constant, and it
    promotes variables declared *inside* a function body to module anchors.

    So: only declarations at brace depth 0 are anchors; a body runs to its `;` (or to the
    line break that ends it by ASI), not to the end of the line; an arrow with a block
    body is skipped, never guessed; `as const` is stripped. Object and array literals are
    kept as values so `NAME.field` resolves, and a block-bodied function is `NO_MEDIDO`
    rather than a constant -- an anchor missing from the mapping is how the caller learns
    the reader did not measure it.
    """
    m = _mascara(texto)
    anclas: dict[str, dict] = {}
    i, n, prof = 0, len(m), 0
    while i < n:
        if not m[i]:
            i += 1
            continue
        c = texto[i]
        if c in _ABRE:
            prof += 1
        elif c in _CIERRA:
            prof -= 1
        elif prof == 0 and c == "c" and _es_palabra(texto, i, "const"):
            leida = _leer_declaracion(texto, m, i)
            if leida is not None:
                nombre, cuerpo, fin = leida
                if cuerpo:
                    flecha = _FLECHA.match(cuerpo)
                    if flecha:
                        params = _parametros(
                            flecha.group("ps") if flecha.group("ps") is not None
                            else flecha.group("solo"))
                        resto = flecha.group("cuerpo").strip()
                        if not resto.startswith("{"):   # block body: no anchor, and measured
                            anclas[nombre] = {"tipo": "funcion", "cuerpo": resto,
                                              "params": params}
                    else:
                        anclas[nombre] = {"tipo": "const", "cuerpo": cuerpo, "params": []}
                i = fin
                continue
        i += 1
    return anclas


# ------------------------------------------------------------------ evaluacion

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)|([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
                    r"|(\?\?|\*\*|[-+*/(),:?{}[\]]))")

_CONSTANTES = {"Math.PI": math.pi, "Math.E": math.e}


def _num(valor):
    """Arithmetic operands are numbers: a dict or a list here is a scope error, not a value."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise FuenteIlegible(f"no es un numero: {valor!r}")
    return float(valor)

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

    def evaluar(self):
        valor = self._expresion()
        if self.i != len(self.tokens):
            raise FuenteIlegible(f"sobra {self.tokens[self.i:]}")
        return valor

    def _expresion(self):
        """`a ?? b` returns `b` only when `a` is undefined, which is `None` here."""
        valor = self._suma()
        while self._mirar()[1] == "??":
            self._tomar()
            otro = self._suma()
            if valor is None:
                valor = otro
        return valor

    def _suma(self):
        valor = self._producto()
        while self._mirar()[1] in ("+", "-"):
            op = self._tomar()[1]
            derecho = self._producto()
            valor = _num(valor) + _num(derecho) if op == "+" else _num(valor) - _num(derecho)
        return valor

    def _producto(self):
        valor = self._potencia()
        while self._mirar()[1] in ("*", "/"):
            op = self._tomar()[1]
            derecho = self._potencia()
            valor = _num(valor) * _num(derecho) if op == "*" else _num(valor) / _num(derecho)
        return valor

    def _potencia(self):
        """`**` binds tighter than `*` and is right-associative: `3 * t ** 2` is `3*(t**2)`."""
        base = self._unario()
        if self._mirar()[1] == "**":
            self._tomar()
            return _num(base) ** _num(self._potencia())
        return base

    def _unario(self):
        if self._mirar()[1] == "-":
            self._tomar()
            return -_num(self._unario())
        if self._mirar()[1] == "+":
            self._tomar()
            return _num(self._unario())
        return self._atomo()

    def _bloque(self, cierra: str) -> list:
        """Comma-separated values up to `cierra`: the body of an object or array literal."""
        salida = []
        if self._mirar()[1] == cierra:
            self._tomar(cierra)
            return salida
        while True:
            salida.append(self._expresion())
            if self._mirar()[1] == ",":
                self._tomar()
                if self._mirar()[1] == cierra:
                    self._tomar(cierra)
                    return salida
                continue
            self._tomar(cierra)
            return salida

    def _objeto(self):
        self._tomar("{")
        salida = {}
        if self._mirar()[1] == "}":
            self._tomar("}")
            return salida
        while True:
            tipo, clave = self._mirar()
            if tipo not in ("nombre", "num"):
                raise FuenteIlegible(f"clave no soportada: {clave!r}")
            self._tomar()
            self._tomar(":")
            salida[str(clave)] = self._expresion()
            if self._mirar()[1] == ",":
                self._tomar()
                if self._mirar()[1] == "}":
                    self._tomar("}")
                    return salida
                continue
            self._tomar("}")
            return salida

    def _atomo(self):
        tipo, valor = self._mirar()
        if tipo == "num":
            self._tomar()
            return float(valor)
        if tipo == "op" and valor == "(":
            self._tomar()
            dentro = self._expresion()
            self._tomar(")")
            return dentro
        if tipo == "op" and valor == "{":
            return self._objeto()
        if tipo == "op" and valor == "[":
            self._tomar("[")
            return self._bloque("]")
        if tipo == "nombre":
            self._tomar()
            if self._mirar()[1] == "(":
                self._tomar()
                args = []
                if self._mirar()[1] != ")":
                    args.append(self._expresion())
                    while self._mirar()[1] == ",":
                        self._tomar()
                        args.append(self._expresion())
                self._tomar(")")
                if valor not in _FUNCIONES:
                    raise FuenteIlegible(f"funcion no soportada: {valor}")
                return _num(_FUNCIONES[valor](*[_num(a) for a in args]))
            if valor in _CONSTANTES:
                return float(_CONSTANTES[valor])
            if valor in self.entorno:
                return self.entorno[valor]
            raise FuenteIlegible(f"nombre no declarado: {valor}")
        raise FuenteIlegible(f"token inesperado: {valor!r}")


class _Entorno(dict):
    """Scope that resolves a constant on demand, memoised and cycle-checked."""

    def __init__(self, anclas: dict[str, dict], cache: dict[str, float],
                 en_curso: set[str]):
        super().__init__()
        self._anclas, self._cache, self._en_curso = anclas, cache, en_curso

    def __contains__(self, nombre) -> bool:
        if dict.__contains__(self, nombre):
            return True
        base = nombre.partition(".")[0]
        return base in self._anclas and self._anclas[base]["tipo"] != "funcion"

    def __getitem__(self, nombre):
        if dict.__contains__(self, nombre):
            return dict.__getitem__(self, nombre)
        return _resolver(self._anclas, nombre, self._cache, self._en_curso)


def _miembro(valor, resto: str, completo: str):
    """Walk `a.b.c` over an evaluated literal: a member that is not there is not zero."""
    for parte in resto.split("."):
        if isinstance(valor, dict) and parte in valor:
            valor = valor[parte]
        elif isinstance(valor, list) and parte.isdigit() and int(parte) < len(valor):
            valor = valor[int(parte)]
        else:
            raise FuenteIlegible(f"{completo} no resuelve: no existe {parte!r}")
    return valor


def _resolver(anclas: dict[str, dict], nombre: str, cache: dict, en_curso: set[str]):
    if nombre in cache:
        return cache[nombre]
    base, _, resto = nombre.partition(".")
    if base not in anclas:
        raise FuenteIlegible(f"nombre no declarado: {base}")
    if base in en_curso:
        raise FuenteIlegible(f"ciclo de constantes en {base}")
    ancla = anclas[base]
    if ancla["tipo"] == "funcion":
        raise FuenteIlegible(f"{base} es una funcion: se evalua en puntos, no como constante")
    en_curso.add(base)
    valor = _Evaluador(_tokenizar(_AS_CONST.sub("", ancla["cuerpo"])),
                       _Entorno(anclas, cache, en_curso)).evaluar()
    en_curso.discard(base)
    cache[base] = valor
    return valor if not resto else _miembro(valor, resto, nombre)


def evaluar(anclas: dict[str, dict], nombre: str, puntos=None,
            cache: dict | None = None):
    """Evaluate one anchor. A function is evaluated at each of `puntos`.

    `nombre` may be a path (`CANVAS.ancho`, `rect.top`): the base is evaluated and the
    remaining members are walked, so a source that returns a layout object is comparable
    field by field instead of being written off as opaque. A point of `None` means the
    call site passes no argument, which is the only honest way to reproduce a JS
    `param ?? fallback` default.
    """
    base, _, resto = nombre.partition(".")
    if base not in anclas:
        raise AnclaDesconocida(nombre)
    ancla = anclas[base]
    cache = {} if cache is None else cache
    constantes = _Entorno(anclas, cache, set())
    if ancla["tipo"] == "const":
        if puntos:
            raise FuenteIlegible(f"{nombre} es una constante, no se evalua en puntos")
        valor = _Evaluador(_tokenizar(_AS_CONST.sub("", ancla["cuerpo"])),
                           constantes).evaluar()
        return valor if not resto else _miembro(valor, resto, nombre)
    if not puntos:
        puntos = [0.0]
    if len(ancla["params"]) != 1:
        raise FuenteIlegible(
            f"{base} declara {len(ancla['params'])} parametros; este lector evalua funciones de uno")
    salida = []
    tokens = _tokenizar(_AS_CONST.sub("", ancla["cuerpo"]))
    for u in puntos:
        entorno = _Entorno(anclas, cache, set())
        entorno[ancla["params"][0]] = None if u is None else float(u)
        valor = _Evaluador(tokens, entorno).evaluar()
        salida.append(valor if not resto else _miembro(valor, resto, nombre))
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
             anclas: dict[str, dict] | None = None, vivos: dict | None = None,
             backend: str = "estatico", exigir_cobertura_total: bool = False) -> dict:
    """Compare every anchor the reference names against the value it expects.

    `referencia` is `{nombre: valor}` for constants or
    `{nombre: {"puntos": [...], "valores": [...]}}` for functions. A `valor` that is a
    literal (a list, an object) is not a measurement: it is reported per anchor with the
    path that would measure it (`RAMPA.0`, `CUADRO.ancho`), never coerced and never allowed
    to abort the anchors that did come back as numbers. The receipt lists, per
    anchor: how many points were compared, the absolute worst error, its relative value
    and -- when it diverges -- the rounding residual of the measured value plus the policy
    (`floor` / `round` / `ceil`) that reproduces the number the port computed. `cobertura`
    publishes the scope: how many anchors the source declares, how many were compared, and
    which ones the reference never named.

    `vivos` carries reference values measured by executing the source (see `live_oracle`);
    when given they replace this module's arithmetic, which is the point: a port compared
    against a second implementation of the same formula can agree for the wrong reason.
    The receipt names the `backend` that produced the numbers.

    `exigir_cobertura_total` turns `cobertura.omitidas` from a report into a defect: a
    repository that signs a manifest saying every anchor it declares is accounted for gets
    `RC 2 · COBERTURA_INCOMPLETA` when one is not, and `cobertura.exigida` says in the
    receipt which of the two readings applies.
    """
    if not isinstance(referencia, dict):
        return {"rc": RC_NO_MEDIDO, "causa": "INSUMO_ILEGIBLE",
                "detalle": f"la referencia no es un objeto {{nombre: valor}}, "
                           f"es {type(referencia).__name__}", "anclas": [],
                "no_evaluables": [], "backend": backend}
    # The source side already refuses to conform when it declares no anchors; the reference
    # side did not, so `{}` compared nothing and came back `RC_OK` -- a green that measured
    # zero anchors. Two sides of one comparison take the same guard.
    if not referencia:
        return {"rc": RC_NO_MEDIDO, "causa": "REFERENCIA_VACIA",
                "detalle": "la referencia no nombra ninguna ancla: no hay nada que comparar",
                "anclas": [], "no_evaluables": [], "backend": backend}
    if anclas is None:
        if not texto:
            return {"rc": RC_NO_MEDIDO, "causa": "SIN_FUENTE",
                    "detalle": "sin fuente TypeScript que evaluar", "anclas": [],
                    "no_evaluables": [], "backend": backend}
        anclas = extraer_anclas(texto)
    if not anclas:
        return {"rc": RC_NO_MEDIDO, "causa": "SIN_ANCLAS",
                "detalle": "la fuente no declara ninguna ancla evaluable", "anclas": [],
                "no_evaluables": [], "backend": backend}
    filas, divergen, no_medidas, no_evaluables, cache = [], 0, [], [], {}
    for nombre, esperado in referencia.items():
        if nombre.partition(".")[0] not in anclas:
            no_medidas.append(nombre)
            continue
        try:
            if isinstance(esperado, dict):
                puntos = [None if p is None else float(p) for p in esperado["puntos"]]
                valores = [float(v) for v in esperado["valores"]]
            else:
                puntos, valores = [], [float(esperado)]
        except (KeyError, TypeError, ValueError):
            # The source side already refuses to compare a literal; the reference side
            # used to raise out of `float()` and take the whole receipt with it, so one
            # array in a production port reported nothing about the anchors that did
            # match. Same guard, both sides of the comparison.
            no_evaluables.append({"ancla": nombre, "motivo": (
                f"la referencia da {type(esperado).__name__}: nombra un campo o un "
                f"indice (`{nombre}.campo`, `{nombre}.0`)")})
            continue
        try:
            if vivos is None:
                obtenidos = evaluar(anclas, nombre, puntos, cache)
            else:
                obtenidos = vivos[nombre]
                if any(o is None for o in obtenidos):
                    raise FuenteIlegible("el oraculo vivo no da un numero en ese punto")
        except (FuenteIlegible, ArithmeticError, TypeError, ValueError) as fallo:
            no_evaluables.append({"ancla": nombre, "motivo": str(fallo)})
            continue
        if not isinstance(obtenidos, list):
            obtenidos = [obtenidos]
        # A literal (object, list) is not a number: comparing it would invent a value, so
        # the caller is told to name a field instead.
        numeros = [o for o in obtenidos
                   if isinstance(o, (int, float)) and not isinstance(o, bool)]
        if len(numeros) != len(obtenidos):
            no_evaluables.append({"ancla": nombre,
                                  "motivo": "devuelve un literal: nombra un campo con `nombre.campo`"})
            continue
        obtenidos = numeros
        fila = {"ancla": nombre, "tipo": anclas[nombre.partition(".")[0]]["tipo"],
                "puntos": len(obtenidos),
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
    # A green over a hand-picked subset of the anchors is still a measurement of that
    # subset and nothing else, so the receipt says which names it never looked at: on a
    # real 7-anchor engine the first dogfooding run returned `rc 0` over 3 of them and no
    # field carried the other 4. `omitidas` is that field. It reports, it does not fail:
    # a reference is allowed to be a subset, it is not allowed to be silently smaller.
    cubiertas = {f["ancla"].partition(".")[0] for f in filas}
    cubiertas.update(f["ancla"].partition(".")[0] for f in no_evaluables)
    cobertura = {"declaradas": len(anclas), "comparadas": len(filas),
                 "omitidas": sorted(n for n in anclas if n not in cubiertas),
                 "exigida": bool(exigir_cobertura_total)}
    if no_medidas:
        return {"rc": RC_NO_MEDIDO, "causa": "ANCLA_NO_DECLARADA",
                "detalle": f"la fuente no declara {', '.join(sorted(no_medidas))}",
                "anclas": filas, "no_evaluables": no_evaluables, "backend": backend,
                "cobertura": cobertura}
    # A divergence is a measurement and outranks a gap; a gap never degrades to conforming.
    if divergen:
        return {"rc": RC_DIVERGE, "causa": "DIVERGE",
                "detalle": f"{divergen} punto(s) fuera de tolerancia {tolerancia:g}",
                "tolerancia": tolerancia, "anclas": filas,
                "no_evaluables": no_evaluables, "backend": backend,
                "cobertura": cobertura}
    if no_evaluables:
        nombres = ", ".join(f["ancla"] for f in no_evaluables)
        return {"rc": RC_NO_MEDIDO, "causa": "ANCLA_NO_EVALUABLE",
                "detalle": f"fuera del subconjunto legible: {nombres}",
                "tolerancia": tolerancia, "anclas": filas,
                "no_evaluables": no_evaluables, "backend": backend,
                "cobertura": cobertura}
    # A subset is reported and allowed, because one invocation is allowed to measure one
    # question. A repository that signs a manifest saying otherwise gets a gap instead of a
    # green: an anchor nobody declared how to read is indistinguishable from an anchor that
    # was renamed, and both are absences that a gate must not wave through.
    if exigir_cobertura_total and cobertura["omitidas"]:
        return {"rc": RC_NO_MEDIDO, "causa": "COBERTURA_INCOMPLETA",
                "detalle": f"la cobertura exigida omite {', '.join(cobertura['omitidas'])}",
                "tolerancia": tolerancia, "anclas": filas,
                "no_evaluables": no_evaluables, "backend": backend,
                "cobertura": cobertura}
    return {"rc": RC_OK, "causa": "", "detalle": "", "tolerancia": tolerancia,
            "anclas": filas, "no_evaluables": [], "backend": backend,
            "cobertura": cobertura}


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

# The three shapes that a line-based reader gets wrong on a real source, synthetic here so
# the regression travels with the code: a declaration whose arrow spans lines, an arrow
# annotated with its return type, and variables declared inside a function body.
_FUENTE_ESTRUCTURAL = """
export const CAJA = { ancho: 1080, alto: 1920 } as const;
export const VIEW = { ancho: 864, alto: 960 } as const;
export const rect = (y?: number) => ({
  left: (CAJA.ancho - VIEW.ancho) / 2,
  top: y ?? (CAJA.alto - VIEW.alto) / 2,
  width: VIEW.ancho,
  height: VIEW.alto,
});
export const esNodo = (v: number): boolean => {
  const m = v / 1.2;
  return Math.abs(m - Math.round(m)) * 1.2 < 0.15;
};
export const cerca = (v: number) =>
  VIEW.ancho.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
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
         "FRACCION", "DESPLAZAMIENTO", "REDONDEADO"]))
    igual("miembro de objeto", evaluar(anclas, "REDONDEADO.ancho"), 986.0)
    igual("constante", evaluar(anclas, "LONA"), 768 * (1725 / 1344))
    igual("Math.floor", evaluar(anclas, "MARGEN"), 108.0)
    igual("funcion cubo", evaluar(anclas, "FRACCION", [0.5])[0], 0.125)
    igual("funcion pulso", evaluar(anclas, "DESPLAZAMIENTO", [1.0])[0], 17.4)
    conforme = comparar(None, {"LONA": 768 * (1725 / 1344), "FRACCION":
                               {"puntos": [0.0, 0.5, 1.0], "valores": [0.0, 0.125, 1.0]}},
                        anclas=anclas)
    igual("conforme rc", conforme["rc"], RC_OK)
    igual("recibo sin huecos", conforme["no_evaluables"], [])
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

    # Structural reading: depth 0 only, block bodies skipped, `as const` dropped, and a
    # function that returns a literal comparable field by field.
    est = extraer_anclas(_FUENTE_ESTRUCTURAL)
    igual("anclas estructurales", sorted(est), ["CAJA", "VIEW", "cerca", "rect"])
    if "m" in est:
        fallos.append("una variable local se leyo como ancla de modulo")
    if "esNodo" in est:
        fallos.append("una funcion con cuerpo de bloque se leyo como ancla")
    igual("campo de objeto devuelto", evaluar(est, "rect.left")[0], 108.0)
    igual("campo por defecto", evaluar(est, "rect.top", [None])[0], 480.0)
    igual("campo con argumento", evaluar(est, "rect.top", [500.0])[0], 500.0)
    sin_defecto = comparar(None, {"rect.top": {"puntos": [0.0], "valores": [480.0]}},
                           anclas=est)
    igual("?? no se ignora", sin_defecto["rc"], RC_DIVERGE)
    no_leible = comparar(None, {"cerca": {"puntos": [1.0], "valores": [1.8]}}, anclas=est)
    igual("declarada pero fuera del subconjunto", no_leible["rc"], RC_NO_MEDIDO)
    igual("hueco nombrado", no_leible["causa"], "ANCLA_NO_EVALUABLE")
    igual("hueco en el recibo", [f["ancla"] for f in no_leible["no_evaluables"]], ["cerca"])
    for mensaje in fallos:
        print(f"FALLO {mensaje}", file=sys.stderr)
    if fallos:
        print(f"AUTOTEST NO OK: {len(fallos)} ancla(s)", file=sys.stderr)
        return RC_DIVERGE
    print("AUTOTEST OK: 33 anclas de oraculo")
    return RC_OK


def medir_vivos(texto: str, referencia: dict, backend: str = "auto"):
    """`(vivos, nombre del backend, fallo, aviso)`; an empty `fallo` means it ran or was
    not asked, and a non-empty `aviso` names the reader that was chosen and did not run.

    `auto` that finds no node falls back to this module's arithmetic without a word, which
    is what `auto` means; `node` that finds none is a gap, because a mode that was asked
    for and could not run is not the other mode.

    A node that is there and cannot load the source -- `enum` and `namespace` are what
    TypeScript's strip-only mode refuses, and both are ordinary -- is the same gap in the
    reader as no node at all, so `auto` keeps going with the arithmetic it can run. The
    reason travels back as `aviso`, because a fallback that is not named is a weaker
    instrument wearing a stronger one's name. An explicit `node` still fails: that caller
    asked for the second implementation and does not get to receive the first.
    """
    if backend == "estatico":
        return None, "estatico", None, None
    from . import live_oracle

    nodo = live_oracle.version_de_nodo()
    if nodo is None:
        if backend == "node":
            return None, "estatico", ("SIN_ORACULO_VIVO", "node >= 22.6 no esta disponible"), None
        return None, "estatico", None, None
    vivos, motivo = live_oracle.medir(texto, referencia, nodo=nodo)
    if motivo:
        if backend == "node":
            return None, "estatico", ("ORACULO_VIVO_FALLO", motivo), None
        return None, "estatico", None, (f"node no leyo la fuente ({motivo}); "
                                        f"medido con el lector estatico")
    version = subprocess.run([nodo[0], "--version"], capture_output=True,
                             text=True).stdout.strip()
    return vivos, "node " + version, None, None


def main(argv: list[str] | None = None) -> int:
    from ._cli import InsumoFalta, ParserDeContrato, leer_texto, no_medido

    parser = ParserDeContrato(description=__doc__.splitlines()[0])
    parser.add_argument("--fuente", help="declaraciones TypeScript a evaluar")
    parser.add_argument("--referencia", help="JSON {nombre: valor} o {nombre: {puntos, valores}}")
    parser.add_argument("--tolerancia", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--censo", action="store_true",
                        help="listar las anclas que el lector ve, sin evaluar nada")
    parser.add_argument("--backend", choices=("auto", "node", "estatico"), default="auto",
                        help="quien produce los valores de referencia: node ejecuta la "
                             "fuente, estatico la evalua con este modulo")
    parser.add_argument("--self-test", "--autotest", dest="self_test", action="store_true")
    parser.add_argument("--manifest", help="JSON que declara los pares y sus mapeos: "
                                          "un recibo consolidado por repositorio")
    parser.add_argument("--exigir-cobertura-total", dest="exigir_cobertura_total",
                        action="store_true",
                        help="un ancla declarada que nadie midio es un hueco, no un verde")
    args = parser.parse_args(argv)
    if args.self_test:
        return _autotest()
    if args.manifest:
        if args.fuente or args.referencia or args.censo:
            print("uso: anchor_oracle.py --manifest M.json [--backend B] [--json]",
                  file=sys.stderr)
            return RC_ARITY
        from .manifiesto import correr

        return correr(args.manifest, backend=args.backend, json_out=args.json,
                      tolerancia=args.tolerancia,
                      exigir_cobertura_total=args.exigir_cobertura_total)
    if args.censo:
        if not args.fuente:
            print("uso: anchor_oracle.py --fuente F.ts --censo [--json]", file=sys.stderr)
            return RC_ARITY
        try:
            anclas = extraer_anclas(leer_texto(args.fuente, "fuente"))
        except InsumoFalta as exc:
            return no_medido("INSUMO_FALTA", str(exc))
        if args.json:
            print(json.dumps(anclas, indent=2, sort_keys=True))
            return RC_OK
        for nombre, ancla in anclas.items():
            primero = ancla["cuerpo"].splitlines()[0]
            print(f"{nombre} · {ancla['tipo']} · {primero}")
        print(f"CENSO · {len(anclas)} ancla(s) · las funciones con cuerpo de bloque y las "
              f"variables locales no se leen", file=sys.stderr)
        return RC_OK
    if not args.fuente or not args.referencia:
        print("uso: anchor_oracle.py --fuente F.ts --referencia ref.json [--tolerancia T] [--json]\n"
              "     anchor_oracle.py --manifest M.json [--backend auto|node|estatico] [--json]",
              file=sys.stderr)
        return RC_ARITY
    try:
        texto = leer_texto(args.fuente, "fuente")
        referencia = json.loads(leer_texto(args.referencia, "referencia"))
    except InsumoFalta as exc:
        return no_medido("INSUMO_FALTA", str(exc))
    except json.JSONDecodeError as exc:
        return no_medido("INSUMO_ILEGIBLE", f"referencia {args.referencia!r}: {exc}")
    vivos, backend, fallo, aviso = medir_vivos(texto, referencia, args.backend)
    if fallo:
        print(f"NO_MEDIDO · {fallo[0]} · {fallo[1]}", file=sys.stderr)
        return RC_NO_MEDIDO
    recibo = comparar(texto, referencia, tolerancia=args.tolerancia, vivos=vivos,
                      backend=backend,
                      exigir_cobertura_total=args.exigir_cobertura_total)
    if aviso:
        recibo["aviso"] = aviso
    if args.json:
        print(json.dumps(recibo, indent=2, sort_keys=True))
    elif recibo["rc"] == RC_OK:
        total = sum(f["puntos"] for f in recibo["anclas"])
        print(f"CONFORME · {len(recibo['anclas'])} ancla(s) · {total} punto(s) · "
              f"peor error absoluto {max(f['peor_abs'] for f in recibo['anclas']):.3e} · "
              f"oraculo {recibo['backend']}")
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
    from ._cli import correr

    raise SystemExit(correr(main))
