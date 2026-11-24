"""Pequeñas comprobaciones del proceso EDA, sin librerías de test externas."""
import sys
from pathlib import Path
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analisis_eda import convertir_decimal_es, normalizar_fecha_es, limpiar_campanas, combinar_y_validar


class TestLimpieza(unittest.TestCase):
    def test_fecha_espanola(self):
        fechas = normalizar_fecha_es(pd.Series(["2-agosto-2019", "14-septiembre-2016", None]))
        self.assertEqual(fechas.iloc[0], pd.Timestamp("2019-08-02"))
        self.assertEqual(fechas.iloc[1], pd.Timestamp("2016-09-14"))
        self.assertTrue(pd.isna(fechas.iloc[2]))

    def test_decimal_con_coma(self):
        salida = convertir_decimal_es(pd.Series(["4,857", "-36,4", None]))
        self.assertAlmostEqual(salida.iloc[0], 4.857)
        self.assertAlmostEqual(salida.iloc[1], -36.4)
        self.assertTrue(pd.isna(salida.iloc[2]))

    def test_uniones_no_duplican_registros(self):
        campanas = pd.DataFrame({"id": ["a", "b"], "suscribio": [1, 0]})
        clientes = pd.DataFrame({"id": ["a", "b", "c"], "ingresos_anuales": [100, 200, 300]})
        final = combinar_y_validar(campanas, clientes)
        self.assertEqual(len(final), 2)
        self.assertEqual(final["ingresos_anuales"].tolist(), [100, 200])

    def test_uniones_rechazan_duplicados(self):
        campanas = pd.DataFrame({"id": ["a", "b"]})
        clientes = pd.DataFrame({"id": ["a", "a", "b"]})
        with self.assertRaises(ValueError):
            combinar_y_validar(campanas, clientes)


if __name__ == "__main__":
    unittest.main()
