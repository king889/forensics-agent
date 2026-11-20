#!/usr/bin/env python3
"""最小 sqlcipher 命令行，兼容 sqlite3 的常用用法。

    sqlcipher enc.db "PRAGMA key='PASSWORD'; .tables"
    sqlcipher enc.db "PRAGMA key='PASSWORD'; select * from msg limit 5"
    sqlcipher enc.db < script.sql

支持 .tables / .schema / .databases / .quit。
注意：PRAGMA key 必须是第一条语句。
"""

import sys

try:
    import sqlcipher3
except ImportError:
    sys.exit("sqlcipher3 没装：tools/install.sh sqlcipher")


def tokenize(text):
    """切成 ('dot', cmd) / ('sql', stmt)，引号里的分号不当分隔符。"""
    out, buf, quote, at_line_start, i = [], "", None, True, 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf += ch
        elif ch == "." and at_line_start and not buf.strip():
            j = i
            while j < len(text) and text[j] not in "\n;":
                j += 1
            out.append(("dot", text[i:j].strip()))
            i = j
            at_line_start = True
            continue
        elif ch == ";":
            if buf.strip():
                out.append(("sql", buf.strip()))
            buf = ""
            at_line_start = True   # 分号之后算新语句起点，允许同行接 .tables
            i += 1
            continue
        elif ch == "\n":
            at_line_start = True
            buf += ch
            i += 1
            continue
        else:
            buf += ch
        if not ch.isspace():
            at_line_start = False
        i += 1
    if buf.strip():
        out.append(("sql", buf.strip()))
    return out


def do_dot(cur, line):
    parts = line.split()
    cmd, arg = parts[0], (parts[1] if len(parts) > 1 else None)
    if cmd in (".quit", ".exit"):
        raise SystemExit(0)
    if cmd == ".tables":
        cur.execute("select name from sqlite_master where type='table' order by 1")
        print("  ".join(r[0] for r in cur.fetchall()))
    elif cmd == ".schema":
        q = "select sql from sqlite_master where sql is not null"
        args = ()
        if arg:
            q += " and tbl_name=?"
            args = (arg,)
        cur.execute(q, args)
        for (s,) in cur.fetchall():
            print(s + ";")
    elif cmd == ".databases":
        cur.execute("pragma database_list")
        for r in cur.fetchall():
            print("|".join(str(x) for x in r))
    else:
        print(f"不支持 {cmd}，直接用 SQL", file=sys.stderr)


def do_sql(cur, stmt):
    cur.execute(stmt)
    if cur.description:
        rows = cur.fetchall()
        # PRAGMA 只打值，不打表头（PRAGMA key 会回一行 'ok'）
        if not stmt.lstrip().lower().startswith("pragma"):
            print("|".join(d[0] for d in cur.description))
        for row in rows:
            print("|".join("" if v is None else str(v) for v in row))
    elif cur.rowcount > 0:
        print(f"{cur.rowcount} 行受影响")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    first = sys.argv[1]
    if first in ("-version", "--version", "-v"):
        print("sqlcipher (sqlcipher3) sqlite " + sqlcipher3.sqlite_version)
        return 0
    if first in ("-h", "--help"):
        print(__doc__)
        return 0
    text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else sys.stdin.read()
    con = sqlcipher3.connect(sys.argv[1])
    cur = con.cursor()
    for kind, body in tokenize(text):
        try:
            if kind == "dot":
                do_dot(cur, body)
            else:
                do_sql(cur, body)
        except SystemExit:
            raise
        except Exception as e:
            msg = str(e)
            if "not a database" in msg or "encrypted" in msg:
                print("Error: 密码错或不是 SQLCipher 库（先 PRAGMA key='...'）",
                      file=sys.stderr)
            else:
                print(f"Error: {msg}", file=sys.stderr)
            return 1
    con.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
