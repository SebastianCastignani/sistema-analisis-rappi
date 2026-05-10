import duckdb
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
METRICS_PATH = str(BASE_DIR / "RAW_INPUT_METRICS.csv")
ORDERS_PATH = str(BASE_DIR / "RAW_ORDERS.csv")





@app.get("/orders/growth")
def orders_growth(
    weeks: int = Query(default=5),
    limit: int = Query(default=10),
    country: str = Query(default=None)
):
    week_col = f"L{weeks-1}W"
    
    if country:
        query = f"""
            SELECT 
                o.COUNTRY, o.CITY, o.ZONE,
                ROUND(o.L0W, 2) AS orders_this_week,
                ROUND(o."{week_col}", 2) AS orders_{weeks}w_ago,
                ROUND(((o.L0W - o."{week_col}") / NULLIF(o."{week_col}", 0)) * 100, 2) AS growth_pct
            FROM read_csv_auto(?, HEADER=TRUE) o
            WHERE o.METRIC = 'Orders'
            AND o.COUNTRY = ?
            AND o."{week_col}" > 0
            ORDER BY growth_pct DESC
            LIMIT ?
        """
        params = [ORDERS_PATH, country, limit]
    else:
        query = f"""
            SELECT 
                o.COUNTRY, o.CITY, o.ZONE,
                ROUND(o.L0W, 2) AS orders_this_week,
                ROUND(o."{week_col}", 2) AS orders_{weeks}w_ago,
                ROUND(((o.L0W - o."{week_col}") / NULLIF(o."{week_col}", 0)) * 100, 2) AS growth_pct
            FROM read_csv_auto(?, HEADER=TRUE) o
            WHERE o.METRIC = 'Orders'
            AND o."{week_col}" > 0
            ORDER BY growth_pct DESC
            LIMIT ?
        """
        params = [ORDERS_PATH, limit]

    con = duckdb.connect()
    result = con.execute(query, params).fetchdf()
    return JSONResponse(result.to_dict(orient="records"))



@app.get("/zones/cross")
def cross_metrics(
    metric_high: str = Query(default="Lead Penetration"),
    metric_low: str = Query(default="Perfect Orders"),
    threshold_high: float = Query(default=50.0),
    threshold_low: float = Query(default=50.0),
    week: str = Query(default="L0W_ROLL"),
    country: str = Query(default=None)
):
    country_filter = "AND COUNTRY = ?" if country else ""

    query = f"""
        SELECT 
            a.ZONE, a.COUNTRY, a.CITY, a.ZONE_TYPE, a.ZONE_PRIORITIZATION,
            a.value AS value_high,
            b.value AS value_low
        FROM
            (SELECT ZONE, COUNTRY, CITY, ZONE_TYPE, ZONE_PRIORITIZATION,
                    ROUND("{week}" * 100, 2) AS value
             FROM read_csv_auto(?, HEADER=TRUE)
             WHERE METRIC = ?
             {country_filter}) a
        JOIN
            (SELECT ZONE, ROUND("{week}" * 100, 2) AS value
             FROM read_csv_auto(?, HEADER=TRUE)
             WHERE METRIC = ?
             {country_filter}) b
        ON a.ZONE = b.ZONE
        WHERE a.value > ?
        AND b.value < ?
        ORDER BY a.value DESC
    """

    params = [METRICS_PATH, metric_high]
    if country:
        params.append(country)
    params += [METRICS_PATH, metric_low]
    if country:
        params.append(country)
    params += [threshold_high, threshold_low]

    con = duckdb.connect()
    result = con.execute(query, params).fetchdf()
    return JSONResponse(result.to_dict(orient="records"))


@app.get("/zones/trend")
def zone_trend(
    metric: str = Query(default="Gross Profit UE"),
    zone: str = Query(default="Chapinero"),
    weeks: int = Query(default=8)
):
    # construimos las columnas según las semanas pedidas
    # si piden 4 semanas → L0W_ROLL, L1W_ROLL, L2W_ROLL, L3W_ROLL
    week_cols = ", ".join([f"L{i}W_ROLL" for i in range(weeks)])

    query = f"""
        UNPIVOT (
            SELECT COUNTRY, CITY, ZONE, {week_cols}
            FROM read_csv_auto(?, HEADER=TRUE)
            WHERE METRIC = ?
            AND ZONE = ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ZONE) = 1
        )
        ON {week_cols}
        INTO NAME week VALUE value
        ORDER BY week DESC
    """
    con = duckdb.connect()
    result = con.execute(query, [METRICS_PATH, metric, zone]).fetchdf()
    result["value"] = (result["value"] * 100).round(2)
    return JSONResponse(result.to_dict(orient="records"))



@app.get("/zones/top")
def top_zones(
    metric: str = Query(default="Lead Penetration"),
    week: str = Query(default="L0W_ROLL"),
    limit: int = Query(default=5)
):
    query = f"""
        SELECT COUNTRY, CITY, ZONE, ZONE_TYPE, ZONE_PRIORITIZATION,
               "{week}" AS value
        FROM read_csv_auto(?, HEADER=TRUE)
        WHERE METRIC = ?
        ORDER BY value DESC
        LIMIT ?
    """
    con = duckdb.connect()
    result = con.execute(query, [METRICS_PATH, metric, limit]).fetchdf()
    return JSONResponse(result.to_dict(orient="records"))


@app.get("/zones/compare")
def compare_zones(
    metric: str = Query(default="Perfect Orders"),
    group_by: str = Query(default="ZONE_TYPE"),
    country: str = Query(default=None),
    week: str = Query(default="L0W_ROLL")  # L0W_ROLL, L1W_ROLL, L2W_ROLL...
):
    con = duckdb.connect()

    if country:
        query = f"""
            SELECT {group_by},
                   ROUND(AVG("{week}") * 100, 2) AS avg_value_pct,
                   COUNT(DISTINCT ZONE) AS total_zones
            FROM read_csv_auto(?, HEADER=TRUE)
            WHERE METRIC = ?
            AND COUNTRY = ?
            GROUP BY {group_by}
            ORDER BY avg_value_pct DESC
        """
        result = con.execute(query, [METRICS_PATH, metric, country]).fetchdf()
    else:
        query = f"""
            SELECT {group_by},
                   ROUND(AVG("{week}") * 100, 2) AS avg_value_pct,
                   COUNT(DISTINCT ZONE) AS total_zones
            FROM read_csv_auto(?, HEADER=TRUE)
            WHERE METRIC = ?
            GROUP BY {group_by}
            ORDER BY avg_value_pct DESC
        """
        result = con.execute(query, [METRICS_PATH, metric]).fetchdf()

    return JSONResponse(result.to_dict(orient="records"))
