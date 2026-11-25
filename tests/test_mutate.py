"""Pin the README's mutation claim.

The README says which mutations the suite notices and, just as importantly, which three no
test can notice because the arithmetic makes the guard unreachable. Both halves rot the same
way: a mutation whose target text drifts becomes `NO_APPLICABLE` and is quietly counted as
covered, and an "unreachable" guard that gains a reachable input turns into an undetected
hole.

The suite is not re-run here -- that would run the suite 25 times inside the suite. What is
pinned is the contract of the instrument: every mutation still finds its one target, and the
three declared unreachable ones are still the three the code declares.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_ESPEC = importlib.util.spec_from_file_location("mutate", RAIZ / "tools" / "mutate.py")
mutate = importlib.util.module_from_spec(_ESPEC)
_ESPEC.loader.exec_module(mutate)


class ObjetivosVivos(unittest.TestCase):
    def test_cada_mutacion_encuentra_su_objetivo_una_sola_vez(self):
        """`count != 1` is the silent failure mode: the mutation applies to nothing and the
        report calls that mutant covered."""
        for mid, sitio, viejo, _nuevo, _motivo in mutate.MUTANTES:
            with self.subTest(mutante=mid):
                texto = (RAIZ / "ts_py_anchor_guard" / sitio).read_text()
                self.assertEqual(texto.count(viejo), 1,
                                 f"{mid} no casa exactamente una vez en {sitio}")

    def test_los_mutantes_inalcanzables_son_los_que_el_codigo_declara(self):
        declarados = {m[0] for m in mutate.MUTANTES}
        self.assertLessEqual(set(mutate.INALCANZABLES), declarados)
        for mid in mutate.INALCANZABLES:
            with self.subTest(mutante=mid):
                self.assertTrue(mutate.INALCANZABLES[mid].strip())

    def test_un_mutante_desconocido_es_invocacion_mala(self):
        self.assertEqual(mutate.main(["no_existe"]), mutate.RC_ARITY)

    def test_una_bandera_desconocida_es_invocacion_mala(self):
        self.assertEqual(mutate.main(["--mutar-todo"]), mutate.RC_ARITY)


class VeredictoTest(unittest.TestCase):
    def test_un_fallo_del_modulo_propio_es_propio(self):
        err = ("FAIL: test_x (tests.test_viewport_embed.RectTest.test_x)\n"
               "AssertionError: 1 != 2")
        self.assertEqual(mutate._veredicto("viewport_embed.py", err), "propio")

    def test_un_fallo_de_otro_modulo_no_cuenta_como_cobertura(self):
        """The whole point of the column: a kill from an unrelated module is a coincidence
        of one run, and summing it inflates the rate."""
        err = ("ERROR: test_y (tests.test_anchor_oracle.AnclasTest.test_y)\n"
               "json.decoder.JSONDecodeError: Expecting value")
        self.assertEqual(mutate._veredicto("subpixel_probe.py", err), "ajeno")

    def test_sin_marca_no_se_adivina(self):
        self.assertEqual(mutate._veredicto("subpixel_probe.py", "algo se rompio"),
                         "sin_marca")


if __name__ == "__main__":
    unittest.main()
