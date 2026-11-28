import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
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


RAIZ = pathlib.Path(__file__).resolve().parent.parent

# Every value `action.yml` exports. The step runs under `set -u`, so an unset one aborts it and
# the test would measure its own environment instead of the wiring.
ENTRADAS = (
    "ENTRADA_CHECK", "ENTRADA_SELF_TEST", "ENTRADA_SOURCE", "ENTRADA_REFERENCE",
    "ENTRADA_MANIFEST", "ENTRADA_BACKEND", "ENTRADA_TOLERANCE", "ENTRADA_PROFILE_A",
    "ENTRADA_PROFILE_B", "ENTRADA_BANDS", "ENTRADA_CANVAS", "ENTRADA_WINDOW", "ENTRADA_RECT",
    "ENTRADA_RECEIPT_FILE", "ENTRADA_ENVIRONMENT", "ENTRADA_ENV_BASE", "ENTRADA_ENV_DESTINO",
    "ENTRADA_EXIGIR_INVARIANCIA",
)


def guion_del_paso() -> str:
    """The composite's `run:` body, taken from `action.yml` rather than copied beside it."""
    lineas = (RAIZ / "action.yml").read_text().splitlines()
    desde = next(k for k, linea in enumerate(lineas) if linea.strip() == "run: |")
    cuerpo = []
    for linea in lineas[desde + 1:]:
        if linea.strip() and not linea.startswith(" " * 8):
            break
        cuerpo.append(linea[8:])
    return "\n".join(cuerpo) + "\n"


class PasoDePublicacionTest(unittest.TestCase):
    """The publish path, replayed as the shell runs it -- because it is bash, not Python.

    Run 46104450819: a module that refuses before reading prints its cause on stderr and nothing
    on stdout, and the step handed that empty string to the summariser. What the caller then read
    was the summariser's `rc=2` in place of the module's, and the step failed with `rechazar`'s
    20, naming the wrong subject. No test of `_resumen` could see it: the module was right.
    """

    def _correr(self, entradas: dict):
        with tempfile.TemporaryDirectory() as tmp:
            guion = pathlib.Path(tmp) / "paso.sh"
            guion.write_text(guion_del_paso())
            salida = pathlib.Path(tmp) / "outputs.txt"
            resumen = pathlib.Path(tmp) / "summary.md"
            salida.touch()
            resumen.touch()
            entorno = {nombre: "" for nombre in ENTRADAS}
            entorno.update(entradas)
            entorno.update({"GUARDA": str(RAIZ), "GITHUB_OUTPUT": str(salida),
                            "GITHUB_STEP_SUMMARY": str(resumen), "PATH": os.environ["PATH"],
                            "HOME": os.environ.get("HOME", tmp), "TMPDIR": tmp})
            hecho = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(guion)],
                cwd=RAIZ, env=entorno, capture_output=True, text=True)
            valores = dict(linea.split("=", 1)
                           for linea in salida.read_text().splitlines() if "=" in linea)
            return hecho.returncode, valores, resumen.read_text()

    def test_un_modulo_que_no_publica_recibo_no_se_resume(self):
        rc, valores, resumen = self._correr({
            "ENTRADA_CHECK": "anchor", "ENTRADA_SOURCE": "fixtures/no_existe.ts",
            "ENTRADA_REFERENCE": "fixtures/anchors.json", "ENTRADA_BACKEND": "estatico"})
        self.assertEqual(rc, 2, "el paso devuelve el codigo del modulo, no el 20 del rechazo")
        self.assertEqual(valores["rc"], "2")
        self.assertEqual(valores["receipt"], "")
        self.assertIn("ningun recibo en stdout", resumen)

    def test_un_recibo_de_verdad_sale_en_una_linea_y_con_su_tamano(self):
        rc, valores, resumen = self._correr({
            "ENTRADA_CHECK": "census", "ENTRADA_SOURCE": "fixtures/engine.ts"})
        self.assertEqual(rc, 0)
        self.assertLessEqual(len(valores["receipt"].encode()), _resumen.LIMITE)
        self.assertIn("```json", resumen)
