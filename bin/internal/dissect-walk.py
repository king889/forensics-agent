"""用 dissect 一次打开目标，走完所有目录，生成文件清单。

为什么要单独写：
    `target-fs walk <dir>` 每次调用都会重开镜像并重解析 LVM。
    pve 的服务器镜像有 8 个分区 + LVM，一次调用 6 秒；
    9 个目录 × 3 台服务器 = 27 次 × 6 秒 = 近 3 分钟纯重复解析。

    这个脚本只打开一次，遍历所有挂载点，输出和 fls -r -p 兼容的行格式：
        r/r <inode或路径哈希>:	<绝对路径>
    （dissect 不给 inode，所以用路径本身当标识，rg 检索用途一致）

用法（必须用带 dissect 的解释器）：
    tools/venv-win/bin/python3 bin/internal/dissect-walk.py <镜像> <输出文件>
"""

from __future__ import annotations

import sys
from pathlib import Path

SKIP_TOP = {"/proc", "/sys", "/dev", "/run"}


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: dissect-walk.py <镜像> <输出文件>", file=sys.stderr)
        return 2
    img, out = sys.argv[1], Path(sys.argv[2])

    from dissect.target import Target

    target = Target.open(img)
    roots = []
    for fs in target.filesystems:
        try:
            roots.append((fs, fs.path("/")))
        except Exception:
            continue
    if not roots:
        print("没有可用的文件系统", file=sys.stderr)
        return 1

    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for fs, root in roots:
            stack = [root]
            seen = 0
            while stack:
                d = stack.pop()
                try:
                    entries = list(d.iterdir())
                except (PermissionError, OSError):
                    continue
                for e in entries:
                    p = str(e)
                    if any(p == s or p.startswith(s + "/") for s in SKIP_TOP):
                        continue
                    try:
                        is_dir = e.is_dir()
                        size = 0 if is_dir else e.stat().st_size
                    except (OSError, ValueError):
                        is_dir, size = False, 0
                    kind = "d/d" if is_dir else "r/r"
                    fh.write(f"{kind} {p}:\t{p}\t{size}\n")
                    n += 1
                    seen += 1
                    if is_dir:
                        stack.append(e)
                if seen > 3_000_000:      # 防跑飞
                    break
    print(f"{n} 行 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
