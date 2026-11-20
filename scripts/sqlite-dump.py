#!/usr/bin/env python3
"""sqlite-dump.py <db> [--table T] [--sql Q] [--limit N] [--list]
查库不改库。--list 只列表名和行数，用来快速摸结构。
"""
import argparse, sqlite3, sys, os
ap=argparse.ArgumentParser()
ap.add_argument("db"); ap.add_argument("--table"); ap.add_argument("--sql")
ap.add_argument("--limit", type=int, default=50); ap.add_argument("--list", action="store_true")
a=ap.parse_args()
if not os.path.exists(a.db): sys.exit(f"没有 {a.db}")
con=sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
con.text_factory=lambda b: b.decode('utf-8','replace')
cur=con.cursor()
if a.list or (not a.sql and not a.table):
    rows=cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for (t,) in rows:
        try: n=cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        except sqlite3.Error: n='?'
        print(f"{t}\t{n}")
    sys.exit(0)
sql=a.sql or f'SELECT * FROM "{a.table}" LIMIT {a.limit}'
cur.execute(sql)
cols=[d[0] for d in cur.description or []]
print("\t".join(cols))
for r in cur.fetchmany(a.limit):
    print("\t".join('' if v is None else str(v)[:200] for v in r))
