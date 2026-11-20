#!/usr/bin/env python3
"""E01/EWF 读写，用 pyewf（随 plaso 装的），不需要 ewf-tools。

    ewf.py info    <disk.E01>
    ewf.py export  <disk.E01> <out.raw> [--size 字节] [--offset 字节]
    ewf.py verify  <disk.E01>

分卷（E01/E02/...）会自动用 pyewf.glob 拼起来。
注意：export 整盘 32GB 要跑十几分钟，TSK（mmls/fls/icat）本来就能直接读 E01，
大多数情况下不需要导出。
"""

import argparse
import hashlib
import os
import sys

try:
    import pyewf
except ImportError:
    sys.exit("pyewf 没装：tools/install.sh plaso")


def open_ewf(path):
    if not os.path.exists(path):
        sys.exit(f"文件不存在: {path}")
    names = pyewf.glob(path)
    if not names:
        sys.exit(f"不是 EWF 或分卷不全: {path}")
    handle = pyewf.handle()
    handle.open(names)
    return handle, names


def human(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024


def cmd_info(args):
    handle, names = open_ewf(args.image)
    size = handle.media_size
    print(f"文件      : {args.image}")
    print(f"分卷      : {len(names)} 个")
    if len(names) > 1:
        for n in names:
            print(f"            {os.path.basename(n)} ({human(os.path.getsize(n))})")
    print(f"媒体大小  : {size} 字节 ({human(size)})")
    print(f"扇区大小  : {handle.bytes_per_sector} 字节")
    print(f"扇区数    : {size // max(handle.bytes_per_sector, 1)}")
    print()
    print("头部信息")
    for k, v in sorted(handle.get_header_values().items()):
        print(f"  {k:<28} {v}")
    hashes = handle.get_hash_values()
    if hashes:
        print()
        print("存储的哈希")
        for k, v in sorted(hashes.items()):
            print(f"  {k:<28} {v}")
    handle.close()


def cmd_export(args):
    handle, _ = open_ewf(args.image)
    total = handle.media_size
    offset = args.offset or 0
    length = args.size or (total - offset)
    if offset + length > total:
        sys.exit(f"范围超出：offset+size > {total}")
    if not args.yes and length > 2 * 1024**3:
        sys.exit(f"要导出 {human(length)}，加 -y 确认（或改用 mmls/fls 直接读 E01）")
    handle.seek(offset)
    done = 0
    chunk = 4 * 1024 * 1024
    with open(args.output, "wb") as fh:
        while done < length:
            n = min(chunk, length - done)
            buf = handle.read_buffer(n)
            if not buf:
                break
            fh.write(buf)
            done += len(buf)
            if sys.stderr.isatty():
                pct = done * 100 // length
                sys.stderr.write(f"\r{done * 100 // length:3d}%  {human(done)}")
                sys.stderr.flush()
    handle.close()
    if sys.stderr.isatty():
        sys.stderr.write("\n")
    print(f"导出完成: {args.output} ({done} 字节)")


def cmd_verify(args):
    handle, _ = open_ewf(args.image)
    total = handle.media_size
    stored = {k.lower(): v for k, v in handle.get_hash_values().items()}
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    handle.seek(0)
    done = 0
    chunk = 8 * 1024 * 1024
    while done < total:
        buf = handle.read_buffer(min(chunk, total - done))
        if not buf:
            break
        md5.update(buf)
        sha1.update(buf)
        done += len(buf)
    handle.close()
    got = {"md5": md5.hexdigest(), "sha1": sha1.hexdigest()}
    print(f"读取 {done} 字节")
    rc = 0
    for algo in ("md5", "sha1"):
        print(f"  {algo:<5} {got[algo]}")
        if algo in stored:
            same = stored[algo].lower() == got[algo]
            print(f"        {'与镜像内记录一致' if same else '不一致！'}（记录值 {stored[algo]}）")
            if not same:
                rc = 1
    if not stored:
        print("  镜像里没有存哈希，无法比对")
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="元数据 + 大小")
    p.add_argument("image")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("export", help="导出成 raw")
    p.add_argument("image")
    p.add_argument("output")
    p.add_argument("--size", type=int, help="导出多少字节（默认全部）")
    p.add_argument("--offset", type=int, help="从哪开始（默认 0）")
    p.add_argument("-y", "--yes", action="store_true", help="超过 2G 也直接导")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("verify", help="重算 md5/sha1")
    p.add_argument("image")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
