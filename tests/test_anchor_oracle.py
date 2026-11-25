import json
import pathlib
import unittest

from ts_py_anchor_guard.anchor_oracle import (
    RC_ARITY, RC_DIVERGE, RC_NO_MEDIDO, RC_OK, AnclaDesconocida, FuenteIlegible,
    comparar, evaluar, extraer_anclas, main, residuo_de_redondeo,
)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FUENTE = (RAIZ / "fixtures" / "engine.ts").read_text()
REFERENCIA = json.loads((RAIZ / "fixtures" / "anchors.json").read_text())


class AnclasTest(unittest.TestCase):
    def test_lee_constantes_y_funciones_y_descarta_lo_que_no_entiende(self):
        anclas = extraer_anclas("""
            export const A = 864;
            const B: number = 1725 / 1344;
            const f = (u: number) => u * u;
            const g = (u) => { return u; };
            export const OBJETO: { w: number } = { w: 1 };
            // const COMENTADA = 3;
        """)
        self.assertEqual(sorted(anclas), ["A", "B", "OBJETO", "f"])
        self.assertEqual(anclas["B"]["cuerpo"], "1725 / 1344")
        self.assertEqual(anclas["f"]["params"], ["u"])

    def test_solo_lee_declaraciones_de_modulo(self):
        """A local promoted to a module anchor is a silent overwrite hazard."""
        anclas = extraer_anclas("""
            export const A = 864;
            export const caja = (v: number): boolean => {
              const m = v / 1.2;
              let z = m;
              return z < 1;
            };
        """)
        self.assertEqual(sorted(anclas), ["A"])

    def test_cuerpo_multilinea_y_anotacion_de_retorno(self):
        anclas = extraer_anclas("""
            export const C = { ancho: 1080, alto: 1920 } as const;
            export const rect = (y?: number) => ({
              left: (C.ancho - 864) / 2,
              top: y ?? (C.alto - 960) / 2,
            });
        """)
        self.assertEqual(sorted(anclas), ["C", "rect"])
        self.assertEqual(anclas["rect"]["params"], ["y"])
        self.assertEqual(evaluar(anclas, "rect.left"), [108.0])
        self.assertEqual(evaluar(anclas, "rect.top", [None]), [480.0])
        self.assertEqual(evaluar(anclas, "rect.top", [500.0]), [500.0])

    def test_un_literal_devuelto_pide_un_campo_en_vez_de_inventar(self):
        anclas = extraer_anclas("const C = { ancho: 1080 };")
        self.assertEqual(evaluar(anclas, "C.ancho"), 1080.0)
        with self.assertRaises(FuenteIlegible):
            evaluar(anclas, "C.no_existe")
        recibo = comparar(None, {"C": 1080.0}, anclas=anclas)
        self.assertEqual(recibo["rc"], RC_NO_MEDIDO)
        self.assertEqual(recibo["causa"], "ANCLA_NO_EVALUABLE")

    def test_potencia_liga_mas_que_producto_y_asocia_a_derecha(self):
        anclas = extraer_anclas("const k = (u) => 3 * u ** 2 + 2 ** u ** 2;")
        self.assertEqual(evaluar(anclas, "k", [2.0]), [3 * 4 + 16])

    def test_redondeo_js_y_python_difieren_en_el_medio(self):
        anclas = extraer_anclas("const r = (v) => Math.round(v);")
        self.assertEqual(evaluar(anclas, "r", [0.5, -0.5, 2.5]), [1.0, 0.0, 3.0])
        self.assertEqual([round(v) for v in (0.5, -0.5, 2.5)], [0, 0, 2])

    def test_nombre_no_declarado_no_se_adivina(self):
        anclas = extraer_anclas("const a = b + 1;")
        with self.assertRaises(FuenteIlegible):
            evaluar(anclas, "a")

    def test_ciclo_de_constantes_se_declara(self):
        anclas = extraer_anclas("const a = b;\nconst b = a;")
        with self.assertRaises(FuenteIlegible):
            evaluar(anclas, "a")

    def test_ancla_inexistente_es_error_no_cero(self):
        with self.assertRaises(AnclaDesconocida):
            evaluar(extraer_anclas("const a = 1;"), "no_existe")


class ComparacionTest(unittest.TestCase):
    def test_la_referencia_del_fixture_conforma_a_tolerancia_cero(self):
        recibo = comparar(FUENTE, REFERENCIA)
        self.assertEqual(recibo["rc"], RC_OK, recibo)
        self.assertEqual(len(recibo["anclas"]), len(REFERENCIA))

    def test_un_puerto_que_cuantiza_la_lona_diverge_y_el_residuo_lo_nombra(self):
        """The defect this module exists for: 985.714 kept, 986 stored."""
        port = dict(REFERENCIA, PLATE_W=986.0)
        recibo = comparar(FUENTE, port)
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        fila = next(f for f in recibo["anclas"] if f["ancla"] == "PLATE_W")
        self.assertFalse(fila["ok"])
        self.assertEqual(fila["cuantizacion"], "round")
        self.assertEqual(fila["residuo_px"]["round"]["valor"], 986)
        self.assertAlmostEqual(fila["residuo_px"]["round"]["residuo"], -0.2857142857142776)

    def test_el_error_de_una_ley_se_localiza_en_su_punto(self):
        port = dict(REFERENCIA, pulse={"puntos": [0, 0.5, 1.0], "valores": [0.0, 15.225, 1.0]})
        recibo = comparar(FUENTE, port)
        fila = next(f for f in recibo["anclas"] if f["ancla"] == "pulse")
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        self.assertEqual(fila["peor_punto"], 1.0)
        self.assertIsNone(fila["cuantizacion"])

    def test_tolerancia_declarada_absorbe_ruido_de_ida_y_vuelta(self):
        port = dict(REFERENCIA, PLATE_W=985.7142857143)
        self.assertEqual(comparar(FUENTE, port)["rc"], RC_DIVERGE)
        self.assertEqual(comparar(FUENTE, port, tolerancia=1e-6)["rc"], RC_OK)

    def test_ancla_ausente_o_fuente_vacia_es_no_medido(self):
        self.assertEqual(comparar(FUENTE, {"NO_EXISTE": 1.0})["rc"], RC_NO_MEDIDO)
        self.assertEqual(comparar(FUENTE, {"NO_EXISTE": 1.0})["causa"], "ANCLA_NO_DECLARADA")
        self.assertEqual(comparar(None, {"A": 1.0})["rc"], RC_NO_MEDIDO)
        self.assertEqual(comparar("// nada evaluable", {"A": 1.0})["rc"], RC_NO_MEDIDO)

    def test_una_ancla_ilegible_es_no_medido_y_no_una_excepcion(self):
        """A declared anchor the reader cannot evaluate must not slip through as conforming."""
        fuente = FUENTE + "\nexport const reduce_algo = (v: number) => [1.0].reduce((a, b) => b);"
        recibo = comparar(fuente, {"reduce_algo": {"puntos": [1.0], "valores": [1.0]}})
        self.assertEqual(recibo["rc"], RC_NO_MEDIDO)
        self.assertEqual(recibo["causa"], "ANCLA_NO_EVALUABLE")
        self.assertEqual([f["ancla"] for f in recibo["no_evaluables"]], ["reduce_algo"])

    def test_una_divergencia_manda_sobre_un_hueco(self):
        fuente = FUENTE + "\nexport const reduce_algo = (v: number) => [1.0].reduce((a, b) => b);"
        recibo = comparar(fuente, {"reduce_algo": {"puntos": [1.0], "valores": [1.0]},
                                   "PLATE_W": 986.0})
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        self.assertEqual(len(recibo["no_evaluables"]), 1)

    def test_el_fixture_ejercita_la_forma_real_y_declara_su_limite(self):
        """The published fixture must carry the shapes the reader gets wrong, not only the easy ones."""
        anclas = extraer_anclas(FUENTE)
        for nombre in ("BOX", "VIEW", "rectView", "NEAR", "nearestNode"):
            self.assertIn(nombre, anclas)
        for local in ("m", "d", "gap", "onNode"):
            self.assertNotIn(local, anclas, f"{local} no es una ancla de modulo")
        recibo = comparar(FUENTE, {"nearestNode": {"puntos": [3.1], "valores": [3.0]}})
        self.assertEqual(recibo["rc"], RC_NO_MEDIDO)
        self.assertEqual(recibo["causa"], "ANCLA_NO_EVALUABLE")

    def test_residuo_reporta_las_tres_politicas(self):
        residuo = residuo_de_redondeo(60.85714285714286)
        self.assertEqual(residuo["floor"]["valor"], 60)
        self.assertEqual(residuo["ceil"]["valor"], 61)
        self.assertEqual(residuo["round"]["valor"], 61)


class ContratoTest(unittest.TestCase):
    def test_autotest_y_aridad(self):
        self.assertEqual(main(["--self-test"]), RC_OK)
        self.assertEqual(main([]), RC_ARITY)

    def test_cli_sobre_el_fixture_devuelve_cero(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as salida:
            rc = main(["--fuente", str(RAIZ / "fixtures" / "engine.ts"),
                       "--referencia", str(RAIZ / "fixtures" / "anchors.json")])
        self.assertEqual(rc, RC_OK)
        self.assertIn("CONFORME", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
