"""Pin the contract census against the CLIs it measures.

The README publishes four exit codes; this is the reader that keeps the table true. Two
things are pinned and they are not the same: that the census agrees with the processes
(one row per code and module), and that the census *can* disagree -- a verifier whose
negative control never fires is a green that measures nothing.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CENSO = RAIZ / "tools" / "contrato_censo.py"

_ESPEC = importlib.util.spec_from_file_location("contrato_censo", CENSO)
assert _ESPEC and _ESPEC.loader
censo = importlib.util.module_from_spec(_ESPEC)
_ESPEC.loader.exec_module(censo)


class ContratoCenso(unittest.TestCase):
    def test_el_censo_coincide_con_los_procesos(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = censo.main(["--raiz", str(RAIZ)])
        self.assertEqual(rc, 0)

    def test_el_censo_puede_decir_que_no(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = censo.main(["--raiz", str(RAIZ), "--self-test"])
        self.assertEqual(rc, 0)

    def test_un_choque_no_satisface_una_celda_de_divergencia(self):
        """`1` is a verdict and `1` is also a crash; the cell must tell them apart."""
        fila = {"modulo": "control", "codigo": 1, "esperado": 1, "clase": "", "motivo": "",
                "args": [], "orden": [sys.executable, "-c", "raise RuntimeError('boom')"]}
        filas, rc = censo.evaluar([fila], raiz=RAIZ)
        self.assertEqual(filas[0]["obtenido"], 1)
        self.assertTrue(filas[0]["choque"])
        self.assertFalse(filas[0]["conforme"], "un choque paso por divergencia medida")
        self.assertEqual(rc, 1)

    def test_las_celdas_vacias_se_declaran_con_su_motivo(self):
        from ts_py_anchor_guard.live_oracle import version_de_nodo

        with tempfile.TemporaryDirectory(prefix="censo-") as caja:
            filas = censo.casos(RAIZ, Path(caja))
        vacias = [f for f in filas if f["clase"]]
        self.assertEqual(len(vacias), 3 if version_de_nodo() else 4,
                         "una celda vacia sin clase pasaria por medida")
        for fila in vacias:
            self.assertTrue(fila["motivo"], f"{fila['modulo']} {fila['codigo']} sin motivo")
            self.assertNotEqual(fila["esperado"], fila["codigo"],
                                "una celda vacia no puede esperar su propio codigo")


if __name__ == "__main__":
    unittest.main()
