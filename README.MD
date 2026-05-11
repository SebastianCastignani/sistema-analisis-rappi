# Sistema de Análisis Inteligente para Operaciones Rappi
 
Bot conversacional y sistema de insights automáticos para que equipos de SP&A y Operations puedan consultar métricas operacionales en lenguaje natural y recibir reportes ejecutivos semanales.
 
---
  
Este sistema resuelve dos problemas:
 
1. **Chatbot conversacional** — cualquier persona del equipo puede preguntar en lenguaje natural y obtener análisis con interpretación de negocio
2. **Reporte automático de insights** — cada semana el sistema analiza anomalías, tendencias y oportunidades y genera un PDF ejecutivo
---
 
## Arquitectura
 
```
Usuario
  │
  ▼
n8n (Agente de IA con OpenAI)
  │
  ├── Tool: get_top_zones       → GET /zones/top
  ├── Tool: valor_promedio      → GET /zones/compare
  ├── Tool: evolucion_metricas  → GET /zones/trend
  ├── Tool: alta_y_baja_metrica → GET /zones/cross
  └── Tool: crecimiento         → GET /orders/growth
                                        │
                                        ▼
                              FastAPI + DuckDB (Railway)
                                        │
                                        ▼
                              RAW_INPUT_METRICS.csv
                              RAW_ORDERS.csv
```
 
El agente de n8n recibe la pregunta del usuario, decide qué endpoint(s) consultar según el contexto, interpreta el JSON que devuelve la API y responde en lenguaje natural con análisis de negocio.
 
---
 
## Chatbot — Cómo funciona
 
El chatbot está construido en **n8n** usando un agente de IA con:
- **Modelo**: gpt-5-mini (OpenAI)
- **Memoria**: Simple Memory para seguimiento del diálogo
- **Tools**: 5 endpoints HTTP que consultan los datos operacionales
### Tipos de preguntas que puede responder
 
| Tipo | Ejemplo |
|------|---------|
| Filtrado | "¿Cuáles son las 5 zonas con mayor % Lead Penetration esta semana?" |
| Comparación | "Compara el Perfect Order entre zonas Wealthy y Non Wealthy en México" |
| Tendencia temporal | "Muestra la evolución de Gross Profit UE en Chapinero últimas 8 semanas" |
| Agregación | "¿Cuál es el promedio de Lead Penetration por país?" |
| Análisis multivariable | "¿Qué zonas tienen alto Lead Penetration pero bajo Perfect Order?" |
| Inferencia | "¿Cuáles son las zonas que más crecen en órdenes en las últimas 5 semanas y qué podría explicar el crecimiento?" |
 
### Métricas disponibles
 
- Lead Penetration
- Perfect Orders
- Gross Profit UE
- Pro Adoption (Last Week Status)
- % PRO Users Who Breakeven
- Non-Pro PTC > OP
- Turbo Adoption
- MLTV Top Verticals Adoption
- Restaurants Markdowns / GMV
- % Restaurants Sessions With Optimal Assortment
- Restaurants SS > ATC CVR
- Restaurants SST > SS CVR
- Retail SST > SS CVR
---
 
## Endpoints de la API
 
Base URL: `https://web-production-14977.up.railway.app`
 
### `GET /zones/top`
Top N zonas por valor de una métrica.
 
| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `metric` | string | `Lead Penetration` | Nombre exacto de la métrica |
| `week` | string | `L0W_ROLL` | Semana a consultar (L0W_ROLL = actual, L1W_ROLL = anterior...) |
| `limit` | int | `5` | Cantidad de zonas a devolver |
| `order` | string | `DESC` | `DESC` para mayores primero, `ASC` para menores |
 
**Ejemplo:**
```
GET /zones/top?metric=Perfect Orders&limit=10&order=ASC
```
 
---
 
### `GET /zones/compare`
Compara el promedio de una métrica agrupando por país, tipo de zona o priorización.
 
| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `metric` | string | `Perfect Orders` | Nombre exacto de la métrica |
| `group_by` | string | `ZONE_TYPE` | `ZONE_TYPE`, `COUNTRY` o `ZONE_PRIORITIZATION` |
| `week` | string | `L0W_ROLL` | Semana a consultar |
| `country` | string | `None` | Filtrar por país (AR, BR, CL, CO, CR, EC, MX, PE, UY) |
 
**Ejemplo:**
```
GET /zones/compare?metric=Perfect Orders&group_by=ZONE_TYPE&country=MX
```
 
---
 
### `GET /zones/trend`
Evolución semanal de una métrica en una zona específica.
 
| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `metric` | string | `Gross Profit UE` | Nombre exacto de la métrica |
| `zone` | string | `Chapinero` | Nombre exacto de la zona |
| `weeks` | int | `9` | Cantidad de semanas (máximo 9) |
 
**Ejemplo:**
```
GET /zones/trend?metric=Gross Profit UE&zone=Chapinero&weeks=8
```
 
---
 
### `GET /zones/cross`
Zonas que tienen una métrica alta y otra baja simultáneamente.
 
| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `metric_high` | string | `Lead Penetration` | Métrica que debe ser alta |
| `metric_low` | string | `Perfect Orders` | Métrica que debe ser baja |
| `threshold_high` | float | `70.0` | Umbral mínimo para métrica alta |
| `threshold_low` | float | `75.0` | Umbral máximo para métrica baja |
| `week` | string | `L0W_ROLL` | Semana a consultar |
| `country` | string | `None` | Filtrar por país (opcional) |
 
**Ejemplo:**
```
GET /zones/cross?metric_high=Lead Penetration&metric_low=Perfect Orders&country=BR
```
 
---
 
### `GET /orders/growth`
Zonas con mayor crecimiento en órdenes comparando semanas.
 
| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `weeks` | int | `5` | Semanas a comparar (L0W vs LNW) |
| `limit` | int | `10` | Cantidad de zonas a devolver |
| `country` | string | `None` | Filtrar por país (opcional) |
 
**Ejemplo:**
```
GET /orders/growth?weeks=5&limit=10&country=CO
```
 
---
 
### `GET /insights/report`
Genera y devuelve el reporte ejecutivo automático en PDF.
 
```
GET /insights/report
```
 
No requiere parámetros. Corre el análisis completo y devuelve el PDF.
 
---
 
## Cómo correrlo localmente

### Requisitos
- Python 3.11+
- n8n (cloud o local)

### 1. Clonar el repo
```bash
git clone https://github.com/SebastianCastignani/sistema-analisis-rappi.git
cd sistema-analisis-rappi
```

### 2. Importar el workflow de n8n (primero)
- Abrí n8n
- Importá el archivo `n8n_workflow.json`
- Configurá tu OpenAI API key en el nodo de modelo — **es lo único que tenés que configurar**
- Los endpoints ya están precargados en los nodos HTTP y apuntan a Railway

### 3. Usar endpoints ya deployados (recomendado)

Los endpoints ya están disponibles en Railway, no hace falta levantar nada:

```
https://web-production-14977.up.railway.app
```

Podés probarlos directamente en el browser.

### 4. Usar endpoints locales (opcional)

Si querés correr la API localmente:

```bash
python3 -m uvicorn main:app --reload --port 8000
```

La terminal te va a mostrar algo así:

```
INFO: Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

En ese caso reemplazá la URL base en cada tool HTTP de n8n:
- De: `https://web-production-14977.up.railway.app`
- A: `http://localhost:8000`

### 5. Configurar entorno local (si vas a correr scripts)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 6. Configurar variables de entorno (solo para ejecución local)
```bash
cp .env.example .env
# Editar .env y agregar tu ANTHROPIC_API_KEY
```
---
 
## Reporte de Insights Automáticos

Tenés dos formas de generarlo:

**Desde el navegador** (Railway):
```
https://web-production-14977.up.railway.app/insights/report
```
Descarga el PDF directamente sin necesidad de correr nada localmente.

**Desde la terminal (local):**
```bash
python3 insight_automatico.py
```
Genera `reporte_rappi.pdf` en la carpeta raíz. Para el modo local necesitás una API key de Anthropic en `.env`.Para generar una se hace desde la consola de claude `https://platform.claude.com/settings/workspaces/default/keys`
 
---
 
## Deploy
 
La API está deployada en **Railway** y se redeploya automáticamente con cada push a `main`.
 
URL pública: `https://web-production-14977.up.railway.app`
 
 
---
 
## Stack tecnológico
 
| Componente | Tecnología |
|------------|------------|
| Agente conversacional | n8n + OpenAI gpt-5-mini |
| API de datos | FastAPI + DuckDB |
| Deploy API | Railway |
| Análisis de insights | Python (pandas, numpy) |
| Generación de PDF | ReportLab + Matplotlib |
| LLM para resumen | Anthropic Claude |
| Datos | CSV (RAW_INPUT_METRICS, RAW_ORDERS) |
 
---
 
## Limitaciones conocidas
 
- **Datos inconsistentes**: el dataset tiene algunos valores de Lead Penetration fuera del rango esperado (>100%) — el bot detecta estas inconsistencias automáticamente y las excluye del análisis
- **Semana actual parcial**: L0W_ROLL puede representar una semana incompleta, lo que puede generar caídas aparentes en métricas
- **Sin visualizaciones en el chat**: el chatbot responde en texto; los gráficos están disponibles solo en el reporte PDF
- **n8n Cloud**: el workflow requiere credenciales propias de OpenAI
---

## Próximos pasos

- **DataBase nativo**: en producción los datos estarían en algun servicio supongo; n8n tiene una tool nativa que eliminaría la capa de FastAPI para la mayorias de los casos , ejemplo si toda la info de rappi esta en bigquery , n8n tiene tool para hacer querys sobre ese servicio directo , esto eliminaria la parte de fastAPI y codigo python (otro caso es remplazar los endpoint del servidor por lambdas)
- **Memoria en una base de datos** Actualmente a manera de prueba de concepto le puse al bot la memoria integrada de n8n , si se pasara a produccion se tendria que crear una memoria en algina base de datos , ejemplo POstgreSQL , de esta manera tendria mas ventana de contexto sin la necesidad de saturar la instancia de n8n
- **Visualizaciones en chat**: integrar gráficos inline en la respuesta del bot
- **Integrar chatbot**: Actualmente el chatbot se prueba mediante la ventana de chat que tiene n8n , si el chatbot es util se podria integrar a herramientas como slack , whatsapp o algun crm , para que los diferntes equipos lo puedan utilizar de manera sencilla (n8n tiene nodos para estos servicios)
- **Arquitectura serverless**: migrar cada endpoint a una Lambda/Cloud Function para escalar sin servidor

---

## Costos (estimados)

### Infraestructura
- **Railway**: uso la version gratuita (5 creditos). Si se pasa a pago, el plan base es de ~$5/mes.
- **Alternativas**: se puede usar alguna instancia de AWS con capa gratuita para reducir costos.

### Modelos
- **Claude Sonnet 4.6** (resumen del PDF): una llamada tipica cuesta aproximadamente $0.021 USD.
- **GPT-5 mini** (chatbot): $0.25 por millon de tokens de entrada y $2.00 por millon de tokens de salida. En una llamada tipica el costo es muy bajo.