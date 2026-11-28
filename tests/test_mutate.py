"""Pin the README's mutation claim.

The README says which mutations the suite notices and, just as importantly, which ones no
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
import io
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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

    def test_el_flag_B_solo_puede_importar_donde_el_interprete_escribe_pyc(self):
        """The kill rate of `au_sin_B` is a property of the interpreter, and it moves.

        Removing `-B` can only be noticed where an import leaves a `.pyc` behind: measured
        here, 3.12.13 writes two files for a one-line module and the CLT 3.9.6 writes none.
        So the mutant is killed on one interpreter and equivalent on the other, and a rate
        published without saying which is a number with an unstated subject. The declaration
        is tied to the measurement instead.
        """
        with tempfile.TemporaryDirectory(prefix="flag-b-") as caja:
            copia = Path(caja) / "copia"
            shutil.copytree(RAIZ, copia, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            sonda = copia / "tools" / "audit_self_test.py"
            texto = sonda.read_text()
            self.assertEqual(texto.count('[sys.executable, "-B", str('), 1)
            sonda.write_text(texto.replace('[sys.executable, "-B", str(', '[sys.executable, str('))
            subprocess.run([sys.executable, str(sonda), "--sonda", "anchor_oracle"],
                           cwd=copia, capture_output=True, text=True, timeout=600)
            escritos = list(copia.rglob("*.pyc"))
        self.assertEqual(bool(escritos), mutate._persiste_bytecode(),
                         f"el arnes declara {mutate._persiste_bytecode()} y la sonda dejo "
                         f"{[str(x.relative_to(copia)) for x in escritos]}")
        self.assertEqual("au_sin_B" in mutate.INALCANZABLES, not escritos)

    def test_un_mutante_desconocido_es_invocacion_mala(self):
        self.assertEqual(mutate.main(["no_existe"]), mutate.RC_ARITY)

    def test_una_bandera_desconocida_es_invocacion_mala(self):
        self.assertEqual(mutate.main(["--mutar-todo"]), mutate.RC_ARITY)

    def test_sin_sitio_en_el_disco_temporal_no_se_emite_ningun_veredicto(self):
        """A suite that cannot write its own scratch files goes red for the disk, not for the
        mutation: the run has to refuse before it produces a table it cannot pay for."""
        poco = shutil.disk_usage(".")._replace(free=1024)
        with mock.patch.object(mutate.shutil, "disk_usage", return_value=poco):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                rc = mutate.main(["sp_sin_clamp"])
        self.assertEqual(rc, mutate.RC_NO_MEDIDO)
        self.assertIn("NO_MEDIDO", err.getvalue())
        self.assertIn("MiB", err.getvalue())

    def test_una_guarda_que_no_puede_preguntar_el_espacio_tampoco_emite_veredicto(self):
        with mock.patch.object(mutate.shutil, "disk_usage", side_effect=OSError(1, "sin ruta")):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                rc = mutate.main(["sp_sin_clamp"])
        self.assertEqual(rc, mutate.RC_NO_MEDIDO)
        self.assertIn("NO_MEDIDO", err.getvalue())


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


class DecisionPorEtapasTest(unittest.TestCase):
    """The scope of a verdict is published, so a cheap decision has to be a named one.

    Stage one runs only the module that owns the site, with `-f`, over two fresh copies. If that
    module goes red both times, the whole suite cannot add anything to "the test that owns it
    killed it", and paying 125 s per mutant for that sentence is what made the table
    uncertifiable. Only a mutation its owner does not notice reaches the suite.
    """

    MUTANTE = ("sp_borde_izq", "ts_py_anchor_guard/subpixel_probe.py",
               "    if mejor in (-max_shift, max_shift):", "    if mejor == max_shift:",
               "el borde izquierdo de la ventana de busqueda")
    OTRO = ("ve_sin_recorte", "ts_py_anchor_guard/viewport_embed.py",
            "    elif not dentro:", "    elif False:", "la causa RECORTE")
    # La forma que `unittest` imprime de verdad: el metodo antes del parentesis, la clase
    # dentro, y por eso la marca nunca llega al metodo.
    PROPIA = "FAIL: test_x (tests.test_subpixel_probe.FaseTest)"
    AJENA = "FAIL: test_y (tests.test_anchor_oracle.AnclasTest)"

    def _falso(self, respuestas):
        """`_correr` que apunta con que alcance se le llamo y responde de una lista."""
        llamadas = []

        def correr(raiz, solo=None, failfast=False):
            llamadas.append((Path(raiz).name, solo, failfast))
            return respuestas[len(llamadas) - 1]

        return llamadas, correr

    def _caja(self):
        caja = tempfile.TemporaryDirectory(prefix="etapas-")
        self.addCleanup(caja.cleanup)
        return Path(caja.name)

    def test_el_dueno_que_mata_dos_veces_no_paga_la_suite(self):
        llamadas, correr = self._falso([(1, self.PROPIA), (1, self.PROPIA)])
        with mock.patch.object(mutate, "_correr", correr):
            fila = mutate._juzgar(self._caja(), self.MUTANTE)
        self.assertEqual(fila["estado"], "MUERTO")
        self.assertEqual(fila["alcance"], "dueno")
        self.assertEqual(fila["veredicto"], "propio")
        self.assertEqual(fila["detalle"], "tests.test_subpixel_probe.FaseTest")
        self.assertEqual(llamadas, [(self.MUTANTE[0], "subpixel_probe", True),
                                    (f"{self.MUTANTE[0]}-repeticion", "subpixel_probe", True)],
                         "la etapa del dueno es la unica que corre, y corre dos veces")

    def test_un_dueno_que_pasa_entrega_la_decision_a_la_suite(self):
        llamadas, correr = self._falso([(0, ""), (1, self.AJENA), (1, self.AJENA)])
        with mock.patch.object(mutate, "_correr", correr):
            fila = mutate._juzgar(self._caja(), self.MUTANTE)
        self.assertEqual((fila["estado"], fila["veredicto"], fila["alcance"]),
                         ("MUERTO", "ajeno", "suite"))
        self.assertEqual([(c[1], c[2]) for c in llamadas],
                         [("subpixel_probe", True), (None, False), (None, False)])

    def test_la_etapa_del_dueno_y_la_suite_no_comparten_arbol(self):
        """A stage that ran already warmed its tree: the suite cannot inherit that state.

        Se mide sobre la secuencia de actos y no sobre el inodo del fichero. El inodo no es
        estado del objeto: la copia se rehace en el mismo camino, y el sistema entrega al
        fichero nuevo el numero que acaba de liberar el viejo. Medido asi, un inodo repetido
        no prueba una copia repetida, y uno distinto tampoco prueba una copia nueva.
        """
        actos = []

        def mutar(destino, sitio, viejo, nuevo):
            actos.append(f"mutar:{Path(destino).name}")
            return original_mutar(destino, sitio, viejo, nuevo)

        def correr(raiz, solo=None, failfast=False):
            actos.append(f"correr:{Path(raiz).name}")
            return (0, "") if len(actos) == 2 else (1, self.AJENA)

        original_mutar = mutate._mutar
        with mock.patch.object(mutate, "_mutar", mutar), \
                mock.patch.object(mutate, "_correr", correr):
            fila = mutate._juzgar(self._caja(), self.MUTANTE)
        self.assertEqual((fila["estado"], fila["alcance"]), ("MUERTO", "suite"))
        self.assertEqual(actos, [f"mutar:{self.MUTANTE[0]}", f"correr:{self.MUTANTE[0]}",
                                 f"mutar:{self.MUTANTE[0]}", f"correr:{self.MUTANTE[0]}",
                                 f"mutar:{self.MUTANTE[0]}-repeticion",
                                 f"correr:{self.MUTANTE[0]}-repeticion"],
                         "entre la etapa del dueno y la de la suite el arbol se rehace")

    def test_estricto_no_mira_al_dueno(self):
        llamadas, correr = self._falso([(0, "")])
        with mock.patch.object(mutate, "_correr", correr):
            fila = mutate._juzgar(self._caja(), self.MUTANTE, estricto=True)
        self.assertEqual((fila["estado"], fila["alcance"]), ("VIVO", "suite"))
        self.assertEqual(llamadas, [(self.MUTANTE[0], None, False)])

    def test_el_orden_de_las_filas_es_el_de_la_tabla_y_no_el_de_terminacion(self):
        """A report that changes order between runs is a report that cannot be compared."""
        caja = self._caja()

        def correr(raiz, solo=None, failfast=False):
            time.sleep(0.6 if Path(raiz).name == self.MUTANTE[0] else 0)
            return 0, ""

        with mock.patch.object(mutate, "_correr", correr):
            filas, rotos = mutate._repartir(caja, [self.MUTANTE, self.OTRO], 2, False)
        self.assertEqual(rotos, [])
        self.assertEqual([f["id"] for f in filas], [self.MUTANTE[0], self.OTRO[0]])

    def test_el_espacio_se_pide_por_trabajador(self):
        """Workers run suites side by side, so the scratch each one needs is needed at once."""
        poco = shutil.disk_usage(".")._replace(free=mutate.LIBRE_MINIMO * 2 - 1)
        with mock.patch.object(mutate.shutil, "disk_usage", return_value=poco), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = mutate.main(["sp_borde_izq", "--trabajadores", "2"])
        self.assertEqual(rc, mutate.RC_NO_MEDIDO)
        self.assertIn("128 MiB", err.getvalue())
        self.assertIn("2 trabajador", err.getvalue())

    def test_un_trabajador_que_revienta_no_deja_filas_sin_juez(self):
        def correr(raiz, solo=None, failfast=False):
            if Path(raiz).name == "base":
                return 0, ""
            raise RuntimeError("el disco dijo no")

        with mock.patch.object(mutate, "_correr", correr), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = mutate.main(["sp_borde_izq", "--trabajadores", "1"])
        self.assertEqual(rc, mutate.RC_NO_MEDIDO)
        self.assertIn("NO_MEDIDO", err.getvalue())
        self.assertIn("RuntimeError", err.getvalue())


if __name__ == "__main__":
    unittest.main()
