"""Pin the README's mutation claim.

The README says which mutations the suite notices and, just as importantly, which four no
test can notice because no input reaches them. Both halves rot the same way: a mutation whose
target text drifts becomes `NO_APPLICABLE` and is quietly counted as covered, and an
"unreachable" branch that gains a reachable input turns into an undetected hole.

The suite is not re-run here -- that would run the suite 33 times inside the suite. What is
pinned is the contract of the instrument: every mutation still finds its one target, the
declared unreachable ones are still the ones the code declares, and the two runs of a repeat
are compared by the set of failing tests with the copy's own location normalised out.
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
                texto = (RAIZ / sitio).read_text()
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
        self.assertEqual(mutate._veredicto("ts_py_anchor_guard/viewport_embed.py", err), "propio")

    def test_un_fallo_de_otro_modulo_no_cuenta_como_cobertura(self):
        """The whole point of the column: a kill from an unrelated module is a coincidence
        of one run, and summing it inflates the rate."""
        err = ("ERROR: test_y (tests.test_anchor_oracle.AnclasTest.test_y)\n"
               "json.decoder.JSONDecodeError: Expecting value")
        self.assertEqual(mutate._veredicto("ts_py_anchor_guard/subpixel_probe.py", err), "ajeno")

    def test_sin_marca_no_se_adivina(self):
        self.assertEqual(mutate._veredicto("ts_py_anchor_guard/subpixel_probe.py", "algo se rompio"),
                         "sin_marca")

    def test_dos_corridas_que_fallan_el_mismo_test_son_el_mismo_hecho(self):
        """Where the copy lived is an input of the run, not an observation: the same failure
        in two trees differs only by its path, and reading that as non-determinism turns a
        reproducible kill into a FLAKY."""
        uno = ("FAIL: test_x (tests.test_audit_self_test.ContratoDelProbe.test_x) "
               "(evento=\"('/private/var/folders/ab/xyz/mut-1/au_filtro_py/_cli.py', 'r', 0)\")")
        dos = ("FAIL: test_x (tests.test_audit_self_test.ContratoDelProbe.test_x) "
               "(evento=\"('/private/var/folders/ab/xyz/mut-2/au_filtro_py-repeticion/_cli.py', 'r', 0)\")")
        copia = Path("/private/var/folders/ab/xyz/mut-2/au_filtro_py-repeticion")
        normalizado = dos.replace(str(copia.parent), "<corrida>")
        self.assertEqual(mutate._marcas(normalizado),
                         ("tests.test_audit_self_test.ContratoDelProbe.test_x",))
        self.assertEqual(mutate._marcas(uno.replace("/private/var/folders/ab/xyz/mut-1", "<corrida>")),
                         mutate._marcas(normalizado))

    def test_el_reporte_nombra_al_dueno_del_mutante(self):
        """A foreign test can fail first and still not be the killer: printing it next to a
        `propio` verdict makes the report unreadable."""
        err = ("FAIL: t (tests.test_audit_self_test.C.t)\n"
               "FAIL: u (tests.test_subpixel_probe.C.u)")
        self.assertEqual(mutate._marca(err), "tests.test_audit_self_test.C.t")
        self.assertEqual(mutate._marca_propia("ts_py_anchor_guard/subpixel_probe.py", err),
                         "tests.test_subpixel_probe.C.u")
        self.assertEqual(mutate._marca_propia("ts_py_anchor_guard/anchor_oracle.py", err),
                         "tests.test_audit_self_test.C.t")

    def test_dos_fallos_y_uno_no_es_el_mismo_hecho(self):
        """A subset is not a repeat: comparing only the first failure would call A+B and A
        the same run."""
        uno = ("FAIL: test_a (tests.test_x.C.test_a)\nFAIL: test_b (tests.test_x.C.test_b)")
        dos = "FAIL: test_a (tests.test_x.C.test_a)"
        self.assertNotEqual(mutate._marcas(uno), mutate._marcas(dos))
        self.assertEqual(mutate._veredicto("ts_py_anchor_guard/subpixel_probe.py",
                                           "FAIL: t (tests.test_ajeno.C.t)\n"
                                           "FAIL: u (tests.test_subpixel_probe.C.u)"),
                         "propio")


if __name__ == "__main__":
    unittest.main()
