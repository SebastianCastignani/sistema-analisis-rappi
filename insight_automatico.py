from dotenv import load_dotenv
load_dotenv()
import os
import io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # sin interfaz gráfica, para servidor
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path
from datetime import datetime
import anthropic

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
def _normalizar_porcentaje(serie):
    """Normaliza valores en [0,1] a porcentaje; invalida >100."""
    serie = serie.copy()
    serie[serie <= 1] = serie[serie <= 1] * 100
    serie[serie > 100] = np.nan
    return serie


def _formatear_tabla(filas, col_widths):
    tabla = Table(filas, colWidths=col_widths)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_NARANJA),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOR_GRIS, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tabla


def _guardar_figura(fig):
    """Guarda un matplotlib fig en memoria para ReportLab."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _limpiar_markdown_basico(texto):
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
    datos = pd.read_csv(RUTA_METRICAS)
    for columna in COLUMNAS_SEMANAS:
        es_pct = datos["METRIC"].isin(METRICAS_PORCENTAJE)
        datos.loc[es_pct, columna] = _normalizar_porcentaje(datos.loc[es_pct, columna])
    return datos


# ── Análisis ───────────────────────────────────────────────────
def detectar_anomalias(datos):
    filas_resultado = []
    for metrica in datos["METRIC"].unique():
        datos_metrica = datos[datos["METRIC"] == metrica].copy()
        datos_metrica = datos_metrica[datos_metrica["L1W_ROLL"].abs() > UMBRAL_VALOR_MINIMO]

        if datos_metrica["L1W_ROLL"].min() < 0:
            datos_metrica["cambio_porcentual"] = datos_metrica["L0W_ROLL"] - datos_metrica["L1W_ROLL"]
        else:
            datos_metrica["cambio_porcentual"] = (
                (datos_metrica["L0W_ROLL"] - datos_metrica["L1W_ROLL"])
                / datos_metrica["L1W_ROLL"].abs() * 100
            )

        datos_metrica = datos_metrica.dropna(subset=["cambio_porcentual"])

        for _, fila in datos_metrica[datos_metrica["cambio_porcentual"] < -UMBRAL_ANOMALIA].nsmallest(3, "cambio_porcentual").iterrows():
            filas_resultado.append({
                "categoria": "Deterioro", "metrica": metrica,
                "zona": fila["ZONE"], "pais": fila["COUNTRY"], "ciudad": fila["CITY"],
                "valor_actual": round(fila["L0W_ROLL"], 2),
                "valor_anterior": round(fila["L1W_ROLL"], 2),
                "cambio": round(fila["cambio_porcentual"], 1)
            })
        for _, fila in datos_metrica[datos_metrica["cambio_porcentual"] > UMBRAL_ANOMALIA].nlargest(3, "cambio_porcentual").iterrows():
            filas_resultado.append({
                "categoria": "Mejora", "metrica": metrica,
                "zona": fila["ZONE"], "pais": fila["COUNTRY"], "ciudad": fila["CITY"],
                "valor_actual": round(fila["L0W_ROLL"], 2),
                "valor_anterior": round(fila["L1W_ROLL"], 2),
                "cambio": round(fila["cambio_porcentual"], 1)
            })
    return pd.DataFrame(filas_resultado)


def detectar_tendencias(datos):
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


def detectar_benchmarking(datos):
    filas_resultado = []
    for metrica in METRICAS_BENCHMARKING:
        datos_metrica = datos[datos["METRIC"] == metrica].dropna(subset=["L0W_ROLL"])
        for (pais, tipo_zona), grupo in datos_metrica.groupby(["COUNTRY", "ZONE_TYPE"]):
            if len(grupo) < 3:
                continue
            promedio = grupo["L0W_ROLL"].mean()
            desvio   = grupo["L0W_ROLL"].std()
            for _, fila in grupo[grupo["L0W_ROLL"] < promedio - desvio].nsmallest(2, "L0W_ROLL").iterrows():
                diferencia = (fila["L0W_ROLL"] - promedio) / abs(promedio) * 100
                if abs(diferencia) > UMBRAL_BENCHMARK:
                    filas_resultado.append({
                        "metrica": metrica, "pais": pais, "tipo_zona": tipo_zona,
                        "zona": fila["ZONE"], "ciudad": fila["CITY"],
                        "valor_zona": round(fila["L0W_ROLL"], 2),
                        "promedio_grupo": round(promedio, 2),
                        "diferencia": round(diferencia, 1)
                    })
    return pd.DataFrame(filas_resultado)


def detectar_correlaciones(datos):
    tabla_pivot = datos.pivot_table(
        index=["COUNTRY", "CITY", "ZONE"], columns="METRIC",
        values="L0W_ROLL", aggfunc="mean"
    )
    metricas = [m for m in METRICAS_PORCENTAJE if m in tabla_pivot.columns]
    filas_resultado = []

    for i in range(len(metricas)):
        for j in range(i + 1, len(metricas)):
            m1, m2 = metricas[i], metricas[j]
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


def detectar_oportunidades(datos):
    filas_resultado = []

    datos_lead = datos[datos["METRIC"] == "Lead Penetration"].dropna(subset=["L0W_ROLL"])
    for _, fila in datos_lead[datos_lead["L0W_ROLL"] < 30].nsmallest(5, "L0W_ROLL").iterrows():
        filas_resultado.append({
            "tipo": "Expansión de oferta",
            "zona": fila["ZONE"], "pais": fila["COUNTRY"], "ciudad": fila["CITY"],
            "valor": round(fila["L0W_ROLL"], 2),
            "descripcion": f"Lead Penetration {round(fila['L0W_ROLL'], 2)}% — alto potencial de incorporación de comercios"
        })

    datos_pro     = datos[datos["METRIC"] == "Pro Adoption (Last Week Status)"].dropna(subset=["L0W_ROLL"])
    datos_perfect = datos[datos["METRIC"] == "Perfect Orders"].dropna(subset=["L0W_ROLL"])
    combinados    = datos_pro.merge(datos_perfect, on=["COUNTRY", "CITY", "ZONE"], suffixes=("_pro", "_perfect"))
    zonas_upsell  = combinados[(combinados["L0W_ROLL_pro"] < 10) & (combinados["L0W_ROLL_perfect"] > 85)]

    for _, fila in zonas_upsell.nsmallest(5, "L0W_ROLL_pro").iterrows():
        filas_resultado.append({
            "tipo": "Upsell Pro",
            "zona": fila["ZONE"], "pais": fila["COUNTRY"], "ciudad": fila["CITY"],
            "valor": round(fila["L0W_ROLL_pro"], 2),
            "descripcion": f"Pro Adoption {round(fila['L0W_ROLL_pro'], 2)}% con Perfect Orders {round(fila['L0W_ROLL_perfect'], 2)}% — zona con buena operación pero baja monetización Pro"
        })
    return pd.DataFrame(filas_resultado)


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

    return _guardar_figura(fig)


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

    return _guardar_figura(fig)


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

    return _guardar_figura(fig)


# ── LLM — Resumen ejecutivo ────────────────────────────────────
def generar_resumen_llm(anomalias, tendencias, correlaciones, oportunidades):
    """
    Envía un resumen de los insights al LLM y pide un texto ejecutivo
    en lenguaje de negocio para incluir en el reporte.
    """
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

    for linea in _limpiar_markdown_basico(texto_llm):
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
    tabla_resumen = _formatear_tabla(datos_tabla, [10*cm, 4*cm])
    tabla_resumen.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
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
        tabla_det = _formatear_tabla(encabezado + filas, [1.5*cm, 4.5*cm, 4.5*cm, 2*cm, 2*cm, 2*cm])
        tabla_det.setStyle(TableStyle([("ALIGN", (3, 0), (-1, -1), "CENTER")]))
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
        tabla_tend = _formatear_tabla(encabezado + filas, [1.5*cm, 4.5*cm, 4.5*cm, 2*cm, 2*cm, 2*cm])
        tabla_tend.setStyle(TableStyle([("ALIGN", (3, 0), (-1, -1), "CENTER")]))
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
        tabla_corr = _formatear_tabla(encabezado + filas, [5*cm, 5*cm, 2.5*cm, 2.5*cm, 2*cm])
        tabla_corr.setStyle(TableStyle([("ALIGN", (2, 0), (-1, -1), "CENTER")]))
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
        tabla_opps = _formatear_tabla(encabezado + filas, [1.5*cm, 3*cm, 3.5*cm, 3*cm, 6*cm])
        tabla_opps.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        historia.append(tabla_opps)

    doc.build(historia)
    print(f"Reporte generado: {RUTA_SALIDA}")


# ── Main ───────────────────────────────────────────────────────
def main():
    print("Analizando datos...")
    datos         = cargar_datos()
    anomalias     = detectar_anomalias(datos)
    tendencias    = detectar_tendencias(datos)
    benchmarking  = detectar_benchmarking(datos)
    correlaciones = detectar_correlaciones(datos)
    oportunidades = detectar_oportunidades(datos)

    print("Generando resumen con IA...")
    texto_llm = generar_resumen_llm(anomalias, tendencias, correlaciones, oportunidades)

    print("Construyendo PDF...")
    construir_pdf(anomalias, tendencias, benchmarking, correlaciones, oportunidades, texto_llm)


if __name__ == "__main__":
    main()