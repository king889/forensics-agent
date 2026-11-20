#!/usr/bin/env python3
"""find-sqlite.py <镜像> [--out dir] [--min 4096]
从无文件系统的原始镜像里按签名 carve SQLite 库（手表/固件/NAND dump 用）。
先只报偏移，加 --out 才真正导出。
"""
import argparse, os, sys
MAGIC=b'SQLite format 3\x00'
ap=argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("--out"); ap.add_argument("--min", type=int, default=4096)
ap.add_argument("--max-hits", type=int, default=200)
a=ap.parse_args()
hits=[]; off=0; tail=b''
with open(a.src,'rb') as fh:
    while True:
        blk=fh.read(32*1024*1024)
        if not blk: break
        buf=tail+blk; i=0
        while True:
            i=buf.find(MAGIC,i)
            if i<0: break
            hits.append(off-len(tail)+i); i+=1
        off+=len(blk); tail=buf[-16:]
        if len(hits)>=a.max_hits: break
print(f"命中 {len(hits)} 处", file=sys.stderr)
for h in hits: print(h)
if a.out and hits:
    os.makedirs(a.out, exist_ok=True)
    with open(a.src,'rb') as fh:
        for n,h in enumerate(hits):
            fh.seek(h); d=fh.read(64*1024*1024)
            # 用 page size 估长度
            try: ps=int.from_bytes(d[16:18],'big') or 4096
            except Exception: ps=4096
            p=os.path.join(a.out, f"sqlite_{n:03d}_{h}.db")
            open(p,'wb').write(d)
            print(f"  -> {p}", file=sys.stderr)
