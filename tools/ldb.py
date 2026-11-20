#!/usr/bin/env python3
"""LevelDB 取证读取器 —— 直接解析 .ldb / .log / MANIFEST，不依赖 leveldb 库。

能读 Chrome/Edge/Android 的 LevelDB，包括：
  - 已被删除但仍残留在 .ldb 里的记录（KeyState.Deleted）
  - .log（WAL）里还没落盘的最新写入
  - snappy 压缩块（纯 Python 实现，不需要编译）
  - 每条记录来自哪个文件、字节偏移

用法:
  ldb-dump <目录>                       # 全部记录（含删除）
  ldb-dump <目录> --live                # 只要活着的
  ldb-dump <目录> --deleted             # 只要删除的（恢复 flag 用）
  ldb-dump <目录> --grep flag -i        # 键或值里含 flag
  ldb-dump <目录> --json > out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from ccl_chromium_reader.storage_formats import ccl_leveldb
except ImportError:
    sys.exit("缺少 ccl_chromium_reader：uv pip install "
             "'ccl_chromium_reader @ git+https://github.com/cclgroupltd/ccl_chromium_reader.git'")


def show(b: bytes) -> str:
    """可打印就原样输出，否则用 \\xNN 转义。"""
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        s = b.decode("utf-8", errors="backslashreplace")
    return "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in s)


def main() -> int:
    ap = argparse.ArgumentParser(description="读 LevelDB（含删除记录、WAL、snappy）")
    ap.add_argument("path", help="LevelDB 目录")
    ap.add_argument("--live", action="store_true", help="只要活着的记录")
    ap.add_argument("--deleted", action="store_true", help="只要已删除的记录")
    ap.add_argument("--grep", metavar="PAT", help="键或值包含该字符串（不区分大小写）")
    ap.add_argument("--limit", type=int, default=0, help="最多输出 N 条")
    ap.add_argument("--json", action="store_true", help="输出 JSON Lines")
    ap.add_argument("-q", "--quiet", action="store_true", help="不打印表头")
    a = ap.parse_args()

    d = Path(a.path)
    if not d.is_dir():
        sys.exit(f"不是目录: {d}")

    db = ccl_leveldb.RawLevelDb(d)
    pat = a.grep.lower() if a.grep else None

    live = deleted = 0
    shown = 0
    if not a.json and not a.quiet:
        print("state\tseq\tfile\tkey\tvalue", file=sys.stderr)

    for r in db.iterate_records_raw():
        is_del = r.state == ccl_leveldb.KeyState.Deleted
        if a.live and is_del:
            continue
        if a.deleted and not is_del:
            continue

        k, v = show(r.key), show(r.value or b"")
        if pat and pat not in k.lower() and pat not in v.lower():
            continue

        if is_del:
            deleted += 1
        else:
            live += 1

        if a.json:
            print(json.dumps({
                "state": "deleted" if is_del else "live",
                "seq": r.seq,
                "file": str(r.origin_file),
                "offset": r.offset,
                "compressed": r.was_compressed,
                "key": k,
                "value": v,
            }, ensure_ascii=False))
        else:
            print(f"{'DEL' if is_del else 'OK'}\t{r.seq}\t{Path(r.origin_file).name}\t{k}\t{v}")

        shown += 1
        if a.limit and shown >= a.limit:
            print(f"--- 已到上限 {a.limit} ---", file=sys.stderr)
            break

    db.close()
    if not a.json:
        print(f"--- 共 {shown} 条（活 {live} / 删 {deleted}）---", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
