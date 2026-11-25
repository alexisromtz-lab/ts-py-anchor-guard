import contextlib
import io
import unittest

from ts_py_anchor_guard.subpixel_probe import (
    RC_ARITY, RC_NO_MEDIDO, RC_OK, RESOLUCION_PX, PerfilInvalido, anisotropia,
    fase_subpixel, main, perfil_sintetico,
)


class FaseTest(unittest.TestCase):
    def test_perfil_identico_mide_cero(self):
        base = perfil_sintetico(400)
        self.assertAlmostEqual(fase_subpixel(base, base)["desplazamiento"], 0.0, places=12)

    def test_recupera_fases_subpixel_por_debajo_de_la_resolucion_declarada(self):
        base = perfil_sintetico(400)
        for fase in (0.02, 0.25, -0.25, 1.6, -3.5):
            medido = fase_subpixel(base, perfil_sintetico(400, fase=fase))
            self.assertLessEqual(abs(medido["desplazamiento"] - fase), RESOLUCION_PX, fase)

    def test_un_compositor_que_redondea_a_pixel_entero_pierde_la_fase(self):
        """0.4 px intended vs the same content snapped: the 0.4 px gap is the defect."""
        base = perfil_sintetico(400)
        deseado = fase_subpixel(base, perfil_sintetico(400, fase=0.4))["desplazamiento"]
        snapped = fase_subpixel(base, perfil_sintetico(400, fase=0.0))["desplazamiento"]
        self.assertLessEqual(abs(deseado - 0.4), RESOLUCION_PX)
        self.assertGreater(abs(snapped - 0.4), RESOLUCION_PX)

    def test_minimo_en_el_borde_es_no_medido_y_no_un_numero(self):
        base = perfil_sintetico(400)
        recibo = fase_subpixel(base, perfil_sintetico(400, fase=6.0), max_shift=4)
        self.assertEqual(recibo["rc"], RC_NO_MEDIDO)
        self.assertEqual(recibo["causa"], "BORDE")

    def test_perfiles_no_relacionados_no_se_declaran_iguales(self):
        base = perfil_sintetico(400)
        ajeno = perfil_sintetico(400, semillas=(0.037, 0.101, 0.229))
        identidad = fase_subpixel(base, base)
        medido = fase_subpixel(base, ajeno)
        self.assertGreater(medido["coste"], identidad["coste"] * 4)

    def test_perfiles_invalidos(self):
        with self.assertRaises(PerfilInvalido):
            fase_subpixel([0.0] * 10, [0.0] * 10)
        with self.assertRaises(PerfilInvalido):
            perfil_sintetico(0)
        with self.assertRaises(PerfilInvalido):
            perfil_sintetico(10, semillas=(0.5, 3.5, 0.2))


class AnisotropiaTest(unittest.TestCase):
    def test_una_escala_0_1_por_ciento_se_mide_en_la_pendiente(self):
        k = 1e-3
        recibo = anisotropia(perfil_sintetico(600), perfil_sintetico(600, escala=1 + k), bandas=6)
        self.assertEqual(recibo["rc"], RC_OK)
        self.assertAlmostEqual(recibo["error_de_escala"], k, delta=0.2 * k)
        self.assertLess(recibo["residuo_max"], 2 * RESOLUCION_PX)

    def test_una_traslacion_pura_no_finge_anisotropia(self):
        recibo = anisotropia(perfil_sintetico(600), perfil_sintetico(600, fase=0.3), bandas=6)
        self.assertEqual(recibo["rc"], RC_OK)
        self.assertLess(abs(recibo["pendiente"]), 1e-3 / 100)  # 100x below the signal

    def test_bandas_insuficientes_o_demasiado_cortas(self):
        with self.assertRaises(PerfilInvalido):
            anisotropia(perfil_sintetico(600), perfil_sintetico(600), bandas=2)
        with self.assertRaises(PerfilInvalido):
            anisotropia(perfil_sintetico(100), perfil_sintetico(100), bandas=6)


class ContratoTest(unittest.TestCase):
    def test_autotest_y_aridad(self):
        self.assertEqual(main(["--self-test"]), RC_OK)
        self.assertEqual(main([]), RC_ARITY)

    def test_cli_mide_dos_perfiles_en_disco(self):
        import pathlib
        import tempfile

        base = perfil_sintetico(200)
        with tempfile.TemporaryDirectory() as tmp:
            a, b = pathlib.Path(tmp, "a.txt"), pathlib.Path(tmp, "b.txt")
            a.write_text("\n".join(f"{v!r}" for v in base))
            b.write_text("\n".join(f"{v!r}" for v in perfil_sintetico(200, fase=0.5)))
            with contextlib.redirect_stdout(io.StringIO()) as salida:
                rc = main(["--a", str(a), "--b", str(b)])
        self.assertEqual(rc, RC_OK)
        self.assertIn("px", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
