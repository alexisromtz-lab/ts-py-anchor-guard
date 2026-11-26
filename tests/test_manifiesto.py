"""The manifest is data, so every one of its silences has to be a receipt line.

These are the falsadores of `H_manifiesto_declarativo_sin_invencion`: a mapping the
repository declares turns a heterogeneous container into measured fields, a container it
does not declare keeps being refused, a misspelled switch does not pass as absent, and the
aggregate receipt orders its verdicts the way the contract orders them.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ts_py_anchor_guard import RC_ARITY, RC_DIVERGE, RC_NO_MEDIDO, RC_OK
from ts_py_anchor_guard.anchor_oracle import main
from ts_py_anchor_guard.manifiesto import ManifiestoIlegible, cargar, correr

# The two shapes that made the real dogfooding refuse: an object against a tuple, and a
# vector under another name. Same numbers, addresses no reader is allowed to guess.
_OBJETO_TS = "export const CUADRO = { ancho: 1080, alto: 1920 };\n"
_OBJETO_JSON = {"CUADRO": [1080, 1920]}
_MAPA_OBJETO = {"CUADRO.ancho": "CUADRO.0", "CUADRO.alto": "CUADRO.1"}

_VECTOR_TS = "export const NUDOS_S5 = [0.453, 0.764, 1];\n"
_VECTOR_JSON = {"RAMPA_S5": [0.453, 0.764, 1.0]}
_MAPA_VECTOR = {"NUDOS_S5.0": "RAMPA_S5.0", "NUDOS_S5.1": "RAMPA_S5.1",
                "NUDOS_S5.2": "RAMPA_S5.2"}

_ESCALAR_TS = "export const K = 0.15;\n"
_DOS_TS = "export const K = 0.15;\nexport const OTRO = 2;\n"


class ManifiestoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._caja = tempfile.TemporaryDirectory()
        self.raiz = Path(self._caja.name)
        self._escribir_fuente("objeto.ts", _OBJETO_TS, "objeto.json", _OBJETO_JSON)
        self._escribir_fuente("vector.ts", _VECTOR_TS, "vector.json", _VECTOR_JSON)
        self._escribir_fuente("escalar.ts", _ESCALAR_TS, "escalar.json", {"K": 0.15})
        self._escribir_fuente("escalar.ts", _ESCALAR_TS, "escalar_desviado.json", {"K": 0.16})
        self._escribir_fuente("dos.ts", _DOS_TS, "dos.json", {"K": 0.15})

    def tearDown(self) -> None:
        self._caja.cleanup()

    def _escribir_fuente(self, ts: str, texto: str, js: str, referencia: dict) -> None:
        (self.raiz / ts).write_text(texto)
        (self.raiz / js).write_text(json.dumps(referencia))

    def _manifiesto(self, pares: list[dict], nombre: str = "ts-py-anchor.json") -> Path:
        ruta = self.raiz / nombre
        ruta.write_text(json.dumps({"version": 1, "pares": pares}, indent=2))
        return ruta

    def _correr(self, ruta: Path) -> tuple[int, dict]:
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(io.StringIO()):
            rc = correr(ruta, json_out=True)
        crudo = salida.getvalue()
        return rc, (json.loads(crudo) if crudo else {})

    def _par_objeto(self, **extra) -> dict:
        par = {"nombre": "objeto", "fuente": "objeto.ts", "referencia": "objeto.json"}
        par.update(extra)
        return par

    def _par_vector(self, **extra) -> dict:
        par = {"nombre": "vector", "fuente": "vector.ts", "referencia": "vector.json"}
        par.update(extra)
        return par

    def _par_dos(self, **extra) -> dict:
        par = {"nombre": "dos", "fuente": "dos.ts", "referencia": "dos.json"}
        par.update(extra)
        return par

    # ---------------------------------------------------------------- P1 · mapeo declarado

    def test_un_mapeo_declarado_mide_el_contenedor_heterogeneo(self):
        """`CUADRO.ancho` against `CUADRO.0` is a signed correspondence, not an inference.

        The oracle refuses a tuple-valued anchor on purpose; what it lacked was a way for
        the repository to say which address holds the number, so the refusal was permanent
        instead of answerable.
        """
        rc, recibo = self._correr(self._manifiesto(
            [self._par_objeto(mapeos=_MAPA_OBJETO, exigir_cobertura_total=True)]))
        self.assertEqual(rc, RC_OK)
        par = recibo["pares"][0]
        medidos = {f["ancla"]: f["peor_rel"] for f in par["anclas"]}
        self.assertEqual(sorted(medidos), ["CUADRO.alto", "CUADRO.ancho"])
        self.assertEqual(set(medidos.values()), {0.0})
        self.assertEqual(par["cobertura"], {"declaradas": 1, "comparadas": 2,
                                            "omitidas": [], "exigida": True})

    def test_sin_mapeo_el_contenedor_sigue_fuera_y_no_se_empareja_por_posicion(self):
        """No declaration, no measurement: the tuple is named, never guessed.

        This is the falsador of the whole feature. If an undeclared object/tuple pair ever
        comes back with numbers, the tool is measuring the reader's assumption.
        """
        rc, recibo = self._correr(self._manifiesto([self._par_objeto()]))
        self.assertEqual(rc, RC_NO_MEDIDO)
        par = recibo["pares"][0]
        self.assertEqual([f["ancla"] for f in par["no_evaluables"]], ["CUADRO"])
        self.assertEqual(par["anclas"], [])
        self.assertEqual(par["cobertura"]["comparadas"], 0)

    # ---------------------------------------------------------------- P3 · renombre

    def test_un_renombre_sin_mapeo_es_ausencia_y_con_mapeo_es_medicion(self):
        """`NUDOS_S5` and `RAMPA_S5` are the same vector; only a mapping can prove it.

        Without the mapping the name is absent from every row -- neither a pass nor a
        failure -- and only `cobertura.omitidas` says so. With it, every element is
        compared and the equivalence stops being an assertion about the two files.
        """
        rc, sin_mapeo = self._correr(self._manifiesto([self._par_vector(nombre="renombre")]))
        self.assertEqual(rc, RC_NO_MEDIDO)
        par = sin_mapeo["pares"][0]
        self.assertEqual(par["causa"], "REFERENCIA_VACIA")
        self.assertEqual(par["referencia_ignorada"], ["RAMPA_S5"])
        self.assertIn("RAMPA_S5", par["detalle"])
        rc, con_mapeo = self._correr(self._manifiesto(
            [self._par_vector(nombre="renombre", mapeos=_MAPA_VECTOR)], "mapeado.json"))
        self.assertEqual(rc, RC_OK)
        filas = {f["ancla"]: f["peor_rel"] for f in con_mapeo["pares"][0]["anclas"]}
        self.assertEqual(sorted(filas), ["NUDOS_S5.0", "NUDOS_S5.1", "NUDOS_S5.2"])
        self.assertEqual(set(filas.values()), {0.0})

    def test_una_ancla_declarada_sin_mapear_es_un_omitido_y_se_cuenta(self):
        """A declared name that no address covers is the subset `cobertura` has to publish.

        Without the flag it is a report; with the flag it is the defect it looks like.
        """
        rc, recibo = self._correr(self._manifiesto([self._par_dos(nombre="dos")]))
        self.assertEqual(rc, RC_OK)
        self.assertEqual(recibo["pares"][0]["cobertura"]["omitidas"], ["OTRO"])
        rc, recibo = self._correr(self._manifiesto(
            [self._par_dos(nombre="dos", exigir_cobertura_total=True)], "exigido.json"))
        self.assertEqual(rc, RC_NO_MEDIDO)
        self.assertEqual(recibo["pares"][0]["causa"], "COBERTURA_INCOMPLETA")
        self.assertIn("OTRO", recibo["pares"][0]["detalle"])
        self.assertTrue(recibo["pares"][0]["cobertura"]["exigida"])

    # ---------------------------------------------------------------- P4 · fail-closed

    def test_una_clave_mal_escrita_no_se_ignora(self):
        """`exigir_covertura_total` must not pass as "absent": the gate would be off.

        A field that switches a gate is either read or named; a manifest that silently
        drops it turns a signed guarantee into a comment.
        """
        ruta = self._manifiesto([self._par_objeto(exigir_covertura_total=True)], "typo.json")
        with self.assertRaises(ManifiestoIlegible) as fallo:
            cargar(ruta)
        self.assertIn("exigir_covertura_total", str(fallo.exception))
        rc, _ = self._correr(ruta)
        self.assertEqual(rc, RC_NO_MEDIDO)

    def test_un_manifiesto_ilegible_dice_que_no_leyo(self):
        casos = {
            "version": {"version": 2, "pares": [self._par_objeto()]},
            "sin-pares": {"version": 1},
            "vacio": {"version": 1, "pares": []},
            "raiz": {"version": 1, "pares": [self._par_objeto()], "extra": True},
            "mapeos": {"version": 1, "pares": [self._par_objeto(mapeos={"A": 1})]},
            "exigir": {"version": 1, "pares": [self._par_objeto(
                exigir_cobertura_total="si")]},
            "backend": {"version": 1, "pares": [self._par_objeto(backend="chromium")]},
            "tolerancia": {"version": 1, "pares": [self._par_objeto(tolerancia=True)]},
            "fuente": {"version": 1, "pares": [{"referencia": "objeto.json"}]},
        }
        for nombre, documento in casos.items():
            with self.subTest(caso=nombre):
                ruta = self.raiz / f"{nombre}.json"
                ruta.write_text(json.dumps(documento))
                with self.assertRaises(ManifiestoIlegible):
                    cargar(ruta)

    def test_un_manifiesto_ausente_no_se_lee_como_un_cero(self):
        rc, recibo = self._correr(self.raiz / "no-existe.json")
        self.assertEqual(rc, RC_NO_MEDIDO)
        self.assertEqual(recibo, {})

    # ---------------------------------------------------------------- P5 · mapeo roto

    def test_un_mapeo_que_no_resuelve_no_borra_el_resto_del_recibo(self):
        """A path the reference does not hold is a contract defect, not a silent skip."""
        rc, recibo = self._correr(self._manifiesto([self._par_objeto(
            mapeos={"CUADRO.ancho": "CUADRO.7", "CUADRO.alto": "CUADRO.1"})]))
        self.assertEqual(rc, RC_NO_MEDIDO)
        par = recibo["pares"][0]
        self.assertEqual(par["causa"], "MAPEO_INVALIDO")
        self.assertIn("CUADRO.7", par["detalle"])
        self.assertIn("CUADRO.alto", [f["ancla"] for f in par["anclas"]])
        self.assertEqual(par["mapeos_invalidos"][0]["ancla"], "CUADRO.ancho")

    def test_un_mapeo_de_ancla_inexistente_se_rechaza(self):
        """A stale signature is not a signature: the source does not declare that anchor."""
        rc, recibo = self._correr(self._manifiesto([self._par_objeto(
            mapeos={"CUADRO_INEXISTENTE.ancho": "CUADRO.0"})]))
        self.assertEqual(rc, RC_NO_MEDIDO)
        self.assertEqual(recibo["pares"][0]["causa"], "MAPEO_INVALIDO")
        self.assertIn("CUADRO_INEXISTENTE.ancho", recibo["pares"][0]["detalle"])

    def test_una_deriva_no_queda_tapada_por_un_mapeo_roto(self):
        """A measured divergence outranks a contract defect: one of them is about the port."""
        rc, recibo = self._correr(self._manifiesto([{
            "nombre": "escalar", "fuente": "escalar.ts",
            "referencia": "escalar_desviado.json",
            "mapeos": {"CUADRO.ancho": "CUADRO.0"}}]))
        self.assertEqual(rc, RC_DIVERGE)
        self.assertEqual(recibo["pares"][0]["causa"], "DIVERGE")
        self.assertIn("mapeos_invalidos", recibo["pares"][0])

    # ---------------------------------------------------------------- P6 · precedencia

    def test_el_recibo_agregado_ordena_como_el_contrato(self):
        """One diverging pair and one gap return `1`, not the maximum of the codes."""
        rc, recibo = self._correr(self._manifiesto([
            {"nombre": "deriva", "fuente": "escalar.ts",
             "referencia": "escalar_desviado.json"},
            self._par_dos(nombre="hueco", exigir_cobertura_total=True)]))
        self.assertEqual([p["rc"] for p in recibo["pares"]], [RC_DIVERGE, RC_NO_MEDIDO])
        self.assertEqual(rc, RC_DIVERGE)
        self.assertEqual(recibo["totales"]["divergen"], 1)
        self.assertEqual(recibo["totales"]["no_medidos"], 1)
        self.assertEqual(recibo["totales"]["pares"], 2)

    # ---------------------------------------------------------------- P7 · determinismo

    def test_dos_corridas_del_mismo_manifiesto_dan_el_mismo_recibo(self):
        ruta = self._manifiesto([self._par_objeto(mapeos=_MAPA_OBJETO,
                                                  exigir_cobertura_total=True)])
        primero, segundo = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(primero):
            correr(ruta, json_out=True)
        with contextlib.redirect_stdout(segundo):
            correr(ruta, json_out=True)
        self.assertEqual(primero.getvalue(), segundo.getvalue())

    def test_las_rutas_del_par_son_relativas_al_manifiesto(self):
        """A manifest committed next to its sources runs from any working directory."""
        anidado = self.raiz / "contratos"
        anidado.mkdir()
        (anidado / "objeto.ts").write_text(_OBJETO_TS)
        (anidado / "objeto.json").write_text(json.dumps(_OBJETO_JSON))
        ruta = anidado / "ts-py-anchor.json"
        ruta.write_text(json.dumps({"version": 1, "pares": [
            {"nombre": "objeto", "fuente": "objeto.ts", "referencia": "objeto.json",
             "mapeos": _MAPA_OBJETO}]}))
        rc, recibo = self._correr(ruta)
        self.assertEqual(rc, RC_OK)
        self.assertEqual(recibo["totales"]["comparadas"], 2)

    def test_la_tolerancia_del_par_manda_y_la_de_la_invocacion_es_el_defecto(self):
        """A manifest is versioned with the repository: it outranks the command line.

        The invocation is a default for pairs that declare nothing -- never a way to loosen
        a tolerance that is already signed.
        """
        par = {"nombre": "escalar", "fuente": "escalar.ts", "referencia": "escalar_desviado.json"}
        rc, _ = self._correr(self._manifiesto([par], "estricto.json"))
        self.assertEqual(rc, RC_DIVERGE)

        def correr_con(ruta: Path, **kwargs) -> int:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                return correr(ruta, json_out=True, **kwargs)

        ruta = self._manifiesto([par], "defecto-tolerante.json")
        self.assertEqual(correr_con(ruta, tolerancia=0.1), RC_OK)

        ruta = self._manifiesto([dict(par, tolerancia=0.01)], "par-estricto.json")
        self.assertEqual(correr_con(ruta, tolerancia=0.1), RC_DIVERGE)

        ruta = self._manifiesto([dict(par, tolerancia=0.1)], "par-tolerante.json")
        self.assertEqual(correr_con(ruta, tolerancia=0.0), RC_OK)

    def test_exigir_cobertura_desde_la_invocacion_solo_aumenta_el_rigor(self):
        """A flag can turn a report into a defect, never a defect into a report."""
        ruta = self._manifiesto([self._par_dos(nombre="dos")], "sin-exigir.json")
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(io.StringIO()):
            rc = correr(ruta, json_out=True, exigir_cobertura_total=True)
        self.assertEqual(rc, RC_NO_MEDIDO)
        par = json.loads(salida.getvalue())["pares"][0]
        self.assertEqual(par["causa"], "COBERTURA_INCOMPLETA")
        self.assertIn("OTRO", par["detalle"])

    # ---------------------------------------------------------------- CLI

    def test_la_cli_lee_el_manifiesto_y_no_mezcla_dos_formas_de_invocar(self):
        ruta = self._manifiesto([self._par_objeto(mapeos=_MAPA_OBJETO,
                                                  exigir_cobertura_total=True)])
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            rc = main(["--manifest", str(ruta), "--json", "--backend", "estatico"])
        self.assertEqual(rc, RC_OK)
        self.assertEqual(json.loads(salida.getvalue())["totales"]["pares"], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--manifest", str(ruta), "--fuente", "objeto.ts"]),
                             RC_ARITY)


if __name__ == "__main__":  # pragma: no cover - entry for `python tests/...`
    unittest.main()
