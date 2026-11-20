#!/usr/bin/env python3
"""xor-decrypt.py <输入> <输出|-> --key <key> [--hex] [--repeat]
key 可以是文本或 --hex 指定的十六进制。repeat 表示循环使用 key（默认循环）。
"""
import argparse, sys
ap=argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--key", required=True)
ap.add_argument("--hex", action="store_true")
ap.add_argument("--no-repeat", action="store_true")
a=ap.parse_args()
k=bytes.fromhex(a.key) if a.hex else a.key.encode()
if not k: sys.exit("空 key")
d=open(a.src,'rb').read()
if a.no_repeat:
    out=bytes(b ^ k[i] for i,b in enumerate(d) if i < len(k)) + d[len(k):]
else:
    out=bytes(b ^ k[i%len(k)] for i,b in enumerate(d))
if a.dst=='-': sys.stdout.buffer.write(out)
else: open(a.dst,'wb').write(out); print(f"{len(out)} 字节 -> {a.dst}")
