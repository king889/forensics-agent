#!/usr/bin/env python3
"""image-jigsaw.py <碎片目录> [-o out.png] [--grid WxH]

把被打乱的图片碎片按**边缘匹配**重排成原图。用于 CTF 里「密码藏在拼图里」这类题。

原理：
    相邻两块在接触边上像素几乎相同，所以
      hcost[i][j] = || 第 i 块的右边缘 - 第 j 块的左边缘 ||
      vcost[i][j] = || 第 i 块的下边缘 - 第 j 块的左/上边缘 ||
    用 Kruskal 式的贪心合并链：每次取全局最小代价的一对，把两条链接起来
    （只允许接在链两端、不允许成环），最后得到若干行，再按 vcost 把行叠起来。

为什么不用文件名顺序：
    实测该题的 patch_000..patch_499 是**打乱命名**的，按序号拼出来是乱码。

用法：
    image-jigsaw.py /tmp/patches -o /tmp/out.png
    image-jigsaw.py /tmp/patches --grid 20x25     # 已知行列时更准
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load_tiles(files: list[Path]) -> tuple[np.ndarray, int, int]:
    imgs = []
    for f in files:
        im = Image.open(f).convert("RGB")
        imgs.append(np.asarray(im, dtype=np.int16))
    h = min(a.shape[0] for a in imgs)
    w = min(a.shape[1] for a in imgs)
    imgs = [a[:h, :w] for a in imgs]
    return np.stack(imgs), h, w


def edge_cost(tiles: np.ndarray, axis: str) -> np.ndarray:
    """返回 (n,n) 代价矩阵：axis='h' 表示 i 的右边接 j 的左边。"""
    n = tiles.shape[0]
    if axis == "h":
        right = tiles[:, :, -1, :].astype(np.float32)   # (n,h,3)
        left = tiles[:, :, 0, :].astype(np.float32)
        d = right[:, None, :, :] - left[None, :, :, :]  # (n,n,h,3)
    else:
        bottom = tiles[:, -1, :, :].astype(np.float32)  # (n,w,3)
        top = tiles[:, 0, :, :].astype(np.float32)
        d = bottom[:, None, :, :] - top[None, :, :, :]
    return np.abs(d).sum(axis=(2, 3))


def build_rows(hcost: np.ndarray, vcost: np.ndarray, n: int) -> tuple[list[list[int]], list[list[int]]]:
    """逐行重建：先找"行首"（左匹配最差的块），再沿最优右邻贪心延伸。

    实测这批碎片有强边缘连续性（最优右邻代价只有随机配对的 5%），
    所以不需要复杂算法，关键是**先确定行首** —— 行首块的左边没有邻居，
    它的 best-left 代价会明显偏高。
    """
    H = hcost.copy()
    np.fill_diagonal(H, 1e12)
    best_left = H.min(axis=0)              # 每个块向左找邻居的最小代价
    order = np.argsort(-best_left)          # 左匹配最差的排前面 → 优先当行首

    used = np.zeros(n, dtype=bool)
    rows: list[list[int]] = []
    for start in order:
        start = int(start)
        if used[start]:
            continue
        row = [start]; used[start] = True
        while True:
            cur = row[-1]
            cand = H[cur].copy()
            cand[used] = 1e12
            nxt = int(cand.argmin())
            if cand[nxt] >= 1e12 or cand[nxt] > best_left.mean() * 3:
                break
            row.append(nxt); used[nxt] = True
        if len(row) >= 2:
            rows.append(row)

    # 剩下的散块（没被任何行接纳）收进单独行
    for i in range(n):
        if not used[i]:
            rows.append([int(i)])
    return rows, rows



def build_2d(hcost: np.ndarray, vcost: np.ndarray, n: int) -> dict[tuple[int, int], int]:
    """二维生长：从一块开始，按四个方向的最优邻居逐步把碎片摆到画布上。

    为什么不能按行拼：这批 500 块里有 273 块是纯白背景，剩下的 227 块
    组成的是一个**不规则的彩色区域**，不是满矩形。按行拼会出现
    54/37/23 这种不一致的行长。
    """
    H = hcost.copy(); np.fill_diagonal(H, 1e12)      # i 右接 j
    HL = H.T.copy()                                  # i 左接 j
    V = vcost.copy(); np.fill_diagonal(V, 1e12)      # i 下接 j
    VU = V.T.copy()                                  # i 上接 j
    thr = float(np.median(H)) * 0.6

    # 种子：取"四周都很难接"的块？反而应从最独特的块开始：选 best-neighbor 代价最小的
    seed = int(H.min(axis=1).argmin())
    grid: dict[tuple[int, int], int] = {(0, 0): seed}
    used = {seed}
    frontier = [(0, 0)]
    DIRS = [((1, 0), H), ((-1, 0), HL), ((0, 1), V), ((0, -1), VU)]
    guard = 0
    while frontier and guard < n * 8:
        guard += 1
        nxt_frontier = []
        for (x, y) in frontier:
            cur = grid[(x, y)]
            for (dx, dy), M in DIRS:
                pos = (x + dx, y + dy)
                if pos in grid:
                    continue
                cand = M[cur].copy()
                for u in used:
                    cand[u] = 1e12
                j = int(cand.argmin())
                if cand[j] > thr:
                    continue
                grid[pos] = j; used.add(j); nxt_frontier.append(pos)
        frontier = nxt_frontier
    return grid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("-o", "--out", default="jigsaw.png")
    ap.add_argument("--grid", help="已知网格，如 20x25（宽x高）")
    ap.add_argument("--pattern", default=r"\.(png|jpg|jpeg)$")
    a = ap.parse_args()

    d = Path(a.dir)
    files = sorted(p for p in d.rglob("*") if p.is_file() and re.search(a.pattern, p.name, re.I))
    if not files:
        print(f"{d} 下没有图片", file=sys.stderr)
        return 2
    print(f"碎片 {len(files)} 张", file=sys.stderr)

    tiles, h, w = load_tiles(files)
    # 纯白块是背景，参与匹配会污染代价矩阵（0 代价到处匹配），先剔除
    keep = []
    for ti in range(tiles.shape[0]):
        tile = tiles[ti]
        if tile.std() < 1.0 and tile.mean() > 250:
            continue
        keep.append(ti)
    blank_n = tiles.shape[0] - len(keep)
    if blank_n:
        print(f"剔除纯白背景块 {blank_n}，参与拼图 {len(keep)}", file=sys.stderr)
        tiles = tiles[keep]
    print(f"单块 {w}x{h}", file=sys.stderr)
    hcost = edge_cost(tiles, "h")
    vcost = edge_cost(tiles, "v")
    grid = build_2d(hcost, vcost, tiles.shape[0])
    if grid:
        xs = [p[0] for p in grid]; ys = [p[1] for p in grid]
        W = max(xs) - min(xs) + 1; Hh = max(ys) - min(ys) + 1
        print(f"二维生长：摆了 {len(grid)} 块，画布 {W}x{Hh}", file=sys.stderr)
        canvas = Image.new("RGB", (W * w, Hh * h), (255, 255, 255))
        for (x, y), idx in grid.items():
            canvas.paste(Image.fromarray(tiles[idx].astype(np.uint8)),
                         ((x - min(xs)) * w, (y - min(ys)) * h))
        canvas.save(a.out)
        print(f"→ {a.out}  {canvas.size}", file=sys.stderr)
        return 0
    rows, _ = build_rows(hcost, vcost, tiles.shape[0])
    lens = [len(r) for r in rows]
    print(f"合并出 {len(rows)} 行，行长度分布: "
          f"{sorted(set(lens), reverse=True)[:6]}", file=sys.stderr)

    # 只保留最长的若干行、且行长度一致
    width = None
    if a.grid:
        width = int(a.grid.lower().split("x")[0])
    else:
        from collections import Counter
        cnt = Counter(lens)
        width = cnt.most_common(1)[0][0]
    rows = [r for r in rows if len(r) == width]
    print(f"采用 {len(rows)} 行 × {width} 列", file=sys.stderr)

    if not rows:
        print("没有可用的行，拼图失败", file=sys.stderr)
        return 1

    ordered = [rows[0]]
    rest = rows[1:]
    while rest:
        last = ordered[-1][0]
        best = min(rest, key=lambda r: vcost[last][r[0]])
        ordered.append(best)
        rest.remove(best)

    out = Image.new("RGB", (width * w, len(ordered) * h), (255, 255, 255))
    for r, row in enumerate(ordered):
        for c, idx in enumerate(row):
            out.paste(Image.fromarray(tiles[idx].astype(np.uint8)), (c * w, r * h))
    out.save(a.out)
    print(f"→ {a.out}  {out.size}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
