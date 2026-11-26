"""A 1:1 sub-viewport inside a larger canvas is PLACED, never rescaled.

The bug this module exists for is silent. A camera or layout engine paints a
`864x960` window into a `1080x1920` frame. A port that composes the window over the
whole frame still matches every trajectory to `0.000e+00`, still renders a recognisable
picture, and is wrong by a factor of `1.25` horizontally and `2.00` vertically. Nothing
fails; the geometry is simply a different subject.

So the invariant is stated once, in arithmetic: the rect that receives the window must
have the same size as the window, and must fit inside the canvas.

    >>> rect_de((1080, 1920), (864, 960))
    (108, 480, 864, 960)

RC: 0 conforming · 1 diverging (the cause is named) · 20 bad invocation.
"""

from __future__ import annotations

RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20


class VentanaNoCabe(ValueError):
    """The window is larger than the canvas: it is not a sub-viewport at all."""


def _entero(valor, nombre: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"{nombre} debe ser entero, llego {valor!r}")
    if valor <= 0:
        raise ValueError(f"{nombre} debe ser positivo, llego {valor}")
    return valor


def rect_de(canvas: tuple[int, int], ventana: tuple[int, int]) -> tuple[int, int, int, int]:
    """`(left, top, width, height)` of `ventana` centred in `canvas`, at scale 1.

    Centring floors the margin, so the rect is always inside the canvas: a camera that
    rounds *up* leaves the window half a pixel outside its own frame, which is exactly
    the sliver this guard is meant to refuse. An oversized window raises
    :class:`VentanaNoCabe` instead of being clipped or shrunk -- clipping changes the
    visible extent and shrinking changes the scale the destination engine uses.
    """
    ancho_cuadro, alto_cuadro = _entero(canvas[0], "canvas[0]"), _entero(canvas[1], "canvas[1]")
    ancho_ventana, alto_ventana = _entero(ventana[0], "ventana[0]"), _entero(ventana[1], "ventana[1]")
    if ancho_ventana > ancho_cuadro or alto_ventana > alto_cuadro:
        raise VentanaNoCabe(
            f"ventana {ancho_ventana}x{alto_ventana} no cabe en lienzo {ancho_cuadro}x{alto_cuadro}"
        )
    return (
        (ancho_cuadro - ancho_ventana) // 2,
        (alto_cuadro - alto_ventana) // 2,
        ancho_ventana,
        alto_ventana,
    )


def verificar_1a1(canvas: tuple[int, int], ventana: tuple[int, int],
                  rect: tuple[int, int, int, int] | None = None) -> dict:
    """Receipt for the 1:1 embedding invariant.

    `escala` is what you get if the window is painted into `rect` and `rect` is stretched
    to `canvas`: `(1.0, 1.0)` means nothing was rescaled. The check names its cause --
    `ESCALA` (the rect was resized), `RECORTE` (the rect leaves the canvas) or
    `DESBORDA` (the window does not fit) -- because "bad geometry" is not a diagnosis.
    """
    ancho_cuadro, alto_cuadro = canvas
    ancho_ventana, alto_ventana = ventana
    if rect is None:
        try:
            rect = rect_de(canvas, ventana)
        except VentanaNoCabe as exc:
            # Same shape as every other receipt: a consumer reads `escala` unconditionally,
            # and a missing key is a crash in the caller, not a diagnosis. `None` is the
            # honest value -- there is no rect, so there is no scale to report.
            return {"rc": RC_DIVERGE, "ok": False, "causa": "DESBORDA", "detalle": str(exc),
                    "rect": None, "canvas": list(canvas), "ventana": list(ventana),
                    "escala": None}
    izquierda, arriba, ancho, alto = rect
    escala = (ancho_ventana / ancho, alto_ventana / alto)
    dentro = izquierda >= 0 and arriba >= 0 and izquierda + ancho <= ancho_cuadro \
        and arriba + alto <= alto_cuadro
    recibo = {"rc": RC_OK, "ok": True, "causa": "", "detalle": "",
              "rect": list(rect), "canvas": list(canvas), "ventana": list(ventana),
              "escala": [round(escala[0], 12), round(escala[1], 12)]}
    if escala[0] != 1.0 or escala[1] != 1.0:
        recibo.update(rc=RC_DIVERGE, ok=False, causa="ESCALA",
                      detalle=f"el rectangulo mide {ancho}x{alto} y la ventana "
                              f"{ancho_ventana}x{alto_ventana}: se estira {escala[0]:.6f}x"
                              f"{escala[1]:.6f}")
    elif not dentro:
        recibo.update(rc=RC_DIVERGE, ok=False, causa="RECORTE",
                      detalle=f"el rectangulo {rect} no cabe en el lienzo {canvas}")
    return recibo


def _autotest() -> int:
    fallos = []

    def igual(nombre, obtenido, esperado):
        if obtenido != esperado:
            fallos.append(f"{nombre}: {obtenido!r} != {esperado!r}")

    igual("centrado", rect_de((1080, 1920), (864, 960)), (108, 480, 864, 960))
    igual("par", rect_de((1000, 1000), (500, 500)), (250, 250, 500, 500))
    igual("impar baja", rect_de((1001, 1001), (500, 500)), (250, 250, 500, 500))
    igual("lleno", rect_de((864, 960), (864, 960)), (0, 0, 864, 960))
    igual("1a1 ok", verificar_1a1((1080, 1920), (864, 960))["rc"], RC_OK)
    estirado = verificar_1a1((1080, 1920), (864, 960), (0, 0, 1080, 1920))
    igual("estirado rc", estirado["rc"], RC_DIVERGE)
    igual("estirado causa", estirado["causa"], "ESCALA")
    igual("estirado escala", estirado["escala"], [0.8, 0.5])
    fuera = verificar_1a1((1080, 1920), (864, 960), (300, 480, 864, 960))
    igual("fuera causa", fuera["causa"], "RECORTE")
    desborda = verificar_1a1((1080, 1920), (1088, 960))
    igual("desborda rc", desborda["rc"], RC_DIVERGE)
    igual("desborda causa", desborda["causa"], "DESBORDA")
    igual("desborda forma", sorted(desborda), sorted(verificar_1a1((1080, 1920), (864, 960))))
    igual("desborda escala", desborda["escala"], None)
    try:
        rect_de((1080, 1920), (0, 960))
    except ValueError:
        pass
    else:
        fallos.append("ventana de ancho 0 no se rechazo")
    for mensaje in fallos:
        print(f"FALLO {mensaje}", file=__import__("sys").stderr)
    if fallos:
        print(f"AUTOTEST NO OK: {len(fallos)} ancla(s)", file=__import__("sys").stderr)
        return RC_DIVERGE
    print("AUTOTEST OK: 14 anclas de encastre")
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    import json
    import sys

    from ._cli import ParserDeContrato

    parser = ParserDeContrato(description=__doc__.splitlines()[0])
    parser.add_argument("--canvas", nargs=2, type=int, metavar=("A", "H"))
    parser.add_argument("--ventana", nargs=2, type=int, metavar=("A", "H"))
    parser.add_argument("--rect", nargs=4, type=int, metavar=("X", "Y", "A", "H"),
                        help="el rectangulo que de verdad usa el motor; si falta, se centra")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", "--autotest", dest="self_test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _autotest()
    if not args.canvas or not args.ventana:
        print("uso: viewport_embed.py --canvas A H --ventana A H [--rect X Y A H]", file=sys.stderr)
        return RC_ARITY
    try:
        canvas = (_entero(args.canvas[0], "canvas[0]"), _entero(args.canvas[1], "canvas[1]"))
        ventana = (_entero(args.ventana[0], "ventana[0]"), _entero(args.ventana[1], "ventana[1]"))
    except ValueError as exc:
        print(f"uso: viewport_embed.py --canvas A H --ventana A H · {exc}", file=sys.stderr)
        return RC_ARITY
    recibo = verificar_1a1(canvas, ventana, tuple(args.rect) if args.rect else None)
    if args.json:
        print(json.dumps(recibo, indent=2, sort_keys=True))
    else:
        print(f"{'OK' if recibo['ok'] else 'DIVERGE'} · causa={recibo['causa'] or '-'} · "
              f"escala={recibo['escala'] if recibo['escala'] is not None else '-'} · "
              f"{recibo['detalle'] or 'encastre 1:1'}")
    return recibo["rc"]


if __name__ == "__main__":
    from ._cli import correr

    raise SystemExit(correr(main))
