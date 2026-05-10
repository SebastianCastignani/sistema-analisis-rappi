import duckdb
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
METRICS_PATH = str(BASE_DIR / "RAW_INPUT_METRICS.csv")

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