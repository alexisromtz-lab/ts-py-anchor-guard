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
    const EVENTO = "$insight_alert_opened";      // text: compared by exact equality
    const CAJA = { ancho: 1080, alto: 1920 };    // object literal, read field by field

It evaluates them without a TypeScript toolchain, a browser, or an E2E suite, and
compares against values supplied by the Python side. Text is a value too: an event name
or an error code that a port renames is as broken as a formula that drifts, and it has no
relative error, so it compares by equality and never through `tolerancia`. What it does
NOT evaluate is anything it cannot read honestly -- template literals, block bodies,
imports, enums, stateful code -- which is reported as `NO_MEDIDO` (exit code 2) and never
as conforming. `--censo` says how much of a file that subset covers, with the reader's own
motives; on three real `constants` files at fixed commits it covered 13 of 72 declarations
before text and 56 of 72 after, and the script that measured it is the tool itself.

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


def _sin_comentarios(cuerpo: str) -> str:
    """The body with `//` and `/* */` removed, strings and template literals intact.

    A comment carries no value, so dropping it cannot change what a declaration declares.
    Leaving it in meant the tokeniser refused the declaration: on three real `constants`
    files, 17 of 59 unreadable declarations failed only because somebody had written
    `LIMIT = 30 // seconds` or `{ /* see RFC */ a: 1 }`. That is the reader reporting
    itself as the subject. An `http://` inside a string is not a comment, which is why
    this walks the text instead of substituting on a regex.
    """
    salida, i, n = [], 0, len(cuerpo)
    while i < n:
        c = cuerpo[i]
        if c in "'\"`":
            j = i + 1
            while j < n:
                if cuerpo[j] == "\\":
                    j += 2
                    continue
                if cuerpo[j] == c:
                    j += 1
                    break
                j += 1
            salida.append(cuerpo[i:j])
            i = min(j, n)
        elif c == "/" and i + 1 < n and cuerpo[i + 1] == "/":
            while i < n and cuerpo[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and cuerpo[i + 1] == "*":
            fin = cuerpo.find("*/", i + 2)
            i = n if fin < 0 else fin + 2
            salida.append(" ")
        else:
            salida.append(c)
            i += 1
    return "".join(salida)


_ANTES_DE_REGEX = set("=(,:[!&|?{};+-*%~^>")
_REGEX_TRAS_PALABRA = {"return", "typeof", "case", "in", "of", "delete", "void",
                       "instanceof", "new", "do", "else", "yield", "await"}


def _es_inicio_regex(texto: str, i: int, m: bytearray | None = None) -> bool:
    """`/` at `i` opens a regular expression, not a division.

    A regex literal is a value with text inside, and the mask used to read it as code:
    `SECURE_URL_REGEX = /[\\w'()*+,;=]/gi` in a real `constants` file opened a string at the
    `'` and swallowed 27 of the 67 declarations that followed. The guess is the lexical
    one -- what came before the slash decides -- and it is deliberately conservative: `<`
    is not in the set, so a JSX closing tag is never mistaken for a regex.
    """
    j = i - 1
    while j >= 0 and (texto[j].isspace() or (m is not None and not m[j])):
        j -= 1
    if j < 0:
        return True
    if texto[j] in _ANTES_DE_REGEX:
        return True
    k = j
    while k >= 0 and (texto[k].isalnum() or texto[k] in "_$"):
        k -= 1
    return texto[k + 1:j + 1] in _REGEX_TRAS_PALABRA


def _saltar_regex(texto: str, i: int, m: bytearray | None = None) -> int:
    """Mask the regex literal that opens at `i`; return the index after its closing slash.

    A literal that runs to the end of the line was not a regex at all: the caller is given
    the character after the slash and nothing beyond it is masked, so a wrong guess costs
    one character instead of a file.
    """
    def apaga(k: int) -> None:
        if m is not None:
            m[k] = 0

    apaga(i)
    j, n, en_clase = i + 1, len(texto), False
    while j < n:
        c = texto[j]
        if c == "\n":
            return i + 1
        apaga(j)
        if c == "\\" and j + 1 < n:
            apaga(j + 1)
            j += 2
            continue
        if c == "[":
            en_clase = True
        elif c == "]":
            en_clase = False
        elif c == "/" and not en_clase:
            return j + 1
        j += 1
    return n


def _mascara(texto: str) -> bytearray:
    """1 where the character is code, 0 inside a comment, a string, a regex or a template.

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
        elif c == "/" and _es_inicio_regex(texto, i, m):
            i = _saltar_regex(texto, i, m)
        elif c in "'\"`":
            i = _cerrar_cadena(texto, m, i)
        else:
            i += 1
    return m


def _cerrar_cadena(texto: str, m: bytearray, i: int) -> int:
    """Mask the literal that opens at `i`, closing quote included; return the index after it.

    The opening quote used to be masked and returned from in the same step, so the *body*
    of every string was left looking like code: a `}` inside `"cero}"` closed a level, and
    the `//` of `"https://…"` opened a comment to the end of the line. That is why 31 of 59
    refused declarations in three real `constants` files were refused by the reader and not
    by the language.
    """
    comilla, n = texto[i], len(texto)
    m[i] = 0
    j = i + 1
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


def _leer_declaracion(texto: str, m: bytearray, i: int, falta: dict | None = None):
    """`(nombre, cuerpo, fin)` for the `const` whose keyword starts at `i`, else None.

    `falta`, when given, is filled with the name and the motive of a declaration that was
    seen and refused, so the census can publish a denominator instead of counting only
    what it read.
    """
    def no_leida(por_que):
        if falta is not None:
            falta["por_que"] = por_que
        return None

    j = i + len("const")
    while j < len(texto) and texto[j] in " \t":
        j += 1
    idn = _IDENT.match(texto, j)
    if not idn:
        return no_leida("sin nombre: destructuring, no un ancla")
    nombre, j, prof = idn.group(), idn.end(), 0
    if falta is not None:
        falta["nombre"] = nombre
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
            return no_leida("tipo sin valor (`declare const X: T;`)")
        j += 1
    else:
        return no_leida("sin `=` ni `;` hasta el final del archivo")
    inicio = j + 1
    fin = _fin_de_cuerpo(texto, m, inicio)
    return nombre, _sin_comentarios(texto[inicio:fin]).strip(), fin


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


def extraer_anclas(texto: str, motivos: dict[str, str] | None = None) -> dict[str, dict]:
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

    `motivos`, when given, receives one entry per declaration the reader saw and refused,
    keyed by name (or by `const@L<line>` when the name itself is missing): the denominator
    that `--censo` needs in order to say how much of a file this subset covers.
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
            falta: dict = {}
            leida = _leer_declaracion(texto, m, i, falta)
            if leida is None:
                if motivos is not None:
                    clave = falta.get("nombre") or f"const@L{texto.count(chr(10), 0, i) + 1}"
                    motivos[clave] = falta.get("por_que", "sin leer")
                i += 1
                continue
            nombre, cuerpo, fin = leida
            if cuerpo:
                flecha = _FLECHA.match(cuerpo)
                if flecha:
                    params = _parametros(
                        flecha.group("ps") if flecha.group("ps") is not None
                        else flecha.group("solo"))
                    resto = flecha.group("cuerpo").strip()
                    if resto.startswith("{"):   # block body: no anchor, and measured
                        if motivos is not None:
                            motivos[nombre] = "funcion con cuerpo de bloque"
                    else:
                        anclas[nombre] = {"tipo": "funcion", "cuerpo": resto,
                                          "params": params}
                else:
                    anclas[nombre] = {"tipo": "const", "cuerpo": cuerpo, "params": []}
            elif motivos is not None:
                motivos[nombre] = "declaracion sin valor"
            i = fin
            continue
        i += 1
    return anclas


def censo(anclas: dict[str, dict], motivos: dict[str, str]) -> dict:
    """How much of a source the reader covers, and what it says about the rest.

    Two different numbers, and neither is a green: `leidas` is what the reader returned at
    all, `evaluables` is what it can also turn into a value. A file where the reader
    returns 20 anchors and evaluates 3 is a file the instrument measures 15 % of, and the
    motives name which half of the silence is the language and which half is the reader.
    """
    evaluables, fallos, cache = [], {}, {}
    for nombre, ancla in anclas.items():
        try:
            if ancla["tipo"] == "const":
                evaluar(anclas, nombre, cache=cache)
            else:
                _tokenizar(_AS_CONST.sub("", ancla["cuerpo"]))
        except (FuenteIlegible, ArithmeticError, TypeError, ValueError) as fallo:
            fallos[nombre] = str(fallo)
            continue
        evaluables.append(nombre)
    declaradas = len(anclas) + len(motivos)
    return {"declaradas": declaradas, "leidas": len(anclas),
            "evaluables": len(evaluables),
            "cobertura": round(len(anclas) / declaradas, 4) if declaradas else None,
            "no_leidas": dict(sorted(motivos.items())),
            "no_evaluables": dict(sorted(fallos.items()))}


# ------------------------------------------------------------------ evaluacion

# `1_000_000` is the same number as `1000000`: the separator is syntax, not a digit, and
# refusing it made a real `constants` file unreadable for a reason the port cannot share.
_TOKEN = re.compile(r"\s*(?:(\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][-+]?\d+)?|\.\d[\d_]*)"
                    r"|(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
                    r"|([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
                    r"|(\?\?|\*\*|[-+*/(),:?{}[\]]))")

_CONSTANTES = {"Math.PI": math.pi, "Math.E": math.e}

# JS drops the backslash of an unknown escape (`"\q"` is `q`), so an unmapped one is the
# letter itself and not an error. `\u` and `\x` are decoded because they do carry a value.
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _desescapar(literal: str) -> str:
    """The text a string literal denotes, or a named refusal for an escape not decoded."""
    salida, i, fin = [], 1, len(literal) - 1
    while i < fin:
        c = literal[i]
        if c != "\\":
            salida.append(c)
            i += 1
            continue
        if i + 1 >= fin:
            raise FuenteIlegible("escape colgante al final de la cadena")
        marca = literal[i + 1]
        if marca in "ux":
            ancho = 4 if marca == "u" else 2
            hexa = literal[i + 2:i + 2 + ancho]
            if len(hexa) < ancho or any(h not in "0123456789abcdefABCDEF" for h in hexa):
                raise FuenteIlegible(f"escape no soportado: {literal[i:i + 2 + ancho]!r}")
            salida.append(chr(int(hexa, 16)))
            i += 2 + ancho
            continue
        salida.append(_ESCAPES.get(marca, marca))
        i += 2
    return "".join(salida)


def _num(valor):
    """Arithmetic operands are numbers: a dict, a list or a text here is a scope error."""
    if isinstance(valor, str):
        raise FuenteIlegible(
            f"texto en aritmetica: {valor!r} (la concatenacion y la comparacion de "
            f"cadenas no se evaluan; nombra el texto como ancla aparte)")
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise FuenteIlegible(f"no es un numero: {valor!r}")
    return float(valor)

def _clave(valor) -> str:
    """The property name a literal key denotes: `{ 1: x }` keys on `"1"`, not `"1.0"`."""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


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
    """Tokens of one expression: numbers, text, dotted names and operators.

    HUELLA-LECTOR-TEXTO-20261127: text is a token and a value, not a reader failure.
    """
    tokens, pos = [], 0
    while pos < len(expr):
        if expr[pos:].strip() == "":
            break
        m = _TOKEN.match(expr, pos)
        if not m:
            raise FuenteIlegible(f"no se puede tokenizar en {pos}: {expr[pos:pos + 20]!r}")
        num, cad, nombre, op = m.groups()
        if num is not None:
            tokens.append(("num", float(num.replace("_", ""))))
        elif cad is not None:
            tokens.append(("cad", _desescapar(cad)))
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
            if tipo not in ("nombre", "num", "cad"):
                raise FuenteIlegible(f"clave no soportada: {clave!r}")
            self._tomar()
            if self._mirar()[1] in (",", "}"):
                # `{ X }` is `{ X: X }`. A shorthand over a name the module does not
                # declare is not zero, it is a gap -- and a gap is named, never guessed.
                if tipo != "nombre" or clave not in self.entorno:
                    raise FuenteIlegible(f"shorthand sin declarar: {clave!r}")
                salida[str(clave)] = self.entorno[clave]
            else:
                self._tomar(":")
                salida[_clave(clave)] = self._expresion()
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
        if tipo == "cad":
            self._tomar()
            return valor
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
        # Text is compared, not converted: an event name or an error code that a port
        # renames is as broken as a formula that drifts, and it has no relative error. So
        # it goes down its own path -- exact equality, no `tolerancia` -- instead of
        # dying in `float()` and being reported as a reference the caller could not write.
        de_texto = isinstance(esperado, str)
        try:
            if isinstance(esperado, dict):
                puntos = [None if p is None else float(p) for p in esperado["puntos"]]
                valores = [float(v) for v in esperado["valores"]]
            elif de_texto:
                puntos, valores = [], [esperado]
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
                if any(o is None for o in obtenidos) and not de_texto:
                    raise FuenteIlegible("el oraculo vivo no da un numero en ese punto")
        except (FuenteIlegible, ArithmeticError, TypeError, ValueError) as fallo:
            no_evaluables.append({"ancla": nombre, "motivo": str(fallo)})
            continue
        if not isinstance(obtenidos, list):
            obtenidos = [obtenidos]
        if de_texto:
            obtenido = obtenidos[0] if obtenidos else None
            if not isinstance(obtenido, str):
                no_evaluables.append({"ancla": nombre, "motivo": (
                    f"la referencia espera texto y el oraculo da "
                    f"{'nada' if obtenido is None else type(obtenido).__name__}")})
                continue
            igual = obtenido == esperado
            fila = {"ancla": nombre, "tipo": anclas[nombre.partition(".")[0]]["tipo"],
                    "tipo_valor": "texto", "puntos": 1, "peor_punto": None, "ok": igual}
            if not igual:
                fila["obtenido"] = obtenido
                fila["esperado"] = esperado
                divergen += 1
            filas.append(fila)
            continue
        # A literal (object, list) is not a number: comparing it would invent a value, so
        # the caller is told to name a field instead.
        numeros = [o for o in obtenidos
                   if isinstance(o, (int, float)) and not isinstance(o, bool)]
        if len(numeros) != len(obtenidos):
            no_evaluables.append({"ancla": nombre, "motivo": (
                "el oraculo da texto donde la referencia espera un numero"
                if any(isinstance(o, str) for o in obtenidos)
                else "devuelve un literal: nombra un campo con `nombre.campo`")})
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
        de_texto = sorted(f["ancla"] for f in filas
                          if f.get("tipo_valor") == "texto" and not f["ok"])
        numericos = divergen - len(de_texto)
        trozos = []
        if numericos:
            trozos.append(f"{numericos} punto(s) fuera de tolerancia {tolerancia:g}")
        if de_texto:
            trozos.append(f"texto divergente (igualdad exacta, la tolerancia no aplica): "
                          f"{', '.join(de_texto)}")
        return {"rc": RC_DIVERGE, "causa": "DIVERGE",
                "detalle": " · ".join(trozos),
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

# Text is a value and a literal, not a reader failure. Every line here is a case a real
# `constants` file had: a name carrying braces, a URL whose `//` is not a comment, a
# comment that declares nothing, a number with separators, a regex whose character class
# carries a quote, an object keyed by text, and a template literal -- which stays out of
# the subset and is named, not guessed.
_FUENTE_TEXTO = """
// const FALSA = 1; un comentario no declara nada
export const EVENTO = "$insight_alert_opened";
export const CIERRE = "cero}uno{";
export const URL = "https://ejemplo.mx/a"; // http:// sigue sin ser comentario
export const MILLON = 1_000_000;
export const PATRON = /[\\w'()*+,;=]/gi;
export const CAJA = { "ancho": 1080, alto: 1920 };
export const TIPO = `plantilla`;
export const ANCHO = 1080;
export const SHORTHAND = { ANCHO, alto: 1920 };
export const HUERFANO = { NADA };
export const CONCATENADO = "a" + 1;
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

    # Text: read as a value, compared by equality, and never routed through `tolerancia`.
    motivos: dict = {}
    tx = extraer_anclas(_FUENTE_TEXTO, motivos)
    igual("anclas de texto", sorted(tx), sorted(
        ["EVENTO", "CIERRE", "URL", "MILLON", "PATRON", "CAJA", "TIPO", "ANCHO",
         "SHORTHAND", "HUERFANO", "CONCATENADO"]))
    igual("un comentario no declara", "FALSA" in tx, False)
    igual("texto con llave dentro", evaluar(tx, "CIERRE"), "cero}uno{")
    igual("// dentro de una cadena", evaluar(tx, "URL"), "https://ejemplo.mx/a")
    igual("separador numerico", evaluar(tx, "MILLON"), 1000000.0)
    igual("clave de texto", evaluar(tx, "CAJA.ancho"), 1080.0)
    igual("clave sin comillas", evaluar(tx, "CAJA.alto"), 1920.0)
    igual("shorthand declarado", evaluar(tx, "SHORTHAND.ANCHO"), 1080.0)
    texto_ok = comparar(None, {"EVENTO": "$insight_alert_opened",
                              "CAJA.ancho": 1080.0}, anclas=tx)
    igual("texto conforme rc", texto_ok["rc"], RC_OK)
    filas_texto = [f for f in texto_ok["anclas"] if f.get("tipo_valor") == "texto"]
    igual("fila de texto sin error relativo", filas_texto[0].get("peor_rel", "ausente"),
          "ausente")
    sin_tolerancia = comparar(None, {"EVENTO": "$insight_alert_opened_v2"},
                              tolerancia=1e9, anclas=tx)
    igual("la tolerancia no salva un texto", sin_tolerancia["rc"], RC_DIVERGE)
    igual("la causa nombra el texto", "texto divergente" in sin_tolerancia["detalle"], True)
    ausente = censo(tx, motivos)
    igual("censo declaradas", ausente["declaradas"], len(tx))
    igual("plantilla fuera del subconjunto", "TIPO" in ausente["no_evaluables"], True)
    igual("shorthand huerfano nombrado", "HUERFANO" in ausente["no_evaluables"], True)
    igual("texto en aritmetica nombrado", "CONCATENADO" in ausente["no_evaluables"], True)
    for mensaje in fallos:
        print(f"FALLO {mensaje}", file=sys.stderr)
    if fallos:
        print(f"AUTOTEST NO OK: {len(fallos)} ancla(s)", file=sys.stderr)
        return RC_DIVERGE
    print("AUTOTEST OK: 44 anclas de oraculo")
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
            texto_censo = leer_texto(args.fuente, "fuente")
        except InsumoFalta as exc:
            return no_medido("INSUMO_FALTA", str(exc))
        motivos: dict[str, str] = {}
        anclas = extraer_anclas(texto_censo, motivos)
        cobertura = censo(anclas, motivos)
        if args.json:
            print(json.dumps({"anclas": anclas, "censo": cobertura}, indent=2,
                             sort_keys=True))
            return RC_OK
        for nombre, ancla in anclas.items():
            primero = ancla["cuerpo"].splitlines()[0]
            print(f"{nombre} · {ancla['tipo']} · {primero}")
        for nombre, por_que in cobertura["no_leidas"].items():
            print(f"NO_LEIDA {nombre} · {por_que}")
        for nombre, por_que in cobertura["no_evaluables"].items():
            print(f"NO_EVALUABLE {nombre} · {por_que}")
        cuanto = ("NO_MEDIDO" if cobertura["cobertura"] is None
                  else f"{cobertura['cobertura']:.1%}")
        print(f"CENSO · {cobertura['declaradas']} declarada(s) · "
              f"{cobertura['leidas']} leida(s) ({cuanto}) · "
              f"{cobertura['evaluables']} evaluable(s) · las funciones con cuerpo de bloque "
              f"y las variables locales no se leen")
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
        numericas = [f for f in recibo["anclas"] if "peor_abs" in f]
        trozos = [f"{len(recibo['anclas'])} ancla(s)", f"{total} punto(s)"]
        if numericas:
            trozos.append(f"peor error absoluto "
                          f"{max(f['peor_abs'] for f in numericas):.3e}")
        if len(numericas) != len(recibo["anclas"]):
            trozos.append(f"{len(recibo['anclas']) - len(numericas)} de texto "
                          f"(igualdad exacta)")
        trozos.append(f"oraculo {recibo['backend']}")
        print("CONFORME · " + " · ".join(trozos))
    elif recibo["rc"] == RC_DIVERGE:
        for fila in recibo["anclas"]:
            if not fila["ok"]:
                if fila.get("tipo_valor") == "texto":
                    print(f"DIVERGE {fila['ancla']} · texto · "
                          f"obtenido {fila['obtenido']!r} esperado {fila['esperado']!r} · "
                          f"igualdad exacta")
                    continue
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
