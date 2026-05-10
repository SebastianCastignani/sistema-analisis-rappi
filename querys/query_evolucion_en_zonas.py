import duckdb
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
METRICS_PATH = str(BASE_DIR / "RAW_INPUT_METRICS.csv")



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