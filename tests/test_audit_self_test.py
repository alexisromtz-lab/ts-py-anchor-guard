"""Pin the README's claim about which self-tests touch data I/O.

The claim is `0` versus *nonzero*, not a constant: the number of events `live_oracle`
produces is a property of its fixture (one write pair and one process per `node` run), so a
test that pinned `24` would break the moment the fixture changes while the invariant still
held. What is pinned here is the shape that cannot move.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PROBE = RAIZ / "tools" / "audit_self_test.py"
SIN_IO = ("anchor_oracle", "subpixel_probe", "viewport_embed")
CON_IO = "live_oracle"


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


if __name__ == "__main__":
    unittest.main()
