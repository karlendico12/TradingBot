import sqlite3

db=sqlite3.connect("database/trading.db")

cur=db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS candles(
time INTEGER PRIMARY KEY,
open REAL,
high REAL,
low REAL,
close REAL,
volume REAL
)
""")

db.commit()

def save(c):

    cur.execute(
        """
        INSERT OR REPLACE INTO candles
        VALUES(?,?,?,?,?,?)
        """,
        (
            c["t"],
            c["o"],
            c["h"],
            c["l"],
            c["c"],
            c["v"]
        )
    )

    db.commit()