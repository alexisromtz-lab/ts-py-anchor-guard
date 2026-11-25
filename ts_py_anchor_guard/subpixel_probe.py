"""How far apart are two luma profiles, below one pixel -- and is the gap uniform?

Two questions, one instrument, no dependencies:

1. **Shift.** Minimise the sum of squared differences over integer offsets, then refine
   with the parabola through the three costs around the minimum. On a band-limited
   profile this resolves a known offset to about `1/50` of a pixel -- enough to tell a
   genuinely sub-pixel compositor (`~0.02 px`) from integer pixel snapping (`floor`,
   `round`, `ceil`, each a quarter of a pixel away from the truth and mutually
   distinguishable).

2. **Anisotropy.** Split the profile into bands, measure the shift in each, and fit a
   line. A pure translation gives a flat line; a rescale gives a slope, and the slope IS
   the relative scale error. This is how an integer-quantised intermediate canvas
   (`985.714 -> 986`, ratio error `2.9e-4`) is caught by looking at one frame instead of
   measuring a whole video.

Why not correlation: correlation of two profiles of unequal length leaks energy as the
overlap shrinks, which biases the minimum toward whichever offset keeps the most samples.
SSD normalises by nothing and is the quantity the question asks for directly.

RC: 0 measured and conforming · 1 measured and the profile diverges · 2 not measured
(profile too short for the requested search, or the fit is not a minimum) · 20 bad
invocation.
"""

from __future__ import annotations

import math

RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20
RESOLUCION_PX = 1 / 50


class PerfilInvalido(ValueError):
    """The profiles cannot answer the question the caller asked."""


def perfil_sintetico(n: int, *, fase: float = 0.0, escala: float = 1.0,
                     semillas: tuple[float, float, float] = (0.05, 0.113, 0.191)) -> list[float]:
    """Three incommensurable sines sampled at `(x - fase)*escala`, in the range [0, 255].

    `fase` is the displacement of the CONTENT: `fase=0.25` moves the profile a quarter of
    a sample to the right, which is what :func:`fase_subpixel` is asked to recover.

    Sampling the analytic function at a fractional offset is exact: the profile carries
    the offset the estimator is asked to recover, so a miss is the estimator's, not an
    interpolation's. Incommensurable seeds avoid the periodic degeneracy where a
    sub-pixel offset and an integer one cost the same.
    """
    if n <= 0:
        raise PerfilInvalido(f"n debe ser positivo, llego {n}")
    if any(w >= math.pi for w in semillas):
        raise PerfilInvalido(
            f"frecuencias por encima de Nyquist ({math.pi:.4f} rad/muestra): {semillas}")
    pesos = (40.0, 26.0, 14.0)
    salida = []
    for i in range(n):
        x = i * escala - fase
        salida.append(127.5 + sum(p * math.sin(w * x) for p, w in zip(pesos, semillas)))
    return salida


def _ssd(a: list[float], b: list[float], d: int) -> float:
    """Σ(a[i] − b[i+d])² over the overlap. `d` is how far `b` is shifted right of `a`."""
    lo_a, hi_a = max(0, -d), min(len(a), len(b) - d)
    if hi_a - lo_a < 2:
        return math.inf
    return sum((a[i] - b[i + d]) ** 2 for i in range(lo_a, hi_a))


def fase_subpixel(a, b, *, max_shift: int = 8) -> dict:
    """Offset of `b` relative to `a`, in samples, with the cost that supports it.

    Positive means the content of `b` sits at larger indices (it moved right/down).
    The integer minimum is refined by the vertex of the parabola through the three
    neighbouring costs; `curvatura` is reported because a flat or inverted parabola means
    the minimum is not a minimum and the answer is `NO_MEDIDO`, not a number.
    """
    a, b = list(a), list(b)
    if len(a) < 16 or len(b) < 16:
        raise PerfilInvalido(f"perfiles demasiado cortos: {len(a)}, {len(b)}")
    if max_shift < 1 or 2 * max_shift + 8 > min(len(a), len(b)):
        raise PerfilInvalido(
            f"max_shift={max_shift} no deja solape suficiente para {len(a)}, {len(b)} muestras")
    costes = {d: _ssd(a, b, d) for d in range(-max_shift, max_shift + 1)}
    mejor = min(costes, key=lambda d: costes[d])
    recibo = {"desplazamiento": float(mejor), "entero": mejor, "coste": costes[mejor],
              "rc": RC_OK, "curvatura": 0.0, "causa": ""}
    if mejor in (-max_shift, max_shift):
        recibo.update(rc=RC_NO_MEDIDO, causa="BORDE",
                      detalle=f"el minimo cae en el borde de la busqueda ({mejor}); "
                              f"amplia --max-shift")
        return recibo
    c_menos, c_cero, c_mas = costes[mejor - 1], costes[mejor], costes[mejor + 1]
    curvatura = c_menos - 2 * c_cero + c_mas
    recibo["curvatura"] = curvatura
    if curvatura <= 0:
        recibo.update(rc=RC_NO_MEDIDO, causa="SIN_MINIMO",
                      detalle="la parabola no abre hacia arriba: no hay minimo subpixel")
        return recibo
    delta = 0.5 * (c_menos - c_mas) / curvatura
    recibo["desplazamiento"] = mejor + max(-0.5, min(0.5, delta))
    return recibo


def anisotropia(a, b, *, bandas: int = 6, max_shift: int = 8) -> dict:
    """Linear fit of the local shift across bands: slope = relative scale error.

    If `b[i] = a[i*(1+k)]` the content at `i` appears displaced by `-k*i`, so a fit of
    `desplazamiento` against the band centre has slope `-k` and an intercept equal to the
    shift at the centre of the profile. Translation alone gives `slope = 0`.
    """
    a, b = list(a), list(b)
    if bandas < 3:
        raise PerfilInvalido(f"hacen falta al menos 3 bandas, llegaron {bandas}")
    n = min(len(a), len(b))
    if n // bandas < 32:
        raise PerfilInvalido(f"{bandas} bandas sobre {n} muestras deja <32 por banda")
    ancho = n // bandas
    puntos = []
    for k in range(bandas):
        desde = k * ancho
        hasta = desde + ancho
        recibo = fase_subpixel(a[desde:hasta], b[desde:hasta], max_shift=max_shift)
        if recibo["rc"] != RC_OK:
            return {"rc": RC_NO_MEDIDO, "causa": "BANDA",
                    "detalle": f"banda {k}: {recibo.get('detalle', recibo['causa'])}",
                    "bandas": puntos}
        puntos.append({"centro": desde + ancho / 2, "desplazamiento": recibo["desplazamiento"]})
    xs = [p["centro"] for p in puntos]
    ys = [p["desplazamiento"] for p in puntos]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    pendiente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    centro = my - pendiente * mx
    residuos = [y - (pendiente * x + centro) for x, y in zip(xs, ys)]
    return {"rc": RC_OK, "causa": "", "detalle": "",
            "pendiente": pendiente, "centro": centro,
            "error_de_escala": -pendiente,
            "residuo_max": max(abs(r) for r in residuos),
            "bandas": puntos}


def _autotest() -> int:
    import sys

    fallos = []

    def cerca(nombre, obtenido, esperado, tol):
        if abs(obtenido - esperado) > tol:
            fallos.append(f"{nombre}: {obtenido!r} != {esperado!r} (tol {tol})")

    base = perfil_sintetico(600)
    identidad = fase_subpixel(base, base)
    cerca("identidad", identidad["desplazamiento"], 0.0, 1e-12)
    for d in (0.25, -3.5, 7.0):
        otro = perfil_sintetico(600, fase=d)
        medido = fase_subpixel(base, otro)
        cerca(f"fase {d}", medido["desplazamiento"], d, RESOLUCION_PX)
    # control negativo: dos perfiles no relacionados no pueden dar fase 0 con coste bajo
    ruido = perfil_sintetico(600, semillas=(0.037, 0.101, 0.229))
    ajeno = fase_subpixel(base, ruido)
    if abs(ajeno["desplazamiento"]) < 1 and ajeno["coste"] < identidad["coste"] * 4:
        fallos.append("dos perfiles distintos se declararon el mismo")
    # anisotropia: b = a(x*(1+k)) deja pendiente -k
    k = 1e-3
    escalado = perfil_sintetico(600, escala=1 + k)
    medida = anisotropia(base, escalado, bandas=6)
    if medida["rc"] != RC_OK:
        fallos.append(f"anisotropia NO_MEDIDO: {medida.get('detalle')}")
    else:
        cerca("error de escala", medida["error_de_escala"], k, 0.2 * k)
        cerca("traslacion pura", anisotropia(base, perfil_sintetico(600, fase=0.0))["pendiente"],
              0.0, 1e-9)
    if fase_subpixel(base, base, max_shift=1)["rc"] != RC_OK:
        fallos.append("max_shift=1 sobre 600 muestras deberia medir")
    for mensaje in fallos:
        print(f"FALLO {mensaje}", file=sys.stderr)
    if fallos:
        print(f"AUTOTEST NO OK: {len(fallos)} ancla(s)", file=sys.stderr)
        return RC_DIVERGE
    print("AUTOTEST OK: 9 anclas de subpixel")
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    import json
    import sys

    from ._cli import InsumoFalta, ParserDeContrato, leer_texto, no_medido

    parser = ParserDeContrato(description=__doc__.splitlines()[0])
    parser.add_argument("--a", help="archivo con el perfil de referencia (flotantes separados "
                                    "por espacio)")
    parser.add_argument("--b", help="archivo con el perfil medido")
    parser.add_argument("--bandas", type=int, default=6, help="bandas del ajuste de escala")
    parser.add_argument("--max-shift", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", "--autotest", dest="self_test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _autotest()
    if not args.a or not args.b:
        print("uso: subpixel_probe.py --a PERFIL --b PERFIL [--bandas N] [--json]", file=sys.stderr)
        return RC_ARITY
    try:
        a = [float(v) for v in leer_texto(args.a, "perfil A").split()]
        b = [float(v) for v in leer_texto(args.b, "perfil B").split()]
    except InsumoFalta as exc:
        return no_medido("INSUMO_FALTA", str(exc))
    except ValueError as exc:
        return no_medido("INSUMO_ILEGIBLE", f"un perfil no es una lista de flotantes: {exc}")
    recibo = anisotropia(a, b, bandas=args.bandas, max_shift=args.max_shift)
    if recibo["rc"] == RC_OK:
        fase = fase_subpixel(a, b, max_shift=args.max_shift)
        recibo["desplazamiento_global"] = fase["desplazamiento"]
    if args.json:
        print(json.dumps(recibo, indent=2, sort_keys=True))
    elif recibo["rc"] == RC_OK:
        print(f"{recibo['desplazamiento_global']:+.4f} px "
              f"({1 / RESOLUCION_PX:.0f}/px de resolucion) · "
              f"error de escala {recibo['error_de_escala'] * 100:+.4f} % por banda")
    else:
        print(f"NO_MEDIDO · {recibo['causa']} · {recibo.get('detalle', '')}", file=sys.stderr)
    return recibo["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
