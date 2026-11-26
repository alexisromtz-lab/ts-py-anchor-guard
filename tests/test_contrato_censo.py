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

    def test_el_primer_control_negativo_se_ejercita(self):
        """`--self-test` answering 0 only says the census agrees today, not that it can say no.

        Sabotage `evaluar` so every row conforms, then read *which* control spoke: the second
        control fires on the same sabotage, so a test that only checked the exit code would
        pass with the first control removed.
        """
        original = censo.evaluar

        def siempre_conforme(filas, *, raiz):
            for fila in filas:
                fila.update(obtenido=fila["esperado"], choque=False, conforme=True)
            return filas, censo.RC_OK

        censo.evaluar = siempre_conforme
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                rc = censo._autotest(RAIZ)
        finally:
            censo.evaluar = original
        self.assertEqual(rc, censo.RC_DIVERGE, "el control negativo no dispara")
        self.assertIn("expectativa imposible", err.getvalue(),
                      f"el control que disparo no fue el primero: {err.getvalue()!r}")

    def test_la_tabla_nombra_el_choque_y_no_un_codigo_equivocado(self):
        fila = {"modulo": "control", "codigo": 1, "esperado": 1, "clase": "", "motivo": "",
                "args": [], "orden": [sys.executable, "-c", "raise RuntimeError('boom')"]}
        filas, _ = censo.evaluar([fila], raiz=RAIZ)
        texto = censo._tabla(filas)
        self.assertIn("CHOQUE", texto)
        self.assertNotIn("devolvio", texto)

    def test_las_celdas_vacias_se_declaran_con_su_motivo(self):
        with tempfile.TemporaryDirectory(prefix="censo-") as caja:
            filas = censo.casos(RAIZ, Path(caja))
        vacias = [f for f in filas if f["clase"]]
        self.assertEqual(len(vacias), 4, "una celda vacia sin clase pasaria por medida")
        for fila in vacias:
            self.assertTrue(fila["motivo"], f"{fila['modulo']} {fila['codigo']} sin motivo")
            self.assertNotEqual(fila["esperado"], fila["codigo"],
                                "una celda vacia no puede esperar su propio codigo")

    def test_el_eje_del_backend_se_mide_y_no_se_deduce(self):
        """`auto` picks node whenever it can, so a grid of `auto` rows measures one backend of two.

        Before this row existed the census ran `anchor_oracle` five times and never asked who
        produced the numbers: `--backend estatico` — the path with no runtime beyond Python —
        was unmeasured, and a silent demotion from `node` to `estatico` would have been invisible.
        """
        from ts_py_anchor_guard.live_oracle import version_de_nodo

        with tempfile.TemporaryDirectory(prefix="censo-") as caja:
            filas = censo.casos(RAIZ, Path(caja))
        estatico = [f for f in filas if "--backend" in f["args"] and "estatico" in f["args"]]
        self.assertEqual(len(estatico), 1, "el backend estatico no tiene fila propia")
        self.assertEqual(estatico[0]["esperado"], censo.RC_OK)

        pedido = [f for f in filas if f["args"][-1:] == ["node"]]
        self.assertEqual(len(pedido), 1, "el modo pedido y ausente no tiene fila propia")
        if version_de_nodo():
            self.assertEqual(pedido[0]["clase"], censo.POR_DISENO,
                             "con node el 2 no se alcanza por esta ruta y hay que declararlo")
        else:
            self.assertEqual(pedido[0]["clase"], censo.MEDIDO,
                             "sin node la ruta devuelve 2: es una celda medida, no declarada")
            self.assertEqual(pedido[0]["esperado"], censo.RC_NO_MEDIDO)


if __name__ == "__main__":
    unittest.main()
