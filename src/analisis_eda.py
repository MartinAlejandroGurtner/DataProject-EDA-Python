"""Proyecto EDA - Marketing bancario (ThePowerMBA).

Ejecución desde la raíz del proyecto:
    python src/analisis_eda.py

El script lee los archivos originales, limpia y combina las tablas,
calcula estadísticas, construye gráficos y guarda los resultados.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Genera imágenes PNG incluso sin una ventana gráfica abierta.
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


RAIZ = Path(__file__).resolve().parents[1]
ORIGINALES = RAIZ / "datos" / "originales"
PROCESADOS = RAIZ / "datos" / "procesados"
TABLAS = RAIZ / "tablas"
GRAFICOS = RAIZ / "graficos"

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}
COLORES = {"principal": "#22577A", "positivo": "#159895", "fondo": "#F2F5F7"}


def normalizar_fecha_es(serie: pd.Series) -> pd.Series:
    """Convierte fechas como '2-agosto-2019' a datetime; respeta valores ausentes."""
    texto = serie.astype("string").str.strip().str.lower()
    for nombre_mes, numero in MESES.items():
        texto = texto.str.replace(f"-{nombre_mes}-", f"-{numero}-", regex=False)
    return pd.to_datetime(texto, format="%d-%m-%Y", errors="coerce")


def convertir_decimal_es(serie: pd.Series) -> pd.Series:
    """Convierte textos con coma decimal (por ejemplo '4,857') a números."""
    return pd.to_numeric(
        serie.astype("string").str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )


def limpiar_campanas(raw: pd.DataFrame) -> pd.DataFrame:
    datos = raw.drop(columns=["Unnamed: 0"], errors="ignore").copy()
    datos = datos.rename(columns={
        "id_": "id", "y": "suscripcion", "date": "fecha_contacto_original",
        "emp.var.rate": "variacion_empleo", "cons.price.idx": "indice_precios",
        "cons.conf.idx": "confianza_consumidor", "euribor3m": "euribor_3m",
        "nr.employed": "empleados_economia",
    })

    # No imputamos las edades ni las variables macro: una imputación artificial
    # cambiaría las medias y podría distorsionar el análisis.
    datos["edad"] = pd.to_numeric(datos.pop("age"), errors="coerce").astype("Int64")
    for columna in ["default", "housing", "loan"]:
        datos[columna] = pd.to_numeric(datos[columna], errors="coerce").astype("Int64")
    for columna in ["indice_precios", "confianza_consumidor", "euribor_3m", "empleados_economia"]:
        datos[columna] = convertir_decimal_es(datos[columna])

    categorias = ["job", "marital", "education", "contact", "poutcome", "suscripcion"]
    for columna in categorias:
        datos[columna] = datos[columna].astype("string").str.strip().str.lower()
        datos[columna] = datos[columna].replace("unknown", "desconocido")

    # Los valores ausentes de categorías permanecen explícitos, sin asumir
    # que equivalen a la categoría más habitual.
    for columna in ["job", "marital", "education", "contact", "poutcome"]:
        datos[columna] = datos[columna].fillna("sin_dato")

    if not datos["suscripcion"].isin(["yes", "no"]).all():
        raise ValueError("Se han encontrado valores inesperados en 'y'.")
    datos["suscribio"] = (datos["suscripcion"] == "yes").astype(int)

    datos["fecha_contacto"] = normalizar_fecha_es(datos["fecha_contacto_original"])
    datos["anio_contacto"] = datos["fecha_contacto"].dt.year.astype("Int64")
    datos["mes_contacto"] = datos["fecha_contacto"].dt.month.astype("Int64")

    # 999 actúa como código especial para pdays, no como 999 días reales.
    datos["dias_contacto_previo"] = datos["pdays"].replace(999, np.nan)
    datos["sin_fecha_contacto_previo"] = datos["pdays"].eq(999)
    datos["grupo_contactos"] = pd.cut(
        datos["campaign"], bins=[0, 1, 2, 3, 5, np.inf],
        labels=["1", "2", "3", "4-5", "6 o más"],
    )
    datos["grupo_edad"] = pd.cut(
        datos["edad"], bins=[0, 24, 34, 44, 54, 64, np.inf],
        labels=["Hasta 24", "25-34", "35-44", "45-54", "55-64", "65 o más"],
    ).cat.add_categories(["Sin dato"]).fillna("Sin dato")
    datos["id"] = datos["id"].astype("string").str.strip().str.lower()

    if datos["id"].isna().any() or datos["id"].duplicated().any():
        raise ValueError("El identificador del CSV falta o está duplicado.")
    return datos


def limpiar_clientes(hojas: dict[str, pd.DataFrame]) -> pd.DataFrame:
    partes = []
    for nombre, tabla in hojas.items():
        bloque = tabla.drop(columns=["Unnamed: 0"], errors="ignore").copy()
        bloque["hoja_origen"] = nombre
        partes.append(bloque)
    clientes = pd.concat(partes, ignore_index=True)
    clientes = clientes.rename(columns={
        "ID": "id", "Income": "ingresos_anuales", "Kidhome": "ninos_hogar",
        "Teenhome": "adolescentes_hogar", "Dt_Customer": "fecha_alta_cliente",
        "NumWebVisitsMonth": "visitas_web_mes",
    })
    clientes["id"] = clientes["id"].astype("string").str.strip().str.lower()
    clientes["fecha_alta_cliente"] = pd.to_datetime(clientes["fecha_alta_cliente"], errors="coerce")
    for col in ["ingresos_anuales", "ninos_hogar", "adolescentes_hogar", "visitas_web_mes"]:
        clientes[col] = pd.to_numeric(clientes[col], errors="coerce")
    if clientes["id"].isna().any() or clientes["id"].duplicated().any():
        raise ValueError("El Excel contiene IDs duplicados o vacíos; revisar antes de cruzar.")
    return clientes


def combinar_y_validar(campanas: pd.DataFrame, clientes: pd.DataFrame) -> pd.DataFrame:
    # Unión LEFT: conserva TODAS las campañas incluso si faltara un cliente.
    resultado = campanas.merge(clientes, how="left", on="id", validate="one_to_one", indicator=True)
    sin_ficha = int(resultado["_merge"].eq("left_only").sum())
    if sin_ficha:
        raise ValueError(f"Hay {sin_ficha} campañas sin ficha de cliente asociada.")
    return resultado.drop(columns="_merge")


def porcentaje_conversion(df: pd.DataFrame, variable: str) -> pd.DataFrame:
    tabla = df.groupby(variable, dropna=False, observed=True)["suscribio"].agg(
        clientes="size", suscripciones="sum", tasa_conversion="mean",
    ).reset_index()
    tabla["tasa_conversion"] *= 100
    return tabla


def guardar_tabla(df: pd.DataFrame, nombre: str) -> None:
    df.to_csv(TABLAS / nombre, index=False, float_format="%.4f")


def guardar_figura(nombre: str) -> None:
    plt.savefig(GRAFICOS / nombre, dpi=165, bbox_inches="tight", facecolor="white")
    plt.close()


def grafico_barras(tabla: pd.DataFrame, variable: str, titulo: str, archivo: str,
                   ordenar: bool = False) -> None:
    datos = tabla.copy()
    if ordenar:
        datos = datos.sort_values("tasa_conversion", ascending=True)
    fig, ax = plt.subplots(figsize=(9, max(4.4, len(datos) * 0.55)))
    # pandas puede conservar los valores ausentes como NaN incluso al convertir
    # una columna a texto. Matplotlib necesita etiquetas str reales en el eje Y.
    etiquetas = ["Sin dato" if pd.isna(valor) else str(valor) for valor in datos[variable].tolist()]
    tasas = datos["tasa_conversion"].astype(float).tolist()
    ax.barh(etiquetas, tasas, color=COLORES["principal"])
    ax.set_title(titulo, fontsize=13, weight="bold", loc="left", pad=15)
    ax.set_xlabel("Tasa de suscripción (%)")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(1, datos["tasa_conversion"].max() * 1.24))
    for i, (_, fila) in enumerate(datos.iterrows()):
        ax.text(fila["tasa_conversion"] + .25, i,
                f"{fila['tasa_conversion']:.1f}% (n={int(fila['clientes']):,})".replace(",", "."),
                va="center", fontsize=9)
    fig.tight_layout()
    guardar_figura(archivo)


def grafico_faltantes(raw: pd.DataFrame) -> pd.DataFrame:
    falta = raw.isna().sum().sort_values(ascending=False)
    tabla = pd.DataFrame({"variable": falta.index, "faltantes": falta.values})
    tabla["porcentaje"] = tabla["faltantes"] / len(raw) * 100
    guardar_tabla(tabla, "faltantes_csv_original.csv")
    datos = tabla[tabla["faltantes"] > 0].sort_values("porcentaje")
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.barh(datos["variable"], datos["porcentaje"], color=COLORES["principal"])
    ax.set_title("Valores ausentes en el CSV original", loc="left", fontsize=13, weight="bold")
    ax.set_xlabel("Porcentaje de registros (%)")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    fig.tight_layout()
    guardar_figura("01_valores_ausentes.png")
    return tabla


def grafico_correlaciones(df: pd.DataFrame) -> None:
    columnas = ["edad", "ingresos_anuales", "duration", "campaign", "previous",
                "euribor_3m", "indice_precios", "confianza_consumidor",
                "visitas_web_mes", "suscribio"]
    correlaciones = df[columnas].corr(numeric_only=True)
    guardar_tabla(correlaciones.reset_index().rename(columns={"index": "variable"}), "correlaciones.csv")
    fig, ax = plt.subplots(figsize=(10, 8))
    imagen = ax.imshow(correlaciones, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(columnas)), columnas, rotation=50, ha="right")
    ax.set_yticks(range(len(columnas)), columnas)
    ax.set_title("Correlaciones (exploratorias, no causales)", loc="left", fontsize=13, weight="bold", pad=15)
    fig.colorbar(imagen, ax=ax, fraction=.045, pad=.035, label="Coeficiente de Pearson")
    fig.tight_layout()
    guardar_figura("09_correlaciones.png")


def analizar(campanas_raw: pd.DataFrame, campanas: pd.DataFrame,
             clientes: pd.DataFrame, unidos: pd.DataFrame) -> dict:
    grafico_faltantes(campanas_raw)
    variables = [
        ("contact", "02_conversion_canal.png", "Conversión por canal de contacto", False),
        ("grupo_contactos", "03_conversion_contactos.png", "Conversión según número de contactos", False),
        ("grupo_edad", "04_conversion_edad.png", "Conversión por tramo de edad", False),
        ("poutcome", "06_conversion_campana_anterior.png", "Conversión según resultado anterior", False),
        ("anio_contacto", "07_conversion_anio.png", "Conversión por año de contacto (fechas disponibles)", False),
        ("job", "08_conversion_profesion.png", "Conversión por ocupación", True),
    ]
    for variable, png, titulo, orden in variables:
        tabla = porcentaje_conversion(unidos, variable)
        guardar_tabla(tabla, f"conversion_{variable}.csv")
        grafico_barras(tabla, variable, titulo, png, ordenar=orden)

    # Los cuartiles se definen únicamente a partir de los ingresos disponibles.
    unidos["cuartil_ingresos"] = pd.qcut(
        unidos["ingresos_anuales"], q=4,
        labels=["Q1: menores", "Q2", "Q3", "Q4: mayores"], duplicates="drop",
    )
    tabla_renta = porcentaje_conversion(unidos, "cuartil_ingresos")
    guardar_tabla(tabla_renta, "conversion_cuartil_ingresos.csv")
    grafico_barras(tabla_renta, "cuartil_ingresos", "Conversión por cuartil de ingresos", "05_conversion_ingresos.png")

    resumen_stats = unidos[["edad", "ingresos_anuales", "duration", "campaign", "previous",
                           "euribor_3m", "visitas_web_mes"]].describe().T
    guardar_tabla(resumen_stats.reset_index().rename(columns={"index": "variable"}), "estadisticos_descriptivos.csv")
    grafico_correlaciones(unidos)

    # Seguimiento de calidad: 170 fichas de Excel no se utilizan en el LEFT JOIN.
    extras = int((~clientes["id"].isin(campanas["id"])).sum())
    n = len(unidos)
    metricas = {
        "campanas": n,
        "fichas_excel": len(clientes),
        "fichas_sin_campana": extras,
        "clientes_sin_ficha": int(unidos["ingresos_anuales"].isna().sum()),
        "suscripciones": int(unidos["suscribio"].sum()),
        "sin_suscripcion": int((unidos["suscribio"] == 0).sum()),
        "conversion_pct": round(100 * unidos["suscribio"].mean(), 2),
        "registros_sin_edad": int(unidos["edad"].isna().sum()),
        "registros_sin_euribor": int(unidos["euribor_3m"].isna().sum()),
        "registros_sin_fecha": int(unidos["fecha_contacto"].isna().sum()),
        "registros_pdays_999": int(unidos["sin_fecha_contacto_previo"].sum()),
        "conversion_por_canal": (
            porcentaje_conversion(unidos, "contact").set_index("contact")["tasa_conversion"].round(2).to_dict()
        ),
        "conversion_segun_contactos": (
            porcentaje_conversion(unidos, "grupo_contactos").set_index("grupo_contactos")["tasa_conversion"].round(2).to_dict()
        ),
        "conversion_segun_antecedente": (
            porcentaje_conversion(unidos, "poutcome").set_index("poutcome")["tasa_conversion"].round(2).to_dict()
        ),
    }
    (TABLAS / "resumen_metricas.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8")
    return metricas


def main() -> None:
    for carpeta in [PROCESADOS, TABLAS, GRAFICOS]:
        carpeta.mkdir(parents=True, exist_ok=True)

    csv = ORIGINALES / "bank-additional.csv"
    excel = ORIGINALES / "customer-details.xlsx"
    if not csv.exists() or not excel.exists():
        raise FileNotFoundError("Faltan los archivos originales en datos/originales/.")

    campanas_raw = pd.read_csv(csv, low_memory=False)
    hojas = pd.read_excel(excel, sheet_name=None, engine="openpyxl")
    campanas = limpiar_campanas(campanas_raw)
    clientes = limpiar_clientes(hojas)
    unidos = combinar_y_validar(campanas, clientes)

    metricas = analizar(campanas_raw, campanas, clientes, unidos)
    campanas.to_csv(PROCESADOS / "campanas_limpias.csv", index=False)
    clientes.to_csv(PROCESADOS / "clientes_limpios.csv", index=False)
    unidos.to_csv(PROCESADOS / "datos_integrados.csv", index=False)

    print("\nPROYECTO EDA - RESULTADOS VERIFICADOS")
    print(f"Campañas: {metricas['campanas']:,}")
    print(f"Suscripciones: {metricas['suscripciones']:,}")
    print(f"Conversión: {metricas['conversion_pct']:.2f}%")
    print(f"Fichas del Excel sin campaña: {metricas['fichas_sin_campana']}")
    print(f"Campañas sin ficha vinculada: {metricas['clientes_sin_ficha']}")
    print("CSV limpios en datos/procesados/, gráficos en graficos/ y estadísticas en tablas/.")


if __name__ == "__main__":
    main()
