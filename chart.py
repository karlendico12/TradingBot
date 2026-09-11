import pandas as pd
import sqlite3
import mplfinance as mpf

def draw():

    conn=sqlite3.connect("database/trading.db")

    df=pd.read_sql(
        "SELECT * FROM candles",
        conn
    )

    df["time"]=pd.to_datetime(
        df["time"],
        unit="ms"
    )

    df=df.set_index("time")

    mpf.plot(
        df,
        type="candle",
        mav=(20,50,200),
        style="nightclouds"
    )