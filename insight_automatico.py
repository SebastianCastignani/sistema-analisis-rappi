from dotenv import load_dotenv
load_dotenv()

import os
import io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path
from datetime import datetime
import anthropic
import duckdb

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image,
    Table, TableStyle, HRFlowable, PageBreak
)

# ── Configuración ──────────────────────────────────────────────
RUTA_METRICAS  = Path("RAW_INPUT_METRICS.csv")
RUTA_ORDENES   = Path("RAW_ORDERS.csv")
RUTA_SALIDA    = Path("reporte_rappi.pdf")

COLUMNAS_SEMANAS = [
    "L8W_ROLL", "L7W_ROLL", "L6W_ROLL", "L5W_ROLL",
    "L4W_ROLL", "L3W_ROLL", "L2W_ROLL", "L1W_ROLL", "L0W_ROLL"
]

METRICAS_PORCENTAJE = [
    "Lead Penetration", "Perfect Orders", "Pro Adoption (Last Week Status)",
    "% PRO Users Who Breakeven", "Non-Pro PTC > OP", "Turbo Adoption",
    "MLTV Top Verticals Adoption", "Restaurants Markdowns / GMV",
    "% Restaurants Sessions With Optimal Assortment",
    "Restaurants SS > ATC CVR", "Restaurants SST > SS CVR", "Retail SST > SS CVR"
]

METRICAS_BENCHMARKING   = ["Perfect Orders", "Gross Profit UE", "Lead Penetration"]
UMBRAL_ANOMALIA         = 10.0
SEMANAS_TENDENCIA       = 3
UMBRAL_BENCHMARK        = 10.0
UMBRAL_CORRELACION      = 0.5
UMBRAL_VALOR_MINIMO     = 1.0
UMBRAL_CAMBIO_TENDENCIA = 5.0

# Colores Rappi
COLOR_NARANJA = colors.HexColor("#FF441F")
COLOR_GRIS    = colors.HexColor("#F5F5F5")
COLOR_OSCURO  = colors.HexColor("#1A1A1A")

# ── Helpers ────────────────────────────────────────────────────
def conectar():
    """Abre una conexión DuckDB en memoria"""
    return duckdb.connect()

def lista_sql(valores):
    """Convierte lista Python a formato SQL: ('a', 'b', 'c')"""
    return "('" + "', '".join(valores) + "')"


def guardar_figura(fig):
    """Guarda un matplotlib fig en memoria para ReportLab."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer


def crear_tabla(filas, col_widths, font_size=8, align=None, valign="MIDDLE", padding=4):
    tabla = Table(filas, colWidths=col_widths)
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_NARANJA),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOR_GRIS, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), valign),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]
    if align:
        estilos.extend(align)
    tabla.setStyle(TableStyle(estilos))
    return tabla


def limpiar_markdown_basico(texto):
    """Limpia bullets/markdown simples que el LLM puede devolver."""
    import re
    lineas = []
    for parrafo in texto.split("\n"):
        linea = parrafo.strip()
        if not linea or linea in ("---", "***"):
            continue
        linea = re.sub(r"^#{1,3}\s*", "", linea)
        linea = re.sub(r"\*\*(.*?)\*\*", r"\1", linea)
        linea = re.sub(r"\*(.*?)\*", r"\1", linea)
        linea = re.sub(r"^[-■•]\s*", "", linea)
        linea = linea.strip()
        if linea:
            lineas.append(linea)
    return lineas


# ── Carga y limpieza ───────────────────────────────────────────
def cargar_datos():
    """
    Carga el CSV con pandas y normaliza métricas porcentuales.
    Se hace en pandas porque requiere iterar columna por columna
    con condiciones compuestas que en SQL serían muy rebuscado.
    """
    datos = pd.read_csv(RUTA_METRICAS)
    for columna in COLUMNAS_SEMANAS:
        filas_decimal = datos["METRIC"].isin(METRICAS_PORCENTAJE) & (datos[columna] <= 1)
        datos.loc[filas_decimal, columna] = datos.loc[filas_decimal, columna] * 100
        filas_invalidas = datos["METRIC"].isin(METRICAS_PORCENTAJE) & (datos[columna] > 100)
        datos.loc[filas_invalidas, columna] = np.nan
    return datos


# ── Análisis ───────────────────────────────────────────────────
def detectar_anomalias(datos):
    """
    Compara L0W_ROLL vs L1W_ROLL. Si el cambio supera el umbral es una anomalía.
    Usa DuckDB SQL — es un filtro y cálculo directo que se expresa mejor en SQL.
    Gross Profit UE usa diferencia absoluta porque puede ser negativo.
    """
    con = conectar()
    con.register("metricas", datos)

    # Métricas porcentuales — cambio porcentual normal
    deterioros_pct = con.execute(f"""
        SELECT 'Deterioro' AS categoria, METRIC AS metrica,
               ZONE AS zona, COUNTRY AS pais, CITY AS ciudad,
               ROUND(L0W_ROLL, 2) AS valor_actual,
               ROUND(L1W_ROLL, 2) AS valor_anterior,
               ROUND(((L0W_ROLL - L1W_ROLL) / ABS(L1W_ROLL)) * 100, 1) AS cambio
        FROM metricas
        WHERE METRIC IN {lista_sql(METRICAS_PORCENTAJE)}
        AND ABS(L1W_ROLL) > {UMBRAL_VALOR_MINIMO}
        AND L0W_ROLL IS NOT NULL AND L1W_ROLL IS NOT NULL
        AND ((L0W_ROLL - L1W_ROLL) / ABS(L1W_ROLL)) * 100 < -{UMBRAL_ANOMALIA}
        ORDER BY cambio ASC LIMIT 20
    """).fetchdf()

    mejoras_pct = con.execute(f"""
        SELECT 'Mejora' AS categoria, METRIC AS metrica,
               ZONE AS zona, COUNTRY AS pais, CITY AS ciudad,
               ROUND(L0W_ROLL, 2) AS valor_actual,
               ROUND(L1W_ROLL, 2) AS valor_anterior,
               ROUND(((L0W_ROLL - L1W_ROLL) / ABS(L1W_ROLL)) * 100, 1) AS cambio
        FROM metricas
        WHERE METRIC IN {lista_sql(METRICAS_PORCENTAJE)}
        AND ABS(L1W_ROLL) > {UMBRAL_VALOR_MINIMO}
        AND L0W_ROLL IS NOT NULL AND L1W_ROLL IS NOT NULL
        AND ((L0W_ROLL - L1W_ROLL) / ABS(L1W_ROLL)) * 100 > {UMBRAL_ANOMALIA}
        ORDER BY cambio DESC LIMIT 20
    """).fetchdf()

    # Gross Profit UE — diferencia absoluta porque puede ser negativo
    deterioros_gp = con.execute(f"""
        SELECT 'Deterioro' AS categoria, METRIC AS metrica,
               ZONE AS zona, COUNTRY AS pais, CITY AS ciudad,
               ROUND(L0W_ROLL, 2) AS valor_actual,
               ROUND(L1W_ROLL, 2) AS valor_anterior,
               ROUND(L0W_ROLL - L1W_ROLL, 1) AS cambio
        FROM metricas
        WHERE METRIC = 'Gross Profit UE'
        AND ABS(L1W_ROLL) > {UMBRAL_VALOR_MINIMO}
        AND L0W_ROLL IS NOT NULL AND L1W_ROLL IS NOT NULL
        AND (L0W_ROLL - L1W_ROLL) < -{UMBRAL_ANOMALIA}
        ORDER BY cambio ASC LIMIT 20
    """).fetchdf()

    return pd.concat([deterioros_pct, mejoras_pct, deterioros_gp], ignore_index=True)


def detectar_benchmarking(datos):
    """
    Compara cada zona contra el promedio de su grupo (país + tipo de zona).
    Usa DuckDB SQL con AVG y STDDEV_POP — operaciones de agregación nativas.
    """
    con = conectar()
    con.register("metricas", datos)

    return con.execute(f"""
        WITH estadisticas_grupo AS (
            SELECT COUNTRY, ZONE_TYPE, METRIC,
                   AVG(L0W_ROLL)        AS promedio_grupo,
                   STDDEV_POP(L0W_ROLL) AS desvio_grupo
            FROM metricas
            WHERE METRIC IN {lista_sql(METRICAS_BENCHMARKING)}
            AND L0W_ROLL IS NOT NULL
            GROUP BY COUNTRY, ZONE_TYPE, METRIC
            HAVING COUNT(*) >= 3
        )
        SELECT m.METRIC AS metrica, m.COUNTRY AS pais, m.ZONE_TYPE AS tipo_zona,
               m.ZONE AS zona, m.CITY AS ciudad,
               ROUND(m.L0W_ROLL, 2) AS valor_zona,
               ROUND(e.promedio_grupo, 2) AS promedio_grupo,
               ROUND(((m.L0W_ROLL - e.promedio_grupo) / ABS(e.promedio_grupo)) * 100, 1) AS diferencia
        FROM metricas m
        JOIN estadisticas_grupo e
            ON m.COUNTRY = e.COUNTRY AND m.ZONE_TYPE = e.ZONE_TYPE AND m.METRIC = e.METRIC
        WHERE m.L0W_ROLL IS NOT NULL
        AND m.L0W_ROLL < e.promedio_grupo - e.desvio_grupo
        AND ABS((m.L0W_ROLL - e.promedio_grupo) / ABS(e.promedio_grupo)) * 100 > {UMBRAL_BENCHMARK}
        ORDER BY diferencia ASC
    """).fetchdf()


def detectar_correlaciones(datos):
    """
    Calcula correlación de Pearson entre pares de métricas.
    DuckDB pivotea los datos con CASE WHEN, luego pandas calcula las correlaciones
    porque DuckDB no soporta CORR() entre columnas dinámicas sin SQL muy complejo.
    """
    con = conectar()
    con.register("metricas", datos)

    # Pivotear: una fila por zona, una columna por métrica
    tabla_pivot = con.execute(f"""
        SELECT COUNTRY, CITY, ZONE,
            {', '.join([f"MAX(CASE WHEN METRIC = '{m}' THEN L0W_ROLL END) AS \"{m}\""
                       for m in METRICAS_PORCENTAJE])}
        FROM metricas
        GROUP BY COUNTRY, CITY, ZONE
    """).fetchdf()

    metricas_disponibles = [m for m in METRICAS_PORCENTAJE if m in tabla_pivot.columns]
    filas_resultado = []

    for i in range(len(metricas_disponibles)):
        for j in range(i + 1, len(metricas_disponibles)):
            m1, m2 = metricas_disponibles[i], metricas_disponibles[j]
            par = tabla_pivot[[m1, m2]].dropna()
            if len(par) < 10:
                continue
            corr = par[m1].corr(par[m2])
            if abs(corr) >= UMBRAL_CORRELACION:
                filas_resultado.append({
                    "metrica_1": m1, "metrica_2": m2,
                    "correlacion": round(corr, 2),
                    "tipo": "positiva" if corr > 0 else "negativa",
                    "cantidad_zonas": len(par)
                })

    return pd.DataFrame(filas_resultado).sort_values("correlacion", key=abs, ascending=False)


def detectar_tendencias(datos):
    """
    Detecta zonas con deterioro consecutivo en N+ semanas.
    Se implementa en pandas porque requiere evaluar si cada valor
    es menor que el anterior de forma encadenada — en SQL requeriría
    múltiples JOINs o LAG() anidados que se vuelven muy difíciles de leer.
    Solo analiza zonas High Priority o Prioritized para reducir ruido.
    """
    filas_resultado = []
    columnas_recientes = COLUMNAS_SEMANAS[-(SEMANAS_TENDENCIA + 1):]
    zonas_prioritarias = datos[datos["ZONE_PRIORITIZATION"].isin(["High Priority", "Prioritized"])]

    for metrica in zonas_prioritarias["METRIC"].unique():
        for _, fila in zonas_prioritarias[zonas_prioritarias["METRIC"] == metrica].iterrows():
            valores = [fila[col] for col in columnas_recientes if not pd.isna(fila[col])]
            if len(valores) < SEMANAS_TENDENCIA + 1:
                continue
            if all(valores[i] > valores[i + 1] for i in range(len(valores) - 1)):
                if abs(valores[0]) < UMBRAL_VALOR_MINIMO:
                    continue
                cambio_total = ((valores[-1] - valores[0]) / abs(valores[0])) * 100
                if abs(cambio_total) < UMBRAL_CAMBIO_TENDENCIA:
                    continue
                filas_resultado.append({
                    "metrica": metrica, "zona": fila["ZONE"],
                    "pais": fila["COUNTRY"], "ciudad": fila["CITY"],
                    "priorizacion": fila["ZONE_PRIORITIZATION"],
                    "valor_inicio": round(valores[0], 2),
                    "valor_actual": round(valores[-1], 2),
                    "cambio_total": round(cambio_total, 1)
                })
    return pd.DataFrame(filas_resultado).drop_duplicates(subset=["zona", "metrica"])


def detectar_oportunidades(datos):
    """
    Identifica zonas con potencial de crecimiento.
    Usa DuckDB SQL — son filtros y JOINs simples que SQL expresa mejor.
    """
    con = conectar()
    con.register("metricas", datos)

    expansion = con.execute(f"""
        SELECT 'Expansión de oferta' AS tipo,
               ZONE AS zona, COUNTRY AS pais, CITY AS ciudad,
               ROUND(L0W_ROLL, 2) AS valor,
               'Lead Penetration ' || ROUND(L0W_ROLL, 2) || '% — alto potencial de incorporación de comercios' AS descripcion
        FROM metricas
        WHERE METRIC = 'Lead Penetration'
        AND L0W_ROLL IS NOT NULL AND L0W_ROLL < 30
        ORDER BY L0W_ROLL ASC LIMIT 5
    """).fetchdf()

    upsell = con.execute(f"""
        SELECT 'Upsell Pro' AS tipo,
               pro.ZONE AS zona, pro.COUNTRY AS pais, pro.CITY AS ciudad,
               ROUND(pro.L0W_ROLL, 2) AS valor,
               'Pro Adoption ' || ROUND(pro.L0W_ROLL, 2) || '% con Perfect Orders ' || ROUND(perf.L0W_ROLL, 2) || '% — zona con buena operación pero baja monetización Pro' AS descripcion
        FROM metricas pro
        JOIN metricas perf ON pro.ZONE = perf.ZONE AND pro.COUNTRY = perf.COUNTRY
        WHERE pro.METRIC  = 'Pro Adoption (Last Week Status)'
        AND perf.METRIC   = 'Perfect Orders'
        AND pro.L0W_ROLL  IS NOT NULL AND perf.L0W_ROLL IS NOT NULL
        AND pro.L0W_ROLL  < 10 AND perf.L0W_ROLL > 85
        ORDER BY pro.L0W_ROLL ASC LIMIT 5
    """).fetchdf()

    return pd.concat([expansion, upsell], ignore_index=True)


# ── Gráficos ───────────────────────────────────────────────────
def grafico_anomalias(anomalias):
    """Barras horizontales con las peores anomalías de deterioro — mismas zonas que la tabla"""
    # Usar exactamente los mismos top 5 que la tabla, ordenados de peor a mejor
    deterioros = anomalias[anomalias["categoria"] == "Deterioro"].nsmallest(5, "cambio")
    if deterioros.empty:
        return None

    # Si todos los valores son iguales (ej: todos -100%) el gráfico no aporta nada
    if deterioros["cambio"].nunique() == 1:
        return None

    fig, ax = plt.subplots(figsize=(10, 4))
    etiquetas = [f"{r['pais']} — {r['zona'][:25]}\n({r['metrica'][:30]})"
                 for _, r in deterioros.iterrows()]
    valores = deterioros["cambio"].values

    ax.barh(etiquetas, valores, color="#FF441F", alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Cambio vs semana anterior (%)")
    ax.set_title("Top Anomalías — Mayor Deterioro Semana a Semana", fontsize=12, fontweight="bold")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    plt.tight_layout()

    return guardar_figura(fig)


def grafico_tendencias(tendencias):
    """Barras horizontales con tendencias de deterioro más fuertes"""
    if tendencias.empty:
        return None

    top = tendencias.nsmallest(8, "cambio_total")
    fig, ax = plt.subplots(figsize=(10, 4))
    etiquetas = [f"{r['pais']} — {r['zona'][:25]}\n({r['metrica'][:30]})"
                 for _, r in top.iterrows()]
    valores = top["cambio_total"].values

    ax.barh(etiquetas, valores, color="#FF8C00", alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Cambio total en últimas 3 semanas (%)")
    ax.set_title(f"Tendencias Preocupantes — Deterioro Consistente ({SEMANAS_TENDENCIA}+ semanas)", fontsize=12, fontweight="bold")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    plt.tight_layout()

    return guardar_figura(fig)


def grafico_correlaciones(correlaciones):
    """Barras horizontales con las correlaciones más fuertes"""
    if correlaciones.empty:
        return None

    top = correlaciones.head(8)
    fig, ax = plt.subplots(figsize=(10, 4))
    etiquetas = [f"{r['metrica_1'][:25]}\nvs {r['metrica_2'][:25]}"
                 for _, r in top.iterrows()]
    valores = top["correlacion"].values
    colores_barras = ["#FF441F" if v > 0 else "#1A73E8" for v in valores]

    ax.barh(etiquetas, valores, color=colores_barras, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlim(-1, 1)
    ax.set_xlabel("Correlación de Pearson")
    ax.set_title("Correlaciones entre Métricas Operacionales", fontsize=12, fontweight="bold")
    plt.tight_layout()

    return guardar_figura(fig)


# ── LLM — Resumen ejecutivo ────────────────────────────────────
def generar_resumen_llm(anomalias, tendencias, correlaciones, oportunidades):
    cliente = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    top_deterioros = anomalias[anomalias["categoria"] == "Deterioro"].nsmallest(5, "cambio")
    top_tendencias = tendencias.nsmallest(5, "cambio_total") if not tendencias.empty else pd.DataFrame()
    top_corr       = correlaciones.head(5) if not correlaciones.empty else pd.DataFrame()
    top_opps       = oportunidades.head(5) if not oportunidades.empty else pd.DataFrame()

    contexto = f"""
Sos un analista de operaciones de Rappi. Generá un resumen ejecutivo breve y accionable
basado en los siguientes insights automáticos del período actual.

TOP ANOMALÍAS (deterioro semana a semana):
{top_deterioros[['pais','ciudad','zona','metrica','valor_anterior','valor_actual','cambio']].to_string(index=False) if not top_deterioros.empty else 'Sin datos'}

TENDENCIAS PREOCUPANTES (deterioro 3+ semanas):
{top_tendencias[['pais','ciudad','zona','metrica','valor_inicio','valor_actual','cambio_total']].to_string(index=False) if not top_tendencias.empty else 'Sin datos'}

CORRELACIONES CLAVE entre métricas:
{top_corr[['metrica_1','metrica_2','correlacion','tipo']].to_string(index=False) if not top_corr.empty else 'Sin datos'}

OPORTUNIDADES identificadas:
{top_opps[['pais','ciudad','zona','tipo','descripcion']].to_string(index=False) if not top_opps.empty else 'Sin datos'}

Generá:
1. RESUMEN EJECUTIVO (3-4 oraciones, los hallazgos más críticos)
2. TOP 3 HALLAZGOS con una recomendación accionable cada uno
3. Una oportunidad de crecimiento destacada

Sé directo, usa lenguaje de negocio, evitá tecnicismos. Respondé en español.
"""

    mensaje = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": contexto}]
    )
    return mensaje.content[0].text


# ── Generación del PDF ─────────────────────────────────────────
def construir_pdf(anomalias, tendencias, benchmarking, correlaciones, oportunidades, texto_llm):
    doc = SimpleDocTemplate(
        str(RUTA_SALIDA), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        "titulo", parent=estilos["Title"],
        textColor=COLOR_NARANJA, fontSize=22, spaceAfter=6
    )
    estilo_subtitulo = ParagraphStyle(
        "subtitulo", parent=estilos["Heading1"],
        textColor=COLOR_OSCURO, fontSize=14, spaceAfter=4,
        borderPad=4
    )
    estilo_cuerpo = ParagraphStyle(
        "cuerpo", parent=estilos["Normal"],
        fontSize=9, leading=14, spaceAfter=6
    )
    estilo_nota = ParagraphStyle(
        "nota", parent=estilos["Normal"],
        fontSize=8, textColor=colors.grey, spaceAfter=4
    )

    historia = []

    # ── Encabezado ──
    historia.append(Paragraph("Reporte Ejecutivo de Operaciones", estilo_titulo))
    historia.append(Paragraph(
        f"Rappi — Análisis Automático de Métricas | {datetime.now().strftime('%d/%m/%Y')}",
        estilo_nota
    ))
    historia.append(HRFlowable(width="100%", thickness=2, color=COLOR_NARANJA, spaceAfter=12))

    # ── Resumen del LLM ──
    historia.append(Paragraph("Resumen Ejecutivo", estilo_subtitulo))

    for linea in limpiar_markdown_basico(texto_llm):
        historia.append(Paragraph(linea, estilo_cuerpo))
    historia.append(Spacer(1, 0.4*cm))

    # ── Tabla resumen de conteos ──
    historia.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=8))
    historia.append(Paragraph("Resumen de Insights Detectados", estilo_subtitulo))

    datos_tabla = [
        ["Categoría", "Cantidad"],
        ["Anomalías detectadas", str(len(anomalias))],
        ["Tendencias preocupantes", str(len(tendencias))],
        ["Casos de benchmarking", str(len(benchmarking))],
        ["Correlaciones relevantes", str(len(correlaciones))],
        ["Oportunidades identificadas", str(len(oportunidades))],
    ]
    tabla_resumen = crear_tabla(
        datos_tabla,
        [10*cm, 4*cm],
        font_size=9,
        align=[("ALIGN", (1, 0), (1, -1), "CENTER")],
        padding=5,
    )
    historia.append(tabla_resumen)
    historia.append(Spacer(1, 0.5*cm))

    # ── Sección Anomalías ──
    historia.append(PageBreak())
    historia.append(Paragraph("1. Anomalías Semana a Semana", estilo_subtitulo))
    historia.append(Paragraph(
        "Zonas con cambios drásticos (>10%) en una semana. Las de deterioro requieren atención inmediata.",
        estilo_nota
    ))

    grafico_anom = grafico_anomalias(anomalias)
    if grafico_anom:
        historia.append(Image(grafico_anom, width=16*cm, height=7*cm))
        historia.append(Spacer(1, 0.3*cm))

    top_det = anomalias[anomalias["categoria"] == "Deterioro"].nsmallest(5, "cambio")
    if not top_det.empty:
        historia.append(Paragraph("Top deterioros:", estilo_cuerpo))
        encabezado = [["País", "Zona", "Métrica", "Anterior", "Actual", "Cambio"]]
        filas = [
            [r["pais"], r["zona"][:28], r["metrica"][:28],
             str(r["valor_anterior"]), str(r["valor_actual"]), f"{r['cambio']}%"]
            for _, r in top_det.iterrows()
        ]
        tabla_det = crear_tabla(
            encabezado + filas,
            [1.5*cm, 4.5*cm, 4.5*cm, 2*cm, 2*cm, 2*cm],
            align=[("ALIGN", (3, 0), (-1, -1), "CENTER")],
        )
        historia.append(tabla_det)

    # ── Sección Tendencias ──
    historia.append(Spacer(1, 0.5*cm))
    historia.append(Paragraph("2. Tendencias Preocupantes", estilo_subtitulo))
    historia.append(Paragraph(
        f"Zonas con deterioro consecutivo en {SEMANAS_TENDENCIA}+ semanas en zonas High Priority o Prioritized.",
        estilo_nota
    ))

    grafico_tend = grafico_tendencias(tendencias)
    if grafico_tend:
        historia.append(Image(grafico_tend, width=16*cm, height=7*cm))
        historia.append(Spacer(1, 0.3*cm))

    if not tendencias.empty:
        top_tend = tendencias.nsmallest(5, "cambio_total")
        encabezado = [["País", "Zona", "Métrica", "Inicio", "Actual", "Cambio"]]
        filas = [
            [r["pais"], r["zona"][:28], r["metrica"][:28],
             str(r["valor_inicio"]), str(r["valor_actual"]), f"{r['cambio_total']}%"]
            for _, r in top_tend.iterrows()
        ]
        tabla_tend = crear_tabla(
            encabezado + filas,
            [1.5*cm, 4.5*cm, 4.5*cm, 2*cm, 2*cm, 2*cm],
            align=[("ALIGN", (3, 0), (-1, -1), "CENTER")],
        )
        historia.append(tabla_tend)

    # ── Sección Correlaciones ──
    historia.append(PageBreak())
    historia.append(Paragraph("3. Correlaciones entre Métricas", estilo_subtitulo))
    historia.append(Paragraph(
        "Métricas que se mueven juntas. Correlación positiva alta = si una sube, la otra también.",
        estilo_nota
    ))

    grafico_corr = grafico_correlaciones(correlaciones)
    if grafico_corr:
        historia.append(Image(grafico_corr, width=16*cm, height=7*cm))
        historia.append(Spacer(1, 0.3*cm))

    if not correlaciones.empty:
        encabezado = [["Métrica 1", "Métrica 2", "Correlación", "Tipo", "Zonas"]]
        filas = [
            [r["metrica_1"][:30], r["metrica_2"][:30],
             str(r["correlacion"]), r["tipo"], str(r["cantidad_zonas"])]
            for _, r in correlaciones.head(8).iterrows()
        ]
        tabla_corr = crear_tabla(
            encabezado + filas,
            [5*cm, 5*cm, 2.5*cm, 2.5*cm, 2*cm],
            align=[("ALIGN", (2, 0), (-1, -1), "CENTER")],
        )
        historia.append(tabla_corr)

    # ── Sección Oportunidades ──
    historia.append(Spacer(1, 0.5*cm))
    historia.append(Paragraph("4. Oportunidades Identificadas", estilo_subtitulo))
    historia.append(Paragraph(
        "Zonas con potencial de crecimiento en oferta de comercios o monetización de usuarios Pro.",
        estilo_nota
    ))

    if not oportunidades.empty:
        encabezado = [["País", "Ciudad", "Zona", "Tipo", "Descripción"]]
        filas = [
            [r["pais"], r["ciudad"][:15], r["zona"][:20], r["tipo"], r["descripcion"][:50]]
            for _, r in oportunidades.iterrows()
        ]
        tabla_opps = crear_tabla(
            encabezado + filas,
            [1.5*cm, 3*cm, 3.5*cm, 3*cm, 6*cm],
            font_size=7,
            valign="TOP",
        )
        historia.append(tabla_opps)

    doc.build(historia)
    print(f"Reporte generado: {RUTA_SALIDA}")


# ── Main ───────────────────────────────────────────────────────
def main():
    print("carga de datos...")
    datos         = cargar_datos()
    anomalias     = detectar_anomalias(datos)
    tendencias    = detectar_tendencias(datos)
    benchmarking  = detectar_benchmarking(datos)
    correlaciones = detectar_correlaciones(datos)
    oportunidades = detectar_oportunidades(datos)

    print("Generando resumen")
    texto_llm = generar_resumen_llm(anomalias, tendencias, correlaciones, oportunidades)

    print("PDF...")
    construir_pdf(anomalias, tendencias, benchmarking, correlaciones, oportunidades, texto_llm)


if __name__ == "__main__":
    main()