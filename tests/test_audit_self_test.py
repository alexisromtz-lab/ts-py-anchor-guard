"""Pin the README's claim about which self-tests touch data I/O.

The claim is `0` versus *nonzero*, not a constant: the number of events `live_oracle`
produces is a property of its fixture (one write pair and one process per `node` run), so a
test that pinned `24` would break the moment the fixture changes while the invariant still
held. What is pinned here is the shape that cannot move.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PROBE = RAIZ / "tools" / "audit_self_test.py"
SIN_IO = ("anchor_oracle", "subpixel_probe", "viewport_embed")
CON_IO = "live_oracle"

_ESPEC = importlib.util.spec_from_file_location("audit_self_test", PROBE)
probe = importlib.util.module_from_spec(_ESPEC)
_ESPEC.loader.exec_module(probe)


def correr(*args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(PROBE), *args],
                       capture_output=True, text=True, cwd=RAIZ, timeout=600)
    return p.returncode, p.stdout


class ContratoDelProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rc, out = correr("--json")
        cls.rc, cls.informe = rc, {f["modulo"]: f for f in json.loads(out)}

    def test_tres_modulos_no_tocan_datos(self):
        for modulo in SIN_IO:
            with self.subTest(modulo=modulo):
                self.assertEqual(self.informe[modulo]["n_datos"], 0,
                                 self.informe[modulo].get("datos_fuera_de_stdlib"))

    def test_live_oracle_si_toca_datos_y_los_nombra(self):
        fila = self.informe[CON_IO]
        self.assertGreater(fila["n_datos"], 0)
        vistos = json.dumps(fila["datos_fuera_de_stdlib"])
        self.assertIn("fuente.ts", vistos)
        self.assertIn("subprocess.Popen", vistos)

    def test_rc_1_cuando_alguno_toca_datos(self):
        self.assertEqual(self.rc, 1)
        rc, _ = correr(*SIN_IO)
        self.assertEqual(rc, 0)

    def test_modulo_desconocido_es_20(self):
        self.assertEqual(correr("no_existe")[0], 20)

    def test_el_filtro_de_codigo_no_confunde_carga_con_datos(self):
        """The `.py` branch of the code-loading filter, pinned by the payloads it receives.

        It cannot be pinned from the report: a self-test's lazy import reads `_cli.py` only
        in a cold tree. Once `_cli.cpython-312.pyc` exists — and any test that spawns an
        interpreter without `-B` leaves it — the same import reads the bytecode, and the
        report stays at `0` either way. So the filter is judged on the events an audit hook
        actually produced here, with a data write as the negative control.
        """
        arbol = str(RAIZ)
        carga = (
            f"('{arbol}/ts_py_anchor_guard/_cli.py', 'r', 16777216)",
            f"('{arbol}/ts_py_anchor_guard/__pycache__/_cli.cpython-312.pyc', 'r', 16777216)",
            f"('{arbol}/ts_py_anchor_guard/__pycache__/_cli.cpython-312.pyc.4328636096', None, 16779777)",
        )
        for args in carga:
            with self.subTest(evento=args):
                self.assertTrue(probe._es_carga_de_codigo("open", args))
        self.assertFalse(probe._es_carga_de_codigo(
            "open", "('/var/folders/x/T/oraculo-vivo-y/fuente.ts', 'w', 16778753)"))

    def test_una_ruta_de_codigo_larga_sigue_siendo_carga_de_codigo(self):
        """The filter has to see the event's own arguments, not the 160-character excerpt
        that gets printed: macOS caches system-Python bytecode under
        `~/Library/Caches/com.apple.python/<path>-39.pyc`, and a copy under `$TMPDIR` puts
        the `.pyc` past the cut, which turned code loading into a false data-I/O report."""
        larga = ("/home/user/Library/Caches/com.apple.python/var/folders/ab/" + "z" * 200
                 + "/copia/ts_py_anchor_guard/_cli.cpython-39.pyc")
        self.assertFalse(probe._es_dato("open", (larga, "rb", 16777216)))
        self.assertTrue(probe._es_dato("open", (larga.replace(".pyc", ".json"), "r", 0)))

    def test_lo_que_abre_el_interprete_no_es_io_de_datos(self):
        """Two exclusions that nothing else pins, both measured on the event.

        Neither is reachable from the report: the child runs with `-B`, so no `.pyc` is
        written through a descriptor and nothing in the interpreter's own tree is opened.
        A rule that only the report could show would be a rule no test holds.
        """
        dentro = str(Path(sys.prefix) / "lib" / "python3.12" / "site-packages" / "x.so")
        self.assertFalse(probe._es_dato("open", (dentro, "rb", 0)))
        self.assertFalse(probe._es_dato("open", (3, "wb")))
        self.assertTrue(probe._es_dato("open", (3, "rb")))
        self.assertTrue(probe._es_dato("open", ("/var/folders/x/T/fuente.ts", "w", 0)))

    def test_la_sonda_no_deja_bytecode_en_el_arbol(self):
        """Asking the probe a question must not answer by leaving files behind.

        Without `-B` the lazily imported `_cli` is compiled and written through a bare
        descriptor, and the verdict does not move — the descriptor filter catches it. So the
        flag cannot be pinned by any count: it is pinned by the tree, which a cold copy
        makes observable.
        """
        with tempfile.TemporaryDirectory(prefix="probe-frio-") as tmp:
            copia = Path(tmp) / "copia"
            shutil.copytree(RAIZ, copia, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            p = subprocess.run(
                [sys.executable, str(copia / "tools" / "audit_self_test.py"), *SIN_IO],
                capture_output=True, text=True, cwd=copia, timeout=600)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual([str(x.relative_to(copia)) for x in copia.rglob("*.pyc")], [])


if __name__ == "__main__":
    unittest.main()
