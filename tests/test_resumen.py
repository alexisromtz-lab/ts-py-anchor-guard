import contextlib
import io
import json
import unittest
from unittest import mock

from ts_py_anchor_guard import _resumen


class ResumenDeReciboTest(unittest.TestCase):
    """P20: one bounded line, and the whole receipt on disk.

    Measured on the real census of `calcom/cal.com@ae027bb7`: 34 141 B as a single line became
    1 031 B (-97,0 %) with `evaluables`, `declaradas`, `cobertura` and `por_causa` intact. The
    2 KiB ceiling is the whole point -- a job writes many values and a log has to stay readable --
    so the test asserts the ceiling on a receipt far wider than the one that motivated it.
    """

    def _resumir(self, recibo: dict, bytes_original=None):
        corto = _resumen.resumir(recibo, bytes_original=bytes_original)
        return corto, len(_resumen._crudo(corto).encode())

    def test_lo_que_ya_cabe_se_publica_entero(self):
        recibo = {"rc": 0, "cambian": 1}
        self.assertEqual(self._resumir(recibo)[0], recibo)

    def test_el_techo_se_respeta_aunque_el_recibo_sea_enorme(self):
        recibo = {"rc": 0,
                  "censo": {"evaluables": 118, "declaradas": 118, "cobertura": 1.0,
                            "por_causa": {"BLOQUEADA_POR_ANCLA": 54}},
                  "anclas": {f"ANCLA_{i:03d}": {"cuerpo": "x" * 400} for i in range(400)}}
        corto, bytes_corto = self._resumir(recibo)
        self.assertLessEqual(bytes_corto, 2048)
        self.assertEqual(corto["censo"]["evaluables"], 118)
        self.assertEqual(corto["anclas"]["n"], 400)
        self.assertIn("bytes", corto)

    def test_una_lista_larga_conserva_el_orden_y_dice_cuanto_no_viajo(self):
        """A differential's rows are the finding: they travel as rows, and the rest is named."""
        filas = [{"ancla": f"A_{i:02d}", "base": i, "destino": i + 1} for i in range(200)]
        corto, bytes_corto = self._resumir({"rc": 0, "cambian": 200, "filas": filas})
        self.assertLessEqual(bytes_corto, 2048)
        viajadas = corto["filas"]
        # Sin repetición de nombres por fila cuando caben todas, o una muestra en orden cuando no.
        nombres = ([f["ancla"] for f in viajadas["muestra"]] if "muestra" in viajadas
                   else [f[0] for f in viajadas["filas"]])
        self.assertEqual(nombres, [f"A_{i:02d}" for i in range(len(nombres))])
        self.assertEqual(len(nombres) + viajadas.get("_resto", 0), 200)
        self.assertGreater(len(nombres), 0)

    def test_nada_se_cae_sin_decirlo(self):
        """Every key the receipt had is either carried or named in `_resumido`.

        A summary that looked like a complete receipt would be the same lie as a green over zero
        anchors, so the compressed node names what did not travel.
        """
        recibo = {"rc": 0, "a": 1,
                  "censo": {f"k{i}": "v" * 300 for i in range(40)},
                  "anclas": {f"A{i}": "w" * 300 for i in range(40)}}
        corto, _ = self._resumir(recibo)
        for clave in recibo:
            if clave not in corto:
                self.assertIn(clave, corto.get("_resumido", []))
        self.assertEqual(corto["rc"], 0)

    def test_bytes_precia_la_linea_publicada_y_no_el_objeto(self):
        """`bytes` is what the caller's line cost, not a re-serialisation of the same object.

        The caller wrote that line with `json.dumps` default separators, so serialising the object
        again, compactly, yields a shorter string: reporting that would price a line nobody wrote,
        and the ceiling exists to price the line the job actually publishes.
        """
        recibo = {"rc": 0, "anclas": {f"A{i:03d}": "x" * 400 for i in range(200)}}
        publicado = json.dumps(recibo)
        with mock.patch("sys.stdin", io.StringIO(publicado)), \
                contextlib.redirect_stdout(io.StringIO()) as salida:
            self.assertEqual(_resumen.main(), 0)
        corto = json.loads(salida.getvalue())
        self.assertGreater(corto["bytes"], _resumen.LIMITE)
        self.assertEqual(corto["bytes"], len(publicado.replace("\n", "").strip().encode()))

    def test_lo_que_no_es_un_objeto_se_rechaza(self):
        with mock.patch("sys.stdin", io.StringIO("[1, 2, 3]")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(_resumen.main(), 2)
        with mock.patch("sys.stdin", io.StringIO("no json")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(_resumen.main(), 2)


if __name__ == "__main__":
    unittest.main()
