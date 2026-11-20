#!/usr/bin/env python3
"""can-asc-summary.py <file.asc> [--id 3B4] [--window 1.0] [--top 20]

解析 Vector ASC 格式的 CAN 日志，输出「按报文 ID 的统计」，用来回答：
  - 哪条报文是异常注入的（频率/周期与其它 ID 明显不同）
  - 某条报文在什么时间点开始出现/消失
  - 碰撞时刻轮速信号何时归零
  - 某个 ID 的完整数据变化序列

ASC 是纯文本，一行一条报文：
    <时间戳秒> <通道> <ID(hex)> <Rx|Tx> d <DLC> <字节...>
所以不需要 python-can，stdlib 就够。

用法示例：
    can-asc-summary.py powertrain_can.asc              # 全量统计
    can-asc-summary.py powertrain_can.asc --id 3B4     # 只看某个 ID
    can-asc-summary.py powertrain_can.asc --window 1   # 按 1 秒窗口看速率
    can-asc-summary.py powertrain_can.asc --grep 0F    # 首字节变化的时刻
"""

from __future__ import annotations

import argparse
import re
import statistics as st
import sys
from collections import defaultdict

# 0.002665 1  050             Rx   d 8 3E 24 62 0B D0 94 DC 5F
LINE = re.compile(
    r"^\s*(?P<ts>\d+\.\d+)\s+(?P<ch>\d+)\s+(?P<mid>[0-9A-Fa-f]+)\s+"
    r"(?P<dir>Rx|Tx)\s+d\s+(?P<dlc>\d+)\s*(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)"
)


def parse(path: str):
    frames = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = LINE.match(line)
            if not m:
                continue
            data = bytes(int(b, 16) for b in m.group("data").split())
            frames.append((float(m.group("ts")), int(m.group("mid"), 16),
                           m.group("dir"), data))
    return frames


def fmt(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("asc")
    ap.add_argument("--id", help="只看这个 ID（hex，如 3B4）")
    ap.add_argument("--window", type=float, default=1.0, help="速率按多少秒统计")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--first-byte", action="store_true", help="按首字节变化列出时刻")
    a = ap.parse_args()

    frames = parse(a.asc)
    if not frames:
        print("没解析到报文，检查是不是 ASC 格式", file=sys.stderr)
        return 1

    t0, t1 = frames[0][0], frames[-1][0]
    print(f"总报文 {len(frames)} 条  时长 {t1 - t0:.3f}s  ({t0:.3f} → {t1:.3f})")

    per: dict[int, list[tuple[float, bytes]]] = defaultdict(list)
    for ts, mid, d, data in frames:
        per[mid].append((ts, data))

    only = int(a.id, 16) if a.id else None
    targets = {only: per[only]} if only and only in per else per

    print(f"\n{'ID':>6} {'条数':>7} {'占比':>6} {'平均周期':>9} {'周期抖动':>9} "
          f"{'速率/s':>8} {'方向':>4} 首末数据")
    print("-" * 96)
    rows = []
    for mid, items in targets.items():
        times = [t for t, _ in items]
        gaps = [b - a_ for a_, b in zip(times, times[1:])]
        period = st.mean(gaps) * 1000 if gaps else 0
        jitter = (st.stdev(gaps) * 1000) if len(gaps) > 1 else 0
        rate = len(items) / max(1e-9, (times[-1] - times[0])) if len(items) > 1 else 0
        dirs = {d for ts, mid_, d, _ in frames if mid_ == mid}
        rows.append((mid, len(items), period, jitter, rate, "/".join(sorted(dirs)),
                     items[0][1], items[-1][1]))
    rows.sort(key=lambda r: -r[1])
    for mid, n, period, jitter, rate, dirs, first, last in rows[: (999 if only else a.top)]:
        print(f"0x{mid:04X} {n:7} {n/len(frames)*100:5.1f}% {period:8.2f}ms {jitter:8.2f} "
              f"{rate:7.1f} {dirs:>4} {fmt(first)[:20]} → {fmt(last)[:20]}")

    # 周期性异常检测：正常报文周期很稳（抖动/周期小），注入报文往往抖动大或频率异常
    print("\n周期性可疑（抖动/周期 > 0.3，可能是人为注入或信号丢失）:")
    susp = [(mid, period, jitter) for mid, n, period, jitter, *_ in rows
            if period > 0 and jitter / period > 0.3 and n > 20]
    if not susp:
        print("  （无）")
    for mid, period, jitter in susp[:10]:
        print(f"  0x{mid:04X}  周期 {period:.1f}ms  抖动 {jitter:.1f}ms  "
              f"抖动比 {jitter/period:.2f}")

    # 速率突变：按窗口统计总量，找异常窗口（Q48「报文频率特征」常用）
    if a.window > 0:
        bins: dict[int, int] = defaultdict(int)
        for ts, *_ in frames:
            bins[int((ts - t0) / a.window)] += 1
        if bins:
            vals = list(bins.values())
            med = st.median(vals)
            hot = [(b * a.window, v) for b, v in sorted(bins.items())
                   if med and v > med * 2]
            print(f"\n按 {a.window}s 窗口的总速率：中位 {med:.0f} 帧/窗口，"
                  f"最长 {max(vals)}")
            if hot:
                print("  速率突然翻倍的窗口（前 10）:")
                for t, v in hot[:10]:
                    print(f"    t={t:7.2f}s  {v} 帧  （中位的 {v/med:.1f} 倍）")

    # 某个 ID 的首字节变化（找状态切换、归零、异常转向指令）
    if only and only in per and a.first_byte:
        print(f"\n0x{only:04X} 首字节变化点:")
        prev = None
        for ts, data in per[only]:
            if not data:
                continue
            if prev is None or data[0] != prev:
                print(f"  t={ts:9.3f}s  首字节 {data[0]:02X}  全帧 {fmt(data)}")
                prev = data[0]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
