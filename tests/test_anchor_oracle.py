import json
import pathlib
import re
import unittest
from unittest import mock

from ts_py_anchor_guard import live_oracle
from ts_py_anchor_guard.anchor_oracle import (
    RC_ARITY, RC_DIVERGE, RC_NO_MEDIDO, RC_OK, AnclaDesconocida, FuenteIlegible,
    comparar, evaluar, extraer_anclas, main, medir_vivos, residuo_de_redondeo,
)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FUENTE = (RAIZ / "fixtures" / "engine.ts").read_text()
REFERENCIA = json.loads((RAIZ / "fixtures" / "anchors.json").read_text())

# La fuente mas corta que el lector vivo tiene que poder cargar.
_FUENTE_CORTA = """
export const A = 864;
export const CAJA = { ancho: 1080 } as const;
"""


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

    def test_round_es_el_medio_hacia_arriba_y_no_un_sesgo(self):
        """`floor(x + 0.4)` reports the same policy for most numbers and a different one
        exactly where the caller is looking: a residual of 0.45 is the case that names the
        quantiser, and it was the case the fixture did not carry.
        """
        residuo = residuo_de_redondeo(0.55)
        self.assertEqual(residuo["floor"]["valor"], 0)
        self.assertEqual(residuo["round"]["valor"], 1)
        self.assertEqual(residuo["ceil"]["valor"], 1)
        self.assertAlmostEqual(residuo["round"]["residuo"], -0.45, places=12)

    def test_el_error_relativo_se_mide_contra_el_valor_esperado(self):
        """`peor_rel` is the number a tolerance is argued in, and it was never checked.

        An absolute error of 2 on an expected 1002 is 2.0e-3, not 2.0: reporting the
        absolute value as relative makes every anchor look a thousand times worse and
        sends the reader to the wrong cause.
        """
        recibo = comparar("export const X = 1000;", {"X": 1002})
        fila = recibo["anclas"][0]
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        self.assertEqual(fila["peor_abs"], 2.0)
        self.assertAlmostEqual(fila["peor_rel"], 2 / 1002, places=12)

    def test_una_referencia_con_un_vector_no_tumba_las_demas_anclas(self):
        """One array in the reference used to take the whole receipt with it.

        `float(esperado)` ran outside the guard, so a production port that hands back
        `RAMPA_MEDIDA = (0.453, 0.764, 1.0)` raised `TypeError` and the file's scalar
        anchors were never reported -- a `NO_MEDIDO` with a traceback instead of a named
        gap. The remedy is already in the contract: an indexed path measures the element.
        """
        fuente = "export const RAMPA = [0.453, 0.764, 1];\nconst K = 3;\n"
        recibo = comparar(fuente, {"RAMPA": [0.453, 0.764, 1.0], "K": 3.0})
        self.assertEqual(recibo["rc"], RC_NO_MEDIDO)
        self.assertEqual(recibo["causa"], "ANCLA_NO_EVALUABLE")
        self.assertEqual([f["ancla"] for f in recibo["anclas"]], ["K"])
        self.assertIn("RAMPA.0", recibo["no_evaluables"][0]["motivo"])
        medido = comparar(fuente, {"RAMPA.0": 0.453, "RAMPA.2": 1.0, "K": 3.0})
        self.assertEqual(medido["rc"], RC_OK)
        self.assertEqual([f["ancla"] for f in medido["anclas"]],
                         ["RAMPA.0", "RAMPA.2", "K"])

    def test_el_recibo_declara_la_cobertura_que_no_uso(self):
        """A green over a subset is a green over that subset, and the receipt must say so.

        Measured on a real engine: `rc 0` came back over 3 of 7 declared anchors and no
        field carried the other 4, so a reader could not tell a full pass from a pass over
        the one anchor that happened to have a Python counterpart with the same name.
        """
        fuente = "export const A = 1;\nconst B = 2;\nconst f = (u) => u;\n"
        recibo = comparar(fuente, {"A": 1.0})
        self.assertEqual(recibo["rc"], RC_OK)
        self.assertEqual(recibo["cobertura"],
                         {"declaradas": 3, "comparadas": 1, "omitidas": ["B", "f"],
                          "exigida": False})
        completo = comparar(fuente, {"A": 1.0, "B": 2.0})
        self.assertEqual(completo["cobertura"]["omitidas"], ["f"])

    def test_la_cobertura_exigida_convierte_un_omitido_en_hueco(self):
        """A repository that signs for total coverage does not get to keep a partial green.

        The same receipt that is `RC 0` when the subset is a report is `RC 2` when the
        subset contradicts a declared expectation -- and the divergence still outranks it,
        because a number that is wrong is a measurement while an anchor nobody read is not.
        """
        fuente = "export const A = 1;\nconst B = 2;\n"
        parcial = comparar(fuente, {"A": 1.0})
        self.assertEqual(parcial["rc"], RC_OK)
        exigido = comparar(fuente, {"A": 1.0}, exigir_cobertura_total=True)
        self.assertEqual(exigido["rc"], RC_NO_MEDIDO)
        self.assertEqual(exigido["causa"], "COBERTURA_INCOMPLETA")
        self.assertIn("B", exigido["detalle"])
        self.assertTrue(exigido["cobertura"]["exigida"])
        cubierto = comparar(fuente, {"A": 1.0, "B": 2.0}, exigir_cobertura_total=True)
        self.assertEqual(cubierto["rc"], RC_OK)
        deriva = comparar(fuente, {"A": 2.0}, exigir_cobertura_total=True)
        self.assertEqual(deriva["rc"], RC_DIVERGE)


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

    def test_los_backends_que_el_readme_publica_son_los_que_el_cli_acepta(self):
        """The input table is the only place a YAML caller learns the spelling.

        `action.yml` forwards `backend` verbatim, and the table printed `static` for a reader
        that accepts `estatico`: the first adopter would have got `20`, an answer about their
        own call. A value published and refused is a defect on the front door, and prose cannot
        catch it — this does.
        """
        import contextlib
        import io
        fila = next(linea for linea in (RAIZ / "README.md").read_text().splitlines()
                    if linea.startswith("| `backend`"))
        publicados = re.findall(r"`([^`]+)`", fila.split("|")[4].split("—")[0])
        self.assertEqual(publicados, ["auto", "node", "estatico"])
        for backend in publicados:
            argv = ["--fuente", str(RAIZ / "fixtures" / "engine.ts"),
                    "--referencia", str(RAIZ / "fixtures" / "anchors.json"),
                    "--backend", backend]
            try:
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    rc = main(argv)
            except SystemExit as salida:  # `ParserDeContrato` exits 20 on a bad invocation
                rc = salida.code
            self.assertNotEqual(rc, RC_ARITY, f"el CLI rechaza el backend publicado: {backend}")


class CaidaNombradaTest(unittest.TestCase):
    """`auto` con un node que existe y no puede cargar la fuente no es un cero del sujeto.

    `enum` es TypeScript corriente y el modo *strip-only* de Node lo rechaza, así que el
    camino por defecto —nadie declara `backend`— contestaba rc 2 sobre un archivo que el
    lector estático mide exacto: el instrumento rechazaba al sujeto por su propio lector.
    """

    def test_auto_cae_al_estatico_y_publica_por_que_node_no_corrio(self):
        with mock.patch.object(live_oracle, "version_de_nodo",
                               return_value=("/usr/bin/node", [])), \
             mock.patch.object(live_oracle, "medir",
                               return_value=({}, "node rc 1: SyntaxError [ERR_UNSUPPORTED_"
                                                 "TYPESCRIPT_SYNTAX]: TypeScript enum is not "
                                                 "supported in strip-only mode")):
            vivos, backend, fallo, aviso = medir_vivos(_FUENTE_CORTA, {"A": 864}, "auto")
        self.assertEqual((vivos, backend, fallo), (None, "estatico", None))
        self.assertIn("enum", aviso)
        self.assertIn("estatico", aviso)

    def test_un_node_pedido_explicitamente_sigue_siendo_un_hueco(self):
        """Quien pide la segunda implementación no recibe la primera sin saberlo."""
        with mock.patch.object(live_oracle, "version_de_nodo",
                               return_value=("/usr/bin/node", [])), \
             mock.patch.object(live_oracle, "medir", return_value=({}, "node rc 1: SyntaxError")):
            vivos, _backend, fallo, aviso = medir_vivos(_FUENTE_CORTA, {"A": 864}, "node")
        self.assertEqual(vivos, None)
        self.assertEqual(fallo[0], "ORACULO_VIVO_FALLO")
        self.assertIsNone(aviso)


if __name__ == "__main__":
    unittest.main()


class TextoEsUnValorTest(unittest.TestCase):
    """A string in a real source is a value, not a hole in the reader.

    Measured before this reader learned strings: 13 of 72 declarations in three production
    files (posthog `frontend/src/lib/constants.tsx`, marimo, langfuse) were evaluable —18,1 %—
    and 31 of the 59 silences were strings. The denominator was the reader's, not the
    language's, so the fix is here and the number moves to 56 of 72 (77,8 %).
    """

    def test_una_cadena_con_llaves_no_desalinea_la_profundidad(self):
        """`"cero}"` used to close a brace level and swallow the next declaration.

        `_cerrar_cadena` returned the index of the opening quote, so only that one character
        was masked: the body of every string was read as code. A `}` inside a string closed a
        level that was never opened, and the declarations after it were reported as absent.
        """
        anclas = extraer_anclas("""
            export const MENSAJE = "cero}";
            export const DESPUES = 864;
            export const URL = "https://ejemplo.mx/a";
            export const OTRO = 1080;
        """)
        self.assertEqual(sorted(anclas), ["DESPUES", "MENSAJE", "OTRO", "URL"])
        self.assertEqual(anclas["MENSAJE"]["cuerpo"], '"cero}"')
        self.assertEqual(anclas["OTRO"]["cuerpo"], "1080")

    def test_un_literal_de_regex_con_comilla_no_se_traga_el_resto_del_archivo(self):
        """`/[\\w'()]/gi` opened a string on its `'` and ate 27 declarations of posthog.

        Excluding `<` from the "a regex can start here" set is deliberate: `</div>` in JSX is
        not a division, and a heuristic that guesses wrong costs a character, not a file.
        """
        anclas = extraer_anclas("""
            export const LIMPIO = "x y".replace(/[\\w'()]/gi, "");
            export const DESPUES = 480;
        """)
        self.assertEqual(sorted(anclas), ["DESPUES", "LIMPIO"])
        self.assertEqual(anclas["DESPUES"]["cuerpo"], "480")

    def test_un_comentario_dentro_de_una_cadena_no_abre_comentario(self):
        """`_mascara` blanks comments and strings alike, so the census needs its own pass."""
        anclas = extraer_anclas("""
            export const RUTA = "a//b";
            export const N = 2;
        """)
        self.assertEqual(sorted(anclas), ["N", "RUTA"])

    def test_el_separador_numerico_se_lee_y_la_plantilla_es_un_hueco_nombrado(self):
        anclas = extraer_anclas("""
            export const MILLON = 1_000_000;
            export const PLANTILLA = `${MILLON}px`;
        """)
        self.assertEqual(sorted(anclas), ["MILLON", "PLANTILLA"])
        self.assertEqual(evaluar(anclas, "MILLON"), 1000000.0)

    def test_un_objeto_con_claves_de_texto_y_shorthand_se_resuelve(self):
        anclas = extraer_anclas("""
            export const ANCHO = 1080;
            export const CAJA = { "ancho-max": 1725, ANCHO, "alto": 1920 };
        """)
        self.assertEqual(evaluar(anclas, "CAJA.ancho-max"), 1725.0)
        self.assertEqual(evaluar(anclas, "CAJA.ANCHO"), 1080.0)
        self.assertEqual(evaluar(anclas, "CAJA.alto"), 1920.0)

    def test_un_shorthand_sin_declaracion_es_ilegible_y_no_un_cero(self):
        anclas = extraer_anclas("export const CAJA = { FANTASMA };\n")
        self.assertIn("CAJA", anclas)
        with self.assertRaises(FuenteIlegible):
            evaluar(anclas, "CAJA")

    def test_el_texto_se_compara_por_igualdad_y_la_tolerancia_no_aplica(self):
        """A tolerance answers "how far", and two strings have no distance between them."""
        recibo = comparar('export const EVENTO = "$a";\n', {"EVENTO": "$a"}, tolerancia=1e9)
        self.assertEqual(recibo["rc"], RC_OK)
        fila = recibo["anclas"][0]
        self.assertEqual(fila["tipo_valor"], "texto")
        self.assertNotIn("peor_rel", fila)
        recibo = comparar('export const EVENTO = "$a";\n', {"EVENTO": "$b"}, tolerancia=1e9)
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        fila = recibo["anclas"][0]
        self.assertFalse(fila["ok"])
        self.assertEqual((fila["obtenido"], fila["esperado"]), ("$a", "$b"))
        self.assertNotIn("peor_rel", fila)

    def test_la_aritmetica_sobre_un_texto_es_un_hueco_nombrado(self):
        anclas = extraer_anclas('export const RARO = "a" + "b";\n')
        self.assertIn("RARO", anclas)
        with self.assertRaises(FuenteIlegible):
            evaluar(anclas, "RARO")

    def test_el_censo_publica_el_denominador_y_nombra_cada_silencio(self):
        """`declaradas` has to be readable from the file, not inferred from the reader.

        Before `--censo` the only denominator was `len(anclas)`, so a reader that skipped 27
        declarations reported 100 % of what it had left. The two halves of the silence are
        different questions: `no_leidas` is the reader, `no_evaluables` is the language.
        """
        from ts_py_anchor_guard.anchor_oracle import censo
        fuente = """
            export const A = 864;
            export const Q = Math.max(1, 2);
            export const f = (u) => { return u; };
            export const T = `${A}px`;
        """
        motivos: dict = {}
        anclas = extraer_anclas(fuente, motivos=motivos)
        recuento = censo(anclas, motivos)
        self.assertEqual((recuento["declaradas"], recuento["leidas"],
                          recuento["evaluables"]), (4, 3, 2))
        self.assertEqual(recuento["cobertura"], 0.75)
        self.assertEqual(list(recuento["no_leidas"]), ["f"])  # a block body, never guessed
        self.assertEqual(list(recuento["no_evaluables"]), ["T"])  # a template, out of subset

    def test_la_cli_publica_el_censo_y_su_denominador(self):
        """A coverage figure with no denominator printed is a number about the reader."""
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as caja:
            fuente = pathlib.Path(caja) / "censo.ts"
            fuente.write_text('export const A = 864;\n'
                              'export const f = (u) => { return u; };\n')
            with contextlib.redirect_stdout(io.StringIO()) as salida, \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--fuente", str(fuente), "--censo"])
        self.assertEqual(rc, RC_OK)
        texto = salida.getvalue()
        self.assertIn("CENSO · 2 declarada(s) · 1 leida(s) (50.0%)", texto)
        self.assertIn("NO_LEIDA f ·", texto)


class EntornoTest(unittest.TestCase):
    """The third population: an anchor whose value is decided outside the source.

    Measured on `calcom/cal.com@ae027bb7` `packages/lib/constants.ts`: of 80 refusals, 60
    name the environment. Filing them with the reader's own gaps made the census look like
    a parser problem, and no amount of parser work moves that number.
    """

    def _censo(self, fuente: str):
        from ts_py_anchor_guard.anchor_oracle import censo
        motivos: dict = {}
        anclas = extraer_anclas(fuente, motivos=motivos)
        return censo(anclas, motivos)

    def test_un_ancla_que_lee_el_entorno_se_nombra_con_su_variable(self):
        recuento = self._censo('export const U = process.env.WEBAPP_URL ?? "https://x";\n')
        self.assertEqual(recuento["evaluables"], 0)
        self.assertEqual(recuento["con_entorno"], {"U": ["WEBAPP_URL"]})
        self.assertEqual(recuento["estructurales"], 0)
        self.assertIn("U", recuento["no_evaluables"])  # still refused, never guessed

    def test_las_dos_formas_de_leer_el_entorno_cuentan(self):
        recuento = self._censo('export const A = process.env["CLAVE"];\n'
                              'export const B = import.meta.env.DEV;\n')
        self.assertEqual(recuento["con_entorno"],
                         {"A": ["CLAVE"], "B": ["DEV"]})

    def test_el_texto_que_nombra_el_entorno_no_lo_lee(self):
        """A string spelling the variable is a value, not a dependency."""
        recuento = self._censo('export const M = "process.env.X" + 1;\n')
        self.assertEqual(recuento["con_entorno"], {})
        self.assertEqual(recuento["estructurales"], 1)

    def test_las_tres_partes_suman_el_denominador(self):
        recuento = self._censo('export const A = 864;\n'
                              'export const U = process.env.X || "y";\n'
                              'export const f = (u) => { return u; };\n')
        self.assertEqual(recuento["declaradas"], 3)
        self.assertEqual(recuento["evaluables"] + len(recuento["con_entorno"])
                         + recuento["estructurales"] + len(recuento["no_leidas"]), 3)

    def test_la_cli_publica_la_parte_del_entorno_en_el_resumen(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as caja:
            fuente = pathlib.Path(caja) / "ent.ts"
            fuente.write_text('export const A = 864;\n'
                              'export const U = process.env.X || "y";\n')
            with contextlib.redirect_stdout(io.StringIO()) as salida, \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--fuente", str(fuente), "--censo"])
        self.assertEqual(rc, RC_OK)
        self.assertIn("1 evaluable(s) · 1 con entorno · 0 por estructura", salida.getvalue())


class TaxonomiaTest(unittest.TestCase):
    """Every structural refusal names the construct that stopped the reader.

    Measured on the 25 structural refusals of `calcom/cal.com@ae027bb7` (20),
    `immich-app/immich@a51a4385` (4) and `fixtures/engine.ts` (1): 9 are template literals,
    4 boolean operators, 3 arrow functions, 2 comparisons, 2 member accesses, 2 regex
    literals, 1 type assertion, 1 reserved word and 1 constant that inherits the refusal of
    the constant it reads. The guess -- `.length`, calls, `satisfies`, `=>` -- named 1 of 20.
    """

    def _censo(self, fuente: str):
        from ts_py_anchor_guard.anchor_oracle import censo
        motivos: dict = {}
        anclas = extraer_anclas(fuente, motivos=motivos)
        return censo(anclas, motivos)

    def test_la_plantilla_se_nombra_y_el_motivo_no_cambia(self):
        """Naming a cause adds a name, it does not rewrite the message a consumer parses."""
        recuento = self._censo('export const T = `${A}px`;\n')
        self.assertEqual(recuento["por_causa"], {"PLANTILLA_LITERAL": 1})
        self.assertIn("no se puede tokenizar", recuento["no_evaluables"]["T"])

    def test_el_simbolo_mas_largo_gana(self):
        """`!==` is a comparison; only the leftover `!` is a boolean operator."""
        recuento = self._censo('export const A = B === "x";\n'
                              'export const C = D !== 1;\n'
                              'export const E = F || 2;\n'
                              'export const G = H!;\n')
        self.assertEqual(recuento["causa_de"],
                         {"A": "COMPARACION", "C": "COMPARACION",
                          "E": "OPERADOR_BOOLEANO", "G": "OPERADOR_BOOLEANO"})

    def test_el_miembro_opcional_no_es_un_ternario(self):
        """`?` is a token, so the tokenizer never sees it here: `?.` is a member access."""
        recuento = self._censo('export const M = globalThis.window?.x;\n')
        self.assertEqual(recuento["causa_de"], {"M": "MIEMBRO"})

    def test_el_literal_de_regex_se_nombra_aunque_falle_dentro(self):
        """The mask says where the literal opens, so the cause is the literal and not its `/`."""
        recuento = self._censo(r"export const R = /^[a-z]+:\/\//;" + "\n")
        self.assertEqual(recuento["por_causa"], {"REGEX_LITERAL": 1})

    def test_el_nombre_reservado_y_la_asercion_se_nombran(self):
        recuento = self._censo('export const N = new Set([1]);\n'
                              'export const O = {a: {b: 1} satisfies T, c: 2};\n')
        self.assertEqual(recuento["causa_de"],
                         {"N": "PALABRA_RESERVADA", "O": "ASERCION_TIPO"})

    def test_el_ancla_que_hereda_nombra_el_ancla_culpable(self):
        """`A = B` fails at a position inside `B`; without the prefix the cause lies about `A`."""
        recuento = self._censo('export const A = B;\nexport const B = C || 1;\n')
        self.assertEqual(recuento["causa_de"]["B"], "OPERADOR_BOOLEANO")
        self.assertEqual(recuento["causa_de"]["A"], "BLOQUEADA_POR_ANCLA")
        self.assertTrue(recuento["no_evaluables"]["A"].startswith("B: "))

    def test_el_reparto_cubre_la_poblacion_estructural(self):
        """A bucket that swallows what it cannot name is the defect this act removes."""
        recuento = self._censo('export const T = `${A}px`;\n'
                              'export const R = "a" + 1;\n'
                              'export const U = process.env.X || "y";\n')
        self.assertEqual(sum(recuento["por_causa"].values()), recuento["estructurales"])
        self.assertEqual(sum(recuento["por_causa"].values())
                         + len(recuento["con_entorno"]), len(recuento["no_evaluables"]))
        self.assertNotIn("SIMBOLO_NO_NOMBRADO", recuento["por_causa"])
        self.assertEqual(recuento["causa_de"]["R"], "REGLA_DEL_EVALUADOR")

    def test_la_cli_nombra_la_causa_de_cada_rechazo(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as caja:
            fuente = pathlib.Path(caja) / "tax.ts"
            fuente.write_text('export const T = `${A}px`;\n'
                              'export const U = process.env.X || "y";\n')
            with contextlib.redirect_stdout(io.StringIO()) as salida, \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--fuente", str(fuente), "--censo"])
        self.assertEqual(rc, RC_OK)
        texto = salida.getvalue()
        self.assertIn("NO_EVALUABLE T · PLANTILLA_LITERAL · ", texto)
        self.assertIn("NO_EVALUABLE U · EN_ENTORNO · ", texto)
        self.assertIn("1 por estructura (PLANTILLA_LITERAL 1)", texto)


class EntornoDeclaradoTest(unittest.TestCase):
    """A read of `process.env.X` is a function of a deployment, and the map is its argument.

    Measured on `calcom/cal.com@ae027bb7`: without a map 38 of 118 anchors are priced and 60
    depend on the environment. Declaring the 63 variables the file reads moves exactly 10 of
    them -- 38 + 10 = 48 -- because the other 50 are stopped by a construct the map does not
    reach: 31 boolean operators, 8 comparisons, 4 templates, 3 member accesses, 1 arrow, and
    3 that have a second blocker behind the read (`as string`, `parseInt`, a ternary). The
    prediction said 51; that arithmetic read `causa_de`, which publishes the head of a chain
    and not the chain.
    """

    def _censo(self, fuente: str, entorno=None):
        from ts_py_anchor_guard.anchor_oracle import censo
        motivos: dict = {}
        anclas = extraer_anclas(fuente, motivos=motivos)
        return censo(anclas, motivos, entorno=entorno)

    def test_una_lectura_desnuda_es_un_valor_cuando_el_mapa_la_declara(self):
        recuento = self._censo('export const A = process.env.PORT;\n'
                              'export const B = process.env.OTRA;\n',
                              entorno={"PORT": "3000"})
        self.assertEqual(recuento["evaluables"], 1)
        self.assertEqual(recuento["con_entorno"], {"B": ["OTRA"]})
        self.assertEqual(recuento["causa_de"]["B"], "VARIABLE_NO_DECLARADA")
        self.assertIn("variable de entorno no declarada: OTRA", recuento["no_evaluables"]["B"])

    def test_el_reparto_de_tres_poblaciones_cierra_con_mapa(self):
        """Adding a map moves anchors between populations; it never invents or loses one."""
        fuente = ('export const A = 1;\n'
                  'export const B = process.env.PORT;\n'
                  'export const C = process.env.FALTA;\n'
                  'export const D = `${B}px`;\n')
        sin = self._censo(fuente)
        con = self._censo(fuente, entorno={"PORT": "3000"})
        self.assertEqual(sin["evaluables"], con["evaluables"] - 1)
        self.assertEqual(sin["estructurales"], con["estructurales"])
        for recuento in (sin, con):
            self.assertEqual(sum(recuento["por_causa"].values())
                             + len(recuento["con_entorno"]), len(recuento["no_evaluables"]))
        self.assertEqual(con["con_entorno"], {"C": ["FALTA"]})
        self.assertEqual(con["causa_de"]["D"], "PLANTILLA_LITERAL")

    def test_una_variable_ausente_nunca_toma_el_valor_por_defecto(self):
        """`X || "d"` is refused at the operator, before the read: the map cannot reach it.

        The map closes the environment; the fallback would need the operator act, and until
        then the anchor stays a hole. What this pins is that it never becomes `"d"`.
        """
        recuento = self._censo('export const A = process.env.FALTA || "d";\n',
                              entorno={"OTRA": "si"})
        self.assertEqual(recuento["evaluables"], 0)
        self.assertIn("A", recuento["con_entorno"])
        self.assertEqual(recuento["causa_de"]["A"], "OPERADOR_BOOLEANO")
        with self.assertRaises(FuenteIlegible):
            evaluar(extraer_anclas('export const A = process.env.FALTA || "d";\n'),
                    "A", entorno={"OTRA": "si"})

    def test_el_mapa_no_resucita_lo_que_el_operador_detiene(self):
        """The map closes the environment; what stands behind it is the next act's business."""
        recuento = self._censo('export const A = process.env.PORT || "80";\n'
                              'export const B = process.env.PORT ?? "80";\n',
                              entorno={"PORT": "3000"})
        self.assertEqual(recuento["causa_de"]["A"], "OPERADOR_BOOLEANO")
        self.assertEqual(recuento["evaluables"], 1)
        self.assertNotIn("B", recuento["no_evaluables"])
        self.assertNotIn("B", recuento["con_entorno"])

    def test_la_forma_corchete_y_la_forma_punto_son_la_misma_lectura(self):
        recuento = self._censo('export const A = process.env["PORT"];\n'
                              'export const B = process.env.PORT;\n'
                              'export const C = import.meta.env["PORT"];\n',
                              entorno={"PORT": "3000"})
        self.assertEqual(recuento["evaluables"], 3)
        sin_mapa = self._censo('export const A = process.env["PORT"];\n')
        self.assertEqual(sin_mapa["con_entorno"], {"A": ["PORT"]})
        self.assertEqual(sin_mapa["causa_de"]["A"], "VARIABLE_NO_DECLARADA")

    def test_un_texto_que_nombra_una_variable_no_es_una_lectura(self):
        """The literal is a value; only the syntax outside a string asks the deployment."""
        recuento = self._censo('export const A = "process.env.PORT";\n')
        self.assertEqual(recuento["evaluables"], 1)
        self.assertEqual(recuento["con_entorno"], {})

    def test_el_mapa_se_publica_porque_otro_mapa_es_otro_censo(self):
        recuento = self._censo('export const A = process.env.PORT;\n',
                              entorno={"PORT": "3000", "OTRA": "x"})
        self.assertEqual(recuento["entorno"], {"OTRA": "x", "PORT": "3000"})
        vacio = self._censo('export const A = 1;\n')
        self.assertEqual(vacio["entorno"], {})

    def test_un_mapa_ilegible_es_no_medido_y_jamas_un_mapa_vacio(self):
        from ts_py_anchor_guard.anchor_oracle import _mapa_declarado
        self.assertEqual(_mapa_declarado("{", "m.json")[0], None)
        self.assertEqual(_mapa_declarado("[1]", "m.json")[1][0], "MAPA_ENTORNO_ILEGIBLE")
        mapa, fallo = _mapa_declarado('{"PORT": 3000}', "m.json")
        self.assertIsNone(mapa)
        self.assertEqual(fallo[0], "MAPA_ENTORNO_ILEGIBLE")
        self.assertIn("PORT", fallo[1])
        self.assertEqual(_mapa_declarado('{"PORT": "3000"}', "m.json")[0], {"PORT": "3000"})

    def test_la_cli_carga_el_mapa_y_lo_publica(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as caja:
            fuente = pathlib.Path(caja) / "env.ts"
            fuente.write_text('export const A = process.env.PORT;\n'
                              'export const B = process.env.FALTA;\n')
            mapa = pathlib.Path(caja) / "env.json"
            mapa.write_text('{"PORT": "3000"}')
            with contextlib.redirect_stdout(io.StringIO()) as salida, \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--fuente", str(fuente), "--censo", "--entorno", str(mapa)])
            self.assertEqual(rc, RC_OK)
            texto = salida.getvalue()
            self.assertIn("CENSO · 1 variable(s) declarada(s) · 2 declarada(s) · ", texto)
            mapa.write_text('{"PORT": 3000}')
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                rc = main(["--fuente", str(fuente), "--censo", "--entorno", str(mapa)])
            self.assertEqual(rc, RC_NO_MEDIDO)
            self.assertIn("MAPA_ENTORNO_ILEGIBLE", error.getvalue())
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                rc = main(["--fuente", str(fuente), "--censo",
                           "--entorno", str(pathlib.Path(caja) / "no-existe.json")])
            self.assertEqual(rc, RC_NO_MEDIDO)
            self.assertIn("INSUMO_FALTA", error.getvalue())

    def test_el_manifiesto_no_traga_el_mapa_en_silencio(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as caja:
            mapa = pathlib.Path(caja) / "env.json"
            mapa.write_text('{"PORT": "3000"}')
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                rc = main(["--manifest", str(pathlib.Path(caja) / "m.json"),
                           "--entorno", str(mapa)])
        self.assertEqual(rc, RC_ARITY)
        self.assertIn("todavia no viaja en el manifiesto", error.getvalue())
