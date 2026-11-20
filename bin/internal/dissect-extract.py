"""批量提取：**一次打开镜像，取 N 个文件**。

为什么要它：
    实测最贵的浪费之一是逐 inode 循环：
        while read ino; do icat -o 2048 img $ino > out; done
    每个 icat 都要重新打开 E01、重新解压 EWF 分块，45 次循环浪费 15 分钟。

    这个脚本打开一次，按路径匹配批量取出。

用法（必须用带 dissect 的解释器）：
    tools/venv-win/bin/python3 dissect-extract.py <镜像或目录> <输出目录> [--grep 正则] [--inode 列表]
        或 --paths 文件（每行一个绝对路径）

输出：保持原目录结构，写出的每个文件打印一行 `路径<TAB>字节数`
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path


def from_directory(src: Path, out: Path, pattern: re.Pattern | None, limit: int) -> int:
    n = 0
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if pattern and not pattern.search(str(rel)):
            continue
        # 去掉盘符前缀，避免输出被拆成 c:/ 这样的结构
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, dst)
            print(f"{rel}\t{dst.stat().st_size}")
            n += 1
        except OSError as exc:
            print(f"! {rel}: {exc}", file=sys.stderr)
        if limit and n >= limit:
            break
    return n


def from_image(src: Path, out: Path, pattern: re.Pattern | None,
               paths: list[str], limit: int) -> int:
    from dissect.target import Target

    target = Target.open(str(src))
    n = 0
    roots = []
    for fs in target.filesystems:
        try:
            roots.append((fs, fs.path("/")))
        except Exception:
            continue

    if paths:
        # 按给定路径取（最省时：不做全盘遍历）
        for raw in paths:
            cand = raw.replace("\\", "/")
            got = False
            for fs, _ in roots:
                for form in (cand, "/" + cand.lstrip("/")):
                    try:
                        f = fs.path(form)
                        if f.is_file():
                            data = f.open().read()
                            rel = form.lstrip("/")
                            dst = out / rel
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            dst.write_bytes(data)
                            print(f"{rel}\t{len(data)}")
                            n += 1
                            got = True
                            break
                    except (OSError, ValueError):
                        continue
                if got:
                    break
            if got and limit and n >= limit:
                break
        return n

    for fs, root in roots:
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                entries = list(d.iterdir())
            except (PermissionError, OSError):
                continue
            for e in entries:
                p = str(e)
                try:
                    if e.is_dir():
                        stack.append(e)
                        continue
                    rel = p.lstrip("/")
                    if pattern and not pattern.search(rel):
                        continue
                    data = e.open().read()
                    dst = out / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(data)
                    print(f"{rel}\t{len(data)}")
                    n += 1
                except (OSError, ValueError, PermissionError):
                    continue
                if limit and n >= limit:
                    return n
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="批量提取（一次打开镜像）")
    ap.add_argument("source")
    ap.add_argument("outdir")
    ap.add_argument("--grep", help="只取路径匹配该正则的文件")
    ap.add_argument("--paths", help="文件：每行一个要取的绝对路径")
    ap.add_argument("--limit", type=int, default=200, help="最多取多少个，默认 200")
    a = ap.parse_args()

    src = Path(a.source)
    if not src.exists():
        print(f"找不到检材: {src}", file=sys.stderr)
        return 2
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(a.grep, re.I) if a.grep else None
    paths = []
    if a.paths:
        pf = Path(a.paths)
        if pf.is_file():
            paths = [l.strip() for l in pf.read_text(encoding="utf-8", errors="replace").splitlines()
                     if l.strip()]

    if src.is_dir():
        n = from_directory(src, out, pattern, a.limit)
    else:
        try:
            n = from_image(src, out, pattern, paths, a.limit)
        except ImportError:
            print("需要 dissect：tools/venv-win/bin/python3 -m pip install dissect.target",
                  file=sys.stderr)
            return 3
    print(f"\n共提取 {n} 个文件 → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
