import duckdb
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
METRICS_PATH = str(BASE_DIR / "RAW_INPUT_METRICS.csv")



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