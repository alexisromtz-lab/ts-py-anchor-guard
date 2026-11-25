"""The exit-code contract, measured where a runner sees it: the process, not `main()`.

Four codes with four meanings -- `0` conforming, `1` diverging, `2` not measured, `20`
bad invocation -- and three of them were wrong before this file existed. `argparse` exits
`2` by default, so a misspelled flag was reported as "not measured"; a missing input file
raised `FileNotFoundError` and left the process at `1`, which reads as "the port is
wrong"; and `viewport_embed` printed a receipt by reading `recibo["escala"]`, a key the
`DESBORDA` receipt did not have, so the module's own negative control died with
`KeyError` instead of naming its cause.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MODULOS = ("anchor_oracle", "live_oracle", "subpixel_probe", "viewport_embed")
RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20


def correr(modulo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", f"ts_py_anchor_guard.{modulo}", *args],
                          cwd=RAIZ, capture_output=True, text=True, timeout=120)


class ContratoDeInvocacion(unittest.TestCase):
    def test_20_una_flag_que_no_existe_no_es_un_no_medido(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                p = correr(modulo, "--no-existe-esta-flag")
                self.assertEqual(p.returncode, RC_ARITY, p.stderr)
                self.assertIn("unrecognized arguments", p.stderr)

    def test_20_un_valor_del_tipo_equivocado(self):
        p = correr("subpixel_probe", "--a", "f", "--b", "g", "--bandas", "abc")
        self.assertEqual(p.returncode, RC_ARITY, p.stderr)

    def test_0_help_no_es_una_invocacion_mala(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                self.assertEqual(correr(modulo, "--help").returncode, RC_OK)


class InsumoQueFalta(unittest.TestCase):
    def test_2_y_recibo_no_traceback(self):
        casos = {
            "anchor_oracle": ("--backend", "estatico", "--fuente", "/nope/f.ts",
                              "--referencia", "/nope/r.json"),
            "live_oracle": ("--fuente", "/nope/f.ts", "--referencia", "/nope/r.json"),
            "subpixel_probe": ("--a", "/nope/a.txt", "--b", "/nope/b.txt"),
        }
        for modulo, args in casos.items():
            with self.subTest(modulo=modulo):
                p = correr(modulo, *args)
                self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
                self.assertIn("NO_MEDIDO · INSUMO_FALTA", p.stderr)
                self.assertNotIn("Traceback", p.stderr)


class ReciboDeDesborde(unittest.TestCase):
    def test_1_el_desborde_nombra_su_causa_y_no_revienta(self):
        p = correr("viewport_embed", "--canvas", "100", "100", "--ventana", "864", "960")
        self.assertEqual(p.returncode, RC_DIVERGE, p.stderr)
        self.assertIn("causa=DESBORDA", p.stdout)
        self.assertNotIn("Traceback", p.stderr)

    def test_el_recibo_del_desborde_tiene_las_claves_del_conforme(self):
        desborde = correr("viewport_embed", "--canvas", "100", "100",
                          "--ventana", "864", "960", "--json")
        conforme = correr("viewport_embed", "--canvas", "1080", "1920",
                          "--ventana", "864", "960", "--json")
        a, b = json.loads(desborde.stdout), json.loads(conforme.stdout)
        self.assertEqual(sorted(a), sorted(b))
        self.assertIsNone(a["escala"])
        self.assertEqual(b["escala"], [1.0, 1.0])

    def test_20_un_lienzo_de_lado_cero_es_invocacion_mala(self):
        p = correr("viewport_embed", "--canvas", "100", "0", "--ventana", "10", "10")
        self.assertEqual(p.returncode, RC_ARITY, p.stderr)


if __name__ == "__main__":
    unittest.main()
