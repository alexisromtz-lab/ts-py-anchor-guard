"""A repository signs its own correspondence map; the gate enforces the signature.

`comparar` measures one source against one reference, and a reference may be a subset:
its `cobertura` says so and nothing fails. That is honest for a single invocation and
insufficient for a gate, because two questions a repository has to answer cannot be
answered by a command line that someone remembers to type:

- **How is a container named in one language to be read in the other?** TypeScript
  `CUADRO = {ancho, alto}` and Python `CUARO = (1080, 1920)` hold the same two numbers at
  different addresses. The oracle refuses to guess (`ANCLA_NO_EVALUABLE`), and it must: an
  inference would be a measurement of the reader's assumption, not of the port.
- **Is a green allowed to cover a subset?** When a name is renamed on one side
  (`NUDOS_S5` / `RAMPA_S5`) it is neither a pass nor a failure -- it is absent -- and no
  receipt says it.

So the correspondence is written down once, in the repository, and versioned with it:

    {
      "version": 1,
      "pares": [
        {"nombre": "paneo",
         "fuente": "src/paneo.ts",
         "referencia": "scripts/ref-paneo.json",
         "mapeos": {"CUADRO.ancho": "CUADRO.0", "CUADRO.alto": "CUADRO.1"},
         "exigir_cobertura_total": true}
      ]
    }

`mapeos` is `{ancla que la fuente declara: ruta en la referencia}`. A mapping also
expresses a rename (`{"NUDOS_S5.0": "RAMPA_S5.0"}`), which is the one way to turn "these
two names carry the same vector" from a claim into a measurement. Both sides use the
notation the oracle already reads for anchors (`CUADRO.ancho`, `RAMPA.0`); a second
notation would be a second thing to keep in agreement.

The manifest is data, so it fails closed the way data has to: a version it does not know,
a key it does not recognise (a typo like `exigir_covertura_total` must not be silently
ignored, or the gate it was meant to switch on never exists), a mapping whose path is not
in the reference, a mapping for an anchor the source does not declare. Each of them is
named in the receipt instead of being skipped.

Paths inside a pair are relative to the manifest's own directory, so the manifest can be
committed next to the sources it describes and run from any working directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import RC_DIVERGE, RC_NO_MEDIDO, RC_OK
from ._cli import InsumoFalta, leer_texto, no_medido
from .anchor_oracle import _miembro, comparar, extraer_anclas, medir_vivos

VERSION = 1

_CLAVES_RAIZ = {"version", "pares"}
_CLAVES_PAR = {"nombre", "fuente", "referencia", "mapeos",
               "exigir_cobertura_total", "tolerancia", "backend"}
_BACKENDS = ("auto", "node", "estatico")


class ManifiestoIlegible(Exception):
    """The manifest says something the contract does not read, and it is named."""


def _desconocidas(claves, permitidas) -> list[str]:
    return sorted(set(claves) - permitidas)


def cargar(ruta: str | Path) -> dict:
    """Parse and validate a manifest, or raise naming what it does not read.

    Validation is not politeness: every field here switches a gate, so a field that is
    misspelled is a gate that is off while its author believes it is on.
    """
    ruta = Path(ruta)
    try:
        documento = json.loads(ruta.read_text())
    except OSError as exc:
        raise InsumoFalta(f"manifiesto {str(ruta)!r}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifiestoIlegible(f"manifiesto {str(ruta)!r}: {exc}") from exc
    if not isinstance(documento, dict):
        raise ManifiestoIlegible(
            f"manifiesto {str(ruta)!r}: la raiz no es un objeto, es "
            f"{type(documento).__name__}")
    sobrantes = _desconocidas(documento, _CLAVES_RAIZ)
    if sobrantes:
        raise ManifiestoIlegible(
            f"manifiesto {str(ruta)!r}: claves que el contrato no lee: "
            f"{', '.join(sobrantes)}")
    version = documento.get("version")
    if version != VERSION:
        raise ManifiestoIlegible(
            f"manifiesto {str(ruta)!r}: version {version!r}, este lector lee {VERSION}")
    pares = documento.get("pares")
    if not isinstance(pares, list) or not pares:
        raise ManifiestoIlegible(
            f"manifiesto {str(ruta)!r}: `pares` tiene que ser una lista no vacia")
    for posicion, par in enumerate(pares, 1):
        _validar_par(par, posicion, ruta)
    return {"version": version, "pares": pares, "raiz": ruta.parent}


def _validar_par(par, posicion: int, ruta: Path) -> None:
    donde = f"manifiesto {str(ruta)!r}: par {posicion}"
    if not isinstance(par, dict):
        raise ManifiestoIlegible(f"{donde}: no es un objeto, es {type(par).__name__}")
    sobrantes = _desconocidas(par, _CLAVES_PAR)
    if sobrantes:
        raise ManifiestoIlegible(
            f"{donde}: claves que el contrato no lee: {', '.join(sobrantes)}")
    for obligatoria in ("fuente", "referencia"):
        valor = par.get(obligatoria)
        if not isinstance(valor, str) or not valor:
            raise ManifiestoIlegible(f"{donde}: falta `{obligatoria}`")
    mapeos = par.get("mapeos", {})
    if not isinstance(mapeos, dict) or not all(
            isinstance(k, str) and k and isinstance(v, str) and v for k, v in mapeos.items()):
        raise ManifiestoIlegible(
            f"{donde}: `mapeos` es {{ancla de la fuente: ruta en la referencia}}")
    exigir = par.get("exigir_cobertura_total", False)
    if not isinstance(exigir, bool):
        raise ManifiestoIlegible(f"{donde}: `exigir_cobertura_total` es true o false")
    tolerancia = par.get("tolerancia", 0.0)
    if isinstance(tolerancia, bool) or not isinstance(tolerancia, (int, float)):
        raise ManifiestoIlegible(f"{donde}: `tolerancia` es un numero")
    backend = par.get("backend", None)
    if backend is not None and backend not in _BACKENDS:
        raise ManifiestoIlegible(
            f"{donde}: `backend` es uno de {', '.join(_BACKENDS)}")


def expandir(referencia: dict, mapeos: dict[str, str],
             anclas: dict[str, dict]) -> tuple[dict, list[dict], list[str]]:
    """Reference rewritten to the addresses the manifest signs, plus what it did not use.

    Three things happen here, and each of them is published in the receipt:

    - every declared mapping is resolved, and a mapping that cannot be resolved is not
      dropped -- the pair would then look exactly like one that never declared it, which is
      the silent hole this file exists to close;
    - a reference key consumed by a mapping is removed: its members now carry the
      measurement, and leaving the container in place would report `CUADRO` as unmeasurable
      forever, which is the refusal the mapping was written to answer;
    - a reference key that is neither declared by the source nor addressed by a mapping is
      returned as *ignored* instead of being compared: inside a manifest the pairing is
      already declared by hand, so an extra key is noise from the dump, not a mismatch.
      It is counted, never silently absorbed.
    """
    expandida, fallos, consumidas = {}, [], set()
    for ancla, ruta in mapeos.items():
        raiz, _, resto = ruta.partition(".")
        consumidas.add(raiz)
        if ancla.partition(".")[0] not in anclas:
            fallos.append({"ancla": ancla, "ruta": ruta, "motivo":
                           "la fuente no declara esa ancla: el mapeo esta de mas"})
            continue
        if raiz not in referencia:
            fallos.append({"ancla": ancla, "ruta": ruta, "motivo":
                           f"la referencia no tiene {raiz!r}"})
            continue
        try:
            expandida[ancla] = _miembro(referencia[raiz], resto, ruta) if resto else referencia[raiz]
        except Exception as fallo:  # noqa: BLE001 - FuenteIlegible or a shape it cannot walk
            fallos.append({"ancla": ancla, "ruta": ruta, "motivo": str(fallo)})
    ignoradas = []
    for nombre, valor in referencia.items():
        if nombre in consumidas:
            continue
        if nombre in anclas:
            expandida[nombre] = valor
        else:
            ignoradas.append(nombre)
    return expandida, fallos, ignoradas


def _cubierta(par: dict) -> dict:
    """The pair's `cobertura`, or empty counts.

    `comparar` is allowed to refuse before it produces one (`REFERENCIA_VACIA`,
    `SIN_FUENTE`), and an aggregate that assumes every receipt has the same shape turns a
    named refusal into a traceback.
    """
    return par.get("cobertura") or {"declaradas": 0, "comparadas": 0, "omitidas": []}


def _cuenta(par: dict, clave: str) -> int:
    return _cubierta(par)[clave]


def _precedencia(codigos) -> int:
    """A measured divergence outranks a gap, and a gap never degrades to conforming."""
    if RC_DIVERGE in codigos:
        return RC_DIVERGE
    return RC_NO_MEDIDO if any(c != RC_OK for c in codigos) else RC_OK


def correr(ruta: str | Path, *, backend: str = "auto", json_out: bool = False,
           tolerancia: float | None = None,
           exigir_cobertura_total: bool = False) -> int:
    """Run every pair in the manifest and print one receipt for the whole repository.

    The arguments are the *defaults* for pairs that do not declare their own: a manifest is
    versioned with the repository and outranks the command line, which is the only way an
    invocation cannot quietly loosen a signature. Demanding total coverage is the exception,
    because it is only ever stricter: `--exigir-cobertura-total` can turn a report into a
    defect and can never turn a defect into a report.
    """
    try:
        manifiesto = cargar(ruta)
    except InsumoFalta as exc:
        return no_medido("INSUMO_FALTA", str(exc))
    except ManifiestoIlegible as exc:
        return no_medido("INSUMO_ILEGIBLE", str(exc))
    pares = []
    for par in manifiesto["pares"]:
        pares.append(_correr_par(par, manifiesto["raiz"], backend, tolerancia,
                                 exigir_cobertura_total))
    codigos = [p["rc"] for p in pares]
    recibo = {"version": VERSION, "manifest": str(ruta), "rc": _precedencia(codigos),
              "pares": pares, "totales": {
                  "pares": len(pares),
                  "conformes": sum(1 for p in pares if p["rc"] == RC_OK),
                  "divergen": sum(1 for p in pares if p["rc"] == RC_DIVERGE),
                  "no_medidos": sum(1 for p in pares if p["rc"] == RC_NO_MEDIDO),
                  "declaradas": sum(_cuenta(p, "declaradas") for p in pares),
                  "comparadas": sum(_cuenta(p, "comparadas") for p in pares),
                  "omitidas": sum(len(_cubierta(p)["omitidas"]) for p in pares),
                  "ignoradas": sum(len(p.get("referencia_ignorada") or []) for p in pares)}}
    if json_out:
        print(json.dumps(recibo, indent=2, sort_keys=True))
    else:
        _imprimir(recibo)
    return recibo["rc"]


def _correr_par(par: dict, raiz: Path, backend: str, tolerancia: float | None,
                exigir_cobertura_total: bool) -> dict:
    nombre = par.get("nombre") or par["fuente"]
    fuente, referencia = raiz / par["fuente"], raiz / par["referencia"]
    try:
        texto = leer_texto(str(fuente), "fuente")
    except InsumoFalta as exc:
        return _recibo_vacio(nombre, "INSUMO_FALTA", str(exc))
    try:
        crudo = json.loads(leer_texto(str(referencia), "referencia"))
    except InsumoFalta as exc:
        return _recibo_vacio(nombre, "INSUMO_FALTA", str(exc))
    except json.JSONDecodeError as exc:
        return _recibo_vacio(nombre, "INSUMO_ILEGIBLE", f"referencia {str(referencia)!r}: {exc}")
    anclas = extraer_anclas(texto)
    valorada, fallos, ignoradas = expandir(crudo, par.get("mapeos") or {}, anclas)
    vivos, nombre_backend, fallo, aviso = medir_vivos(texto, valorada,
                                                      par.get("backend") or backend)
    if fallo:
        recibo = _recibo_vacio(nombre, fallo[0], fallo[1])
        recibo["referencia_ignorada"] = ignoradas
        return recibo
    recibo = comparar(texto, valorada,
                      tolerancia=par.get("tolerancia", 0.0 if tolerancia is None else tolerancia),
                      anclas=anclas, vivos=vivos, backend=nombre_backend,
                      exigir_cobertura_total=(par.get("exigir_cobertura_total", False)
                                              or exigir_cobertura_total))
    recibo["nombre"] = nombre
    recibo["referencia_ignorada"] = ignoradas
    if aviso:
        # `auto` chose a reader that could not load the source and measured with the other
        # one: the receipt names the reason, or the weaker reading passes for the stronger.
        recibo["aviso"] = aviso
    if ignoradas and recibo.get("causa") == "REFERENCIA_VACIA":
        # Everything the reference held was addressed by nobody: name the keys, or the
        # reader has an empty-file verdict on a file that is not empty.
        recibo["detalle"] = (f"la referencia trae {', '.join(ignoradas)}, que la fuente no "
                             f"declara y ningun mapeo alcanza")
    if fallos:
        recibo["mapeos_invalidos"] = fallos
        # The divergence is a measurement about the subject; a mapping that does not
        # resolve is a defect in the contract, and it does not get to overwrite one.
        if recibo["rc"] != RC_DIVERGE:
            recibo.update(rc=RC_NO_MEDIDO, causa="MAPEO_INVALIDO", detalle="; ".join(
                f"{f['ancla']} -> {f['ruta']}: {f['motivo']}" for f in fallos))
    return recibo


def _recibo_vacio(nombre: str, causa: str, detalle: str) -> dict:
    return {"nombre": nombre, "rc": RC_NO_MEDIDO, "causa": causa, "detalle": detalle,
            "anclas": [], "no_evaluables": [], "backend": "",
            "cobertura": {"declaradas": 0, "comparadas": 0, "omitidas": [], "exigida": False}}


def _imprimir(recibo: dict) -> None:
    totales = recibo["totales"]
    for par in recibo["pares"]:
        cobertura = _cubierta(par)
        ignoradas = par.get("referencia_ignorada") or []
        if par["rc"] == RC_OK:
            aviso = f" · aviso: {par['aviso']}" if par.get("aviso") else ""
            print(f"CONFORME {par['nombre']} · {cobertura['comparadas']} comparada(s) · "
                  f"{len(cobertura['omitidas'])} omitida(s) · {len(ignoradas)} ignorada(s) · "
                  f"{par['backend']}{aviso}")
        elif par["rc"] == RC_DIVERGE:
            for fila in par["anclas"]:
                if not fila["ok"]:
                    print(f"DIVERGE {par['nombre']} · {fila['ancla']} · punto "
                          f"{fila['peor_punto']} · obtenido {fila['obtenido']!r} esperado "
                          f"{fila['esperado']!r} · peor_rel {fila['peor_rel']:.6g}")
        else:
            print(f"NO_MEDIDO {par['nombre']} · {par['causa']} · {par['detalle']}",
                  file=sys.stderr)
    print(f"MANIFIESTO · {totales['pares']} par(es) · {totales['conformes']} conforme(s) · "
          f"{totales['divergen']} divergente(s) · {totales['no_medidos']} no medido(s) · "
          f"{totales['declaradas']} declarada(s) · {totales['comparadas']} comparada(s) · "
          f"{totales['omitidas']} omitida(s) · {totales['ignoradas']} ignorada(s)",
          file=sys.stderr)
