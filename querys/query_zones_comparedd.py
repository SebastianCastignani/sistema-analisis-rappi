import duckdb
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()


BASE_DIR = Path(__file__).resolve().parent
METRICS_PATH = str(BASE_DIR / "RAW_INPUT_METRICS.csv")


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