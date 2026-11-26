"""Guards for TypeScript -> Python ports of layout and camera engines.

Three checks, each with its own receipt and its own exit code:

* :mod:`anchor_oracle`   -- do the numbers a TypeScript source declares evaluate to the
                            values the Python port computes, exactly?
* :mod:`viewport_embed`  -- is a 1:1 sub-viewport placed inside a larger canvas, or was it
                            silently stretched to fill it?
* :mod:`subpixel_probe`  -- how far is one luma profile from another, below one pixel, and
                            does the difference grow with position (anisotropy) or not?

:mod:`live_oracle` is not a fourth check: it is the optional backend that measures the
reference values by executing the TypeScript source with node, so that a port is compared
against the engine's own runtime and not against a second implementation of the same
formula.

Exit codes are the same everywhere: ``0`` conforming, ``1`` diverging (the defect is named),
``2`` not measured (never reported as conforming), ``20`` bad invocation.

Names are imported lazily so that ``python -m ts_py_anchor_guard.<module>`` can run a
module without the package importing it first.
"""

from importlib import import_module

_MODULOS = {
    "anchor_oracle": ("comparar", "evaluar", "extraer_anclas", "residuo_de_redondeo"),
    "subpixel_probe": ("anisotropia", "fase_subpixel", "perfil_sintetico",
                       "RESOLUCION_PX", "PerfilInvalido"),
    "viewport_embed": ("rect_de", "verificar_1a1", "VentanaNoCabe"),
    "live_oracle": ("medir", "version_de_nodo"),
}

__all__ = ["RC_OK", "RC_DIVERGE", "RC_NO_MEDIDO", "RC_ARITY"] + [
    nombre for nombres in _MODULOS.values() for nombre in nombres]

RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20
__version__ = "0.8.0"


def __getattr__(nombre: str):
    for modulo, nombres in _MODULOS.items():
        if nombre in nombres:
            return getattr(import_module(f".{modulo}", __name__), nombre)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
