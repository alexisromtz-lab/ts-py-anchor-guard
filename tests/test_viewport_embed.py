import contextlib
import io
import unittest

from ts_py_anchor_guard.viewport_embed import (
    RC_ARITY, RC_DIVERGE, RC_OK, VentanaNoCabe, main, rect_de, verificar_1a1,
)


class RectTest(unittest.TestCase):
    def test_la_ventana_1a1_se_centra_sin_estirarse(self):
        self.assertEqual(rect_de((1080, 1920), (864, 960)), (108, 480, 864, 960))

    def test_el_margen_impar_se_redondea_hacia_dentro(self):
        """floor, not round: rounding up leaves the rect half a pixel outside its canvas."""
        self.assertEqual(rect_de((1081, 1921), (864, 960)), (108, 480, 864, 960))
        self.assertEqual(rect_de((1083, 1923), (864, 960)), (109, 481, 864, 960))

    def test_el_rectangulo_nunca_sale_del_lienzo(self):
        for ancho in range(864, 900):
            izquierda, _, w, _ = rect_de((ancho, 1920), (864, 960))
            self.assertGreaterEqual(izquierda, 0)
            self.assertLessEqual(izquierda + w, ancho)

    def test_ventana_mayor_que_el_lienzo_se_rechaza_en_vez_de_recortarse(self):
        with self.assertRaises(VentanaNoCabe):
            rect_de((640, 480), (864, 960))

    def test_lienzo_o_ventana_no_enteros_se_rechazan(self):
        for malo in ((1080.5, 1920), (1080, 1920.0), (True, 1920)):
            with self.assertRaises(ValueError):
                rect_de(malo, (864, 960))
        with self.assertRaises(ValueError):
            rect_de((1080, 1920), (864, 0))


class VerificacionTest(unittest.TestCase):
    def test_encastre_correcto(self):
        recibo = verificar_1a1((1080, 1920), (864, 960))
        self.assertEqual(recibo["rc"], RC_OK)
        self.assertEqual(recibo["escala"], [1.0, 1.0])
        self.assertEqual(recibo["rect"], [108, 480, 864, 960])

    def test_estirar_la_ventana_al_cuadro_se_nombra_como_escala(self):
        recibo = verificar_1a1((1080, 1920), (864, 960), rect=(0, 0, 1080, 1920))
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        self.assertEqual(recibo["causa"], "ESCALA")
        self.assertEqual(recibo["escala"], [0.8, 0.5])

    def test_un_rectangulo_que_se_sale_se_nombra_como_recorte(self):
        recibo = verificar_1a1((1080, 1920), (864, 960), rect=(250, 480, 864, 960))
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        self.assertEqual(recibo["causa"], "RECORTE")

    def test_ventana_que_no_cabe_se_nombra_como_desborda(self):
        recibo = verificar_1a1((640, 480), (864, 960))
        self.assertEqual(recibo["rc"], RC_DIVERGE)
        self.assertEqual(recibo["causa"], "DESBORDA")


class ContratoTest(unittest.TestCase):
    def test_autotest_y_aridad(self):
        self.assertEqual(main(["--self-test"]), RC_OK)
        self.assertEqual(main([]), RC_ARITY)

    def test_cli_nombra_la_causa(self):
        with contextlib.redirect_stdout(io.StringIO()) as salida:
            rc = main(["--canvas", "1080", "1920", "--ventana", "864", "960",
                       "--rect", "0", "0", "1080", "1920"])
        self.assertEqual(rc, RC_DIVERGE)
        self.assertIn("causa=ESCALA", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
