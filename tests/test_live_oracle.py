import json
import pathlib
import unittest
from unittest import mock

from ts_py_anchor_guard import live_oracle
from ts_py_anchor_guard.anchor_oracle import (
    RC_DIVERGE, RC_NO_MEDIDO, RC_OK, comparar, extraer_anclas, main,
)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FUENTE = (RAIZ / "fixtures" / "engine.ts").read_text()
REFERENCIA = json.loads((RAIZ / "fixtures" / "anchors.json").read_text())
NODO = live_oracle.version_de_nodo()

_MINIMA = """
export const A = 864;
export const CAJA = { ancho: 1080 } as const;
export const rect = (y?: number) => ({ top: y ?? 480, ancho: CAJA.ancho });
export const etiqueta = (v: number) => String(v);
"""


@unittest.skipUnless(NODO, "node >= 22.6 no disponible")
class OraculoVivoTest(unittest.TestCase):
    def test_mide_constantes_funciones_y_miembros_del_resultado(self):
        vivos, motivo = live_oracle.medir(_MINIMA, {
            "A": 864, "CAJA.ancho": 1080,
            "rect.top": {"puntos": [None, 500], "valores": [480, 500]},
            "rect.ancho": {"puntos": [0], "valores": [1080]},
        })
        self.assertEqual(motivo, "")
        self.assertEqual(vivos["A"], [864])
        self.assertEqual(vivos["CAJA.ancho"], [1080])
        self.assertEqual(vivos["rect.top"], [480, 500])
        self.assertEqual(vivos["rect.ancho"], [1080])

    def test_un_valor_que_no_es_numero_se_conserva_como_hueco(self):
        vivos, _ = live_oracle.medir(_MINIMA, {"etiqueta": {"puntos": [1], "valores": [1]},
                                               "NO_EXISTE": 0})
        self.assertEqual(vivos["etiqueta"], [None])
        self.assertEqual(vivos["NO_EXISTE"], [None])

    def test_una_fuente_que_no_compila_es_un_motivo_no_un_cero(self):
        vivos, motivo = live_oracle.medir("export const A = ;", {"A": 1})
        self.assertEqual(vivos, {})
        self.assertIn("node rc", motivo)

    def test_una_caja_temporal_llena_es_un_motivo_y_no_una_excepcion(self):
        with mock.patch.object(pathlib.Path, "write_text",
                               side_effect=OSError(28, "No space left on device")):
            vivos, motivo = live_oracle.medir(_MINIMA, {"A": 864}, nodo=("/bin/false", []))
        self.assertEqual(vivos, {})
        self.assertIn("caja temporal no escribible", motivo)
        self.assertIn("28", motivo)


class BackendDeclaradoTest(unittest.TestCase):
    def test_el_recibo_nombra_el_backend_que_midio(self):
        recibo = comparar(FUENTE, {"PLATE_W": 985.7142857142857}, backend="estatico")
        self.assertEqual(recibo["rc"], RC_OK)
        self.assertEqual(recibo["backend"], "estatico")

    @unittest.skipUnless(NODO, "node >= 22.6 no disponible")
    def test_el_backend_vivo_conforma_y_lo_declara(self):
        vivos, motivo = live_oracle.medir(FUENTE, REFERENCIA)
        self.assertEqual(motivo, "")
        recibo = comparar(FUENTE, REFERENCIA, vivos=vivos, backend="node prueba")
        self.assertEqual(recibo["rc"], RC_OK, recibo)
        self.assertEqual(recibo["backend"], "node prueba")
        self.assertEqual(len(recibo["anclas"]), len(REFERENCIA))

    @unittest.skipUnless(NODO, "node >= 22.6 no disponible")
    def test_el_backend_vivo_sigue_divergiendo_cuando_el_port_cuantiza(self):
        port = dict(REFERENCIA, PLATE_W=986.0)
        vivos, _ = live_oracle.medir(FUENTE, port)
        recibo = comparar(FUENTE, port, vivos=vivos, backend="node prueba")
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        fila = next(f for f in recibo["anclas"] if f["ancla"] == "PLATE_W")
        self.assertEqual(fila["cuantizacion"], "round")

    def test_pedir_node_sin_node_es_no_medido_y_no_un_repliegue_silencioso(self):
        with mock.patch.object(live_oracle, "version_de_nodo", return_value=None):
            with mock.patch("sys.stderr"):
                rc = main(["--fuente", str(RAIZ / "fixtures" / "engine.ts"),
                           "--referencia", str(RAIZ / "fixtures" / "anchors.json"),
                           "--backend", "node"])
        self.assertEqual(rc, RC_NO_MEDIDO)


class FronteraDeVersionTest(unittest.TestCase):
    """El borde que el README publica, medido con binarios reales desde npx."""

    def test_la_frontera_de_node_es_la_que_el_readme_publica(self):
        casos = [("v22.5.9", None),
                 ("v22.6.0", ["--experimental-strip-types"]),
                 ("v23.5.0", ["--experimental-strip-types"]),
                 ("v23.6.0", []),
                 ("v24.15.0", [])]
        for etiqueta, banderas in casos:
            with mock.patch.object(live_oracle.shutil, "which",
                                   return_value="/usr/bin/node"), \
                 mock.patch.object(live_oracle.subprocess, "run",
                                   return_value=mock.Mock(stdout=etiqueta + "\n")):
                obtenido = live_oracle.version_de_nodo()
            if banderas is None:
                self.assertIsNone(obtenido, etiqueta)
            else:
                self.assertEqual(obtenido, ("/usr/bin/node", banderas), etiqueta)


class FuenteRealTest(unittest.TestCase):
    """The shapes a line-based reader got wrong, kept as a regression on the reader."""

    def test_una_funcion_que_el_lector_no_evalua_es_medible_por_node(self):
        fuente = _MINIMA + "\nexport const cerca = (v: number) => [1.8, 3.0].reduce((a, b) => b);"
        anclas = extraer_anclas(fuente)
        self.assertIn("cerca", anclas)
        recibo = comparar(fuente, {"cerca": {"puntos": [1.0], "valores": [3.0]}}, anclas=anclas)
        self.assertEqual(recibo["rc"], RC_NO_MEDIDO)
        if not NODO:
            return
        vivos, motivo = live_oracle.medir(
            fuente, {"cerca": {"puntos": [1.0], "valores": [3.0]}})
        self.assertEqual(motivo, "")
        vivo = comparar(fuente, {"cerca": {"puntos": [1.0], "valores": [3.0]}},
                        anclas=anclas, vivos=vivos, backend="node prueba")
        self.assertEqual(vivo["rc"], RC_OK, vivo)
