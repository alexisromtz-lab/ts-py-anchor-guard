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

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ts_py_anchor_guard import live_oracle

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


class InsumoQueNoSePuedeMedir(unittest.TestCase):
    """`1` is "the port diverges" and it is also what an uncaught exception returns.

    A profile too short to divide into bands raised `PerfilInvalido` out of `main`, an empty
    reference made `comparar` conform over zero anchors and then `max()` over an empty
    sequence, and both left the process at `1` -- a verdict about the subject that no
    measurement backed. Nothing was measured, so both answer `2` and name the reason.
    """

    def test_un_perfil_vacio_es_un_motivo_y_no_una_divergencia(self):
        with tempfile.TemporaryDirectory() as caja:
            vacio = Path(caja) / "vacio.txt"
            vacio.write_text("")
            p = correr("subpixel_probe", "--a", str(vacio), "--b", str(vacio))
        self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
        self.assertIn("NO_MEDIDO · PERFIL_INVALIDO", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_una_referencia_vacia_no_conforma_nada(self):
        with tempfile.TemporaryDirectory() as caja:
            vacia = Path(caja) / "vacia.json"
            vacia.write_text("{}")
            p = correr("anchor_oracle", "--backend", "estatico", "--fuente",
                       str(RAIZ / "fixtures" / "engine.ts"), "--referencia", str(vacia))
        self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
        self.assertIn("NO_MEDIDO · REFERENCIA_VACIA", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_una_referencia_que_no_es_un_objeto_no_se_lee(self):
        with tempfile.TemporaryDirectory() as caja:
            lista = Path(caja) / "lista.json"
            lista.write_text("[]")
            p = correr("anchor_oracle", "--backend", "estatico", "--fuente",
                       str(RAIZ / "fixtures" / "engine.ts"), "--referencia", str(lista))
        self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
        self.assertIn("NO_MEDIDO · INSUMO_ILEGIBLE", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_el_lector_sin_nombres_no_mide(self):
        with tempfile.TemporaryDirectory() as caja:
            vacia = Path(caja) / "vacia.json"
            vacia.write_text("{}")
            p = correr("live_oracle", "--fuente",
                       str(RAIZ / "fixtures" / "engine.ts"), "--referencia", str(vacia))
        self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
        self.assertIn("NO_MEDIDO · REFERENCIA_VACIA", p.stderr)

    @unittest.skipUnless(live_oracle.version_de_nodo(), "node >= 22.6 no disponible")
    def test_el_lector_con_una_fuente_sin_anclas_no_imprime_un_verde_vacio(self):
        with tempfile.TemporaryDirectory() as caja:
            vacia = Path(caja) / "vacia.ts"
            vacia.write_text("// sin declaraciones\n")
            p = correr("live_oracle", "--fuente", str(vacia), "--referencia",
                       str(RAIZ / "fixtures" / "anchors.json"))
        self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
        self.assertIn("NO_MEDIDO · SIN_ANCLAS_LEGIBLES", p.stderr)
        self.assertNotIn("null", p.stdout)

    @unittest.skipUnless(live_oracle.version_de_nodo(), "node >= 22.6 no disponible")
    def test_un_ancla_que_existe_y_no_da_ni_numero_ni_texto_tampoco_es_una_medicion(self):
        """A boolean crosses as itself and the guard turns it into a hole.

        Text is a value, so it prints: what a `--referencia` without values asks for is what
        the source evaluated to. Where a number is *required* —a comparison— the judgment
        belongs to `anchor_oracle`, and the second half of this test is that falsador.
        """
        with tempfile.TemporaryDirectory() as caja:
            fuente = Path(caja) / "bandera.ts"
            fuente.write_text("export const bandera = (v: number) => v > 0;\n")
            ref = Path(caja) / "ref.json"
            ref.write_text('{"bandera": {"puntos": [7]}}')
            p = correr("live_oracle", "--fuente", str(fuente), "--referencia", str(ref))
            self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
            self.assertIn("NO_MEDIDO · SIN_ANCLAS_LEGIBLES", p.stderr)

            texto = Path(caja) / "etiqueta.ts"
            texto.write_text("export const etiqueta = (v: number) => String(v);\n")
            ref.write_text('{"etiqueta": 7}')
            p = correr("anchor_oracle", "--fuente", str(texto), "--referencia", str(ref),
                       "--backend", "node", "--json")
        self.assertEqual(p.returncode, RC_NO_MEDIDO, p.stderr)
        recibo = json.loads(p.stdout)
        self.assertEqual(recibo["causa"], "ANCLA_NO_EVALUABLE")
        # The motive names the shape it got instead of a number, so the caller can act.
        self.assertIn("texto", recibo["no_evaluables"][0]["motivo"])


class ElBordeTraduceElChoque(unittest.TestCase):
    """The last net belongs to the boundary, and it must not swallow the subject's code."""

    def test_una_falla_interna_sale_dos_y_nombra_su_tipo(self):
        from ts_py_anchor_guard._cli import correr as borde

        def revienta(argv=None):
            raise RuntimeError("boom")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(borde(revienta), RC_NO_MEDIDO)
        self.assertIn("NO_MEDIDO · FALLA_INTERNA · RuntimeError: boom", err.getvalue())

    def test_el_codigo_del_sujeto_pasa_intacto(self):
        from ts_py_anchor_guard._cli import correr as borde

        for codigo in (RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY):
            with self.subTest(codigo=codigo):
                self.assertEqual(borde(lambda argv=None, c=codigo: c), codigo)


if __name__ == "__main__":
    unittest.main()


class VersionDeclarada(unittest.TestCase):
    """`__version__` and `pyproject.toml` are two copies of one fact.

    They were already the same string by luck, which is the same guarantee as no guarantee.
    """

    def test_version_coincide_con_pyproject(self):
        import re
        from pathlib import Path as _P

        import ts_py_anchor_guard as paquete

        raiz = _P(__file__).resolve().parents[1]
        texto = (raiz / "pyproject.toml").read_text(encoding="utf-8")
        try:
            import tomllib
            declarada = tomllib.loads(texto)["project"]["version"]
        except ImportError:  # 3.9/3.10: the package needs 3.11, its tests outlive that
            seccion = texto.split("[project]", 1)[1].split("\n[", 1)[0]
            declarada = re.search(r'^version\s*=\s*"([^"]+)"', seccion, re.M).group(1)
        self.assertEqual(paquete.__version__, declarada)
