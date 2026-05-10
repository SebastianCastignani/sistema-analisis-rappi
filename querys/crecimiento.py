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