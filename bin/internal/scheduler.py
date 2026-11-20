#!/usr/bin/env python3
"""主调度器：按题组派活给 worker，盯着它们跑，卡住就喊人。

    fcase go                 # 4 并发，把 ready 的组全做完
    fcase go --jobs 6        # 6 并发
    fcase go --dry-run       # 只打印会派什么活
    fcase go --max-groups 3  # 只做 3 个组
    fcase go --model glm-5.3

和 solve-par 的区别：
    solve-par 按「题」抢，谁空谁拿下一题 —— 同一组的题会被拆散到不同 worker，
    共享的中间产物（解出来的容器、数据库副本）无法复用。
    scheduler 按「组」派，一组一个 worker 顺序做完，产物落在
    artifacts/<检材>/<组号>/，组内题共享。

职责边界：
    - 派活、盯进度、写 agents 表心跳
    - 失败/超时 → 记 attempts、写 blocked.md、继续下一题（不卡死整组）
    - 不亲自查证据
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # bin/internal/ -> 仓库根
BIN = ROOT / "bin"
POLL_SEC = 5


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmmss() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Case:
    def __init__(self) -> None:
        p = Path.cwd().resolve()
        for d in (p, *p.parents):
            if (d / "meta" / "evidence.db").is_file():
                self.root = d
                break
        else:
            sys.exit("scheduler: 当前目录不是 case（找不到 meta/evidence.db）")
        self.meta = self.root / "meta"
        self.arts = self.root / "artifacts"
        self.arts.mkdir(exist_ok=True)
        self.db_path = self.meta / "evidence.db"

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def q(self, sql: str, args=()) -> list:
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

    def x(self, sql: str, args=()) -> None:
        with self.conn() as c:
            c.execute(sql, args)
            c.commit()


API_MARKERS = ("insufficient", "quota", "billing", "api key", "get_channel_failed",
               "402", "401", "403", "429", "rate limit", "unauthorized", "forbidden")


def log_reason(path, width: int = 140) -> str:
    """从日志尾部捞一条能说明失败原因的行（API 报错优先）。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    tail = [l.strip() for l in lines[-40:] if l.strip()]
    for l in reversed(tail):
        if any(m in l.lower() for m in API_MARKERS):
            return l[:width]
    for l in reversed(tail):
        low = l.lower()
        if any(k in low for k in ("error", "failed", "timeout", "超时", "失败", "无法")):
            return l[:width]
    return ""


class Scheduler:
    def __init__(self, c: Case, jobs: int, model: str | None, timeout: int,
                 max_groups: int, dry: bool, redo: bool = False,
                 solve_cmd: str | None = None, batch: int = 1,
                 provider: str | None = None, thinking: str | None = None,
                 wait_unpack: int = 1800) -> None:
        self.c = c
        self.provider = provider
        self.thinking = thinking
        self.wait_unpack = wait_unpack      # 等检材解包最长多久（秒）
        self._wait_since: float | None = None
        self.batch = max(1, batch)
        self.redo = redo
        self.solve_cmd = solve_cmd or str(BIN / "solve")
        self.jobs = jobs
        self.model = model
        self.timeout = timeout
        self.max_groups = max_groups
        self.dry = dry
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.blocked: list[str] = []
        self._n_agent = 0
        self.dispatched: set[str] = set()   # 本次运行已经派过的组，不重复派
        self._waiting: dict[str, str] = {}  # 等检材就绪的组：组 id -> 原因

    # ---------------------------------------------------------------- 组

    def groups(self) -> list[dict]:
        rows = self.c.q("SELECT * FROM groups ORDER BY id")
        out = []
        for r in rows:
            out.append({"id": r["id"], "name": r["name"], "artifact": r["artifact"],
                        "qids": [q for q in (r["qids"] or "").split(",") if q],
                        "depends": [d for d in (r["depends"] or "").split(",") if d],
                        "est": r["est_min"] or 30, "status": r["status"] or "todo"})
        return out

    def ready(self, gs: list[dict]) -> list[dict]:
        """依赖都完成的组；先易后难。"""
        done = {g["id"] for g in gs if g["status"] == "done"}
        todo = [g for g in gs if g["status"] in ("todo", "doing")]
        ok = [g for g in todo if all(d in done for d in g["depends"])]
        return sorted(ok, key=lambda g: (g["est"], g["id"]))

    # ---------------------------------------------------------------- 组内

    def ready_to_run(self, g: dict) -> tuple[bool, str]:
        """检材准备好了吗？没解包/没索引的组先跳过，等它好了下一轮再派。

        这样解包和做题可以重叠：小检材 2 秒就绪立刻开工，
        大检材（Com-01 84G）在后台解，解好自动接上。
        """
        art = g["artifact"]
        if not art:
            return True, ""
        stem = Path(art).stem
        base = self.c.root
        for d in (base / "work" / "unpack" / stem, base / "work" / stem):
            if (d / ".unpacked").is_file():
                return True, ""
        # 不是压缩包（pcap / 单个小文件）就不用等
        if not (base / "evi" / art).name.lower().endswith((".zip", ".7z", ".rar")):
            return True, ""
        return False, f"{stem} 还没解包"

    def group_dir(self, g: dict) -> Path:
        d = self.c.arts / Path(g["artifact"]).stem / g["id"]
        (d / "logs").mkdir(parents=True, exist_ok=True)
        return d

    def answered(self, qid: str) -> bool:
        return bool(self.c.q("SELECT 1 FROM answers WHERE qid=? LIMIT 1", (qid,)))

    def attempt_no(self, qid: str) -> int:
        r = self.c.q("SELECT COALESCE(MAX(attempt),0) FROM attempts WHERE qid=?", (qid,))
        return (r[0][0] if r else 0) + 1

    def run_batch(self, g: dict, qids: list[str], agent: str) -> dict[str, str]:
        """跑一小批题（同组连续题共享一个会话）。返回 {qid: status}。"""
        todo = [q for q in qids if self.redo or not self.answered(q)]
        if not todo:
            return {q: "skipped" for q in qids}

        tag = todo[0] if len(todo) == 1 else f"{todo[0]}-{todo[-1]}"
        log = self.group_dir(g) / "logs" / f"{tag}.log"
        args = ["bash", self.solve_cmd]
        if self.provider:
            args += ["--provider", self.provider]
        if self.model:
            args += ["--model", self.model]
        if self.thinking:
            args += ["--thinking", self.thinking]
        args += todo
        started = now()
        atts = {q: self.attempt_no(q) for q in todo}
        # 一批题共用一个会话，超时按题数放大
        tmo = self.timeout * len(todo) if len(todo) > 1 else self.timeout
        status = "failed"
        env = dict(os.environ, FCASE_AGENT=agent, FCASE_QID=todo[0])
        try:
            with log.open("wb") as fh:
                subprocess.run(args, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=tmo, cwd=self.c.root, env=env)
        except subprocess.TimeoutExpired:
            status = "timeout"
        except OSError as exc:
            log.write_text(f"启动失败: {exc}\n", encoding="utf-8")

        out: dict[str, str] = {q: "skipped" for q in qids if q not in todo}
        for q in todo:
            ok = self.answered(q)
            st = "solved" if ok else status
            out[q] = st
            self.c.x("INSERT INTO attempts (qid,attempt,model,started,ended,status,session,note) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (q, atts[q], self.model or "默认", started, now(), st, str(log), g["id"]))
        return out

    def worker(self, g: dict) -> None:
        with self.lock:
            self._n_agent += 1
            agent = f"A{self._n_agent}"
        self.c.x("INSERT OR REPLACE INTO agents (id,grp,model,status,current_qid,q_started,pid,session,started,last_seen,note) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (agent, g["id"], self.model or "默认", "running", "", now(), os.getpid(),
                  "", now(), now(), ""))
        self.c.x("UPDATE groups SET status='doing' WHERE id=?", (g["id"],))
        print(f"{hhmmss()} {agent} ▶ {g['id']} {g['name']}（{len(g['qids'])} 题）", flush=True)

        fails = []
        qs = g["qids"]
        chunks = [qs[i:i + self.batch] for i in range(0, len(qs), self.batch)]
        for chunk in chunks:
            if self.stop.is_set():
                break
            head = chunk[0]
            # 派活前自动跑 probe：把极值/计数/原文类题的候选表先算好塞进简报，
            # 这类题的错法是「看到第一个像样的候选就停」，提示词管不住，只能预计算。
            try:
                subprocess.run(["bash", str(BIN / "fcase"), "probe", *chunk],
                               cwd=self.c.root, capture_output=True, timeout=600)
                subprocess.run(["bash", str(BIN / "fcase"), "brief", *chunk],
                               cwd=self.c.root, capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError):
                pass
            self.c.x("UPDATE agents SET current_qid=?, q_started=?, last_seen=? WHERE id=?",
                     (head, now(), now(), agent))
            for q in chunk:
                self.c.x("UPDATE questions SET status='doing' WHERE id=? AND status!='done'", (q,))
            res = self.run_batch(g, chunk, agent)
            for qid in chunk:
                st = res.get(qid, "failed")
                if st == "skipped":
                    continue
                if st == "solved":
                    print(f"{hhmmss()} {agent}   ✓ {qid}", flush=True)
                else:
                    fails.append((qid, st))
                    print(f"{hhmmss()} {agent}   ✗ {qid} ({st}) → 记 blocked", flush=True)
                    with self.lock:
                        rel = (self.group_dir(g) / "logs").relative_to(self.c.root)
                        why = log_reason(self.group_dir(g) / "logs" / f"{qid}.log")
                        self.blocked.append(
                            f"- [ ] **{qid}**（{g['id']} {g['name']}）{st} —— "
                            f"日志 `{rel}/`" + (f"\n      `{why}`" if why else ""))
                    self.c.x("UPDATE questions SET status='blocked' WHERE id=? AND status!='done'", (qid,))

        done = all(self.answered(q) for q in g["qids"])
        self.c.x("UPDATE groups SET status=? WHERE id=?", ("done" if done else "todo", g["id"]))
        self.c.x("UPDATE agents SET status=?, last_seen=?, current_qid='' WHERE id=?",
                 ("done" if done else "dead", now(), agent))
        left = len(g["qids"]) - len(fails)
        print(f"{hhmmss()} {agent} ■ {g['id']} 结束：成 {left} 败 {len(fails)}"
              f"{'' if done else '（组未完成，下次重试）'}", flush=True)

    # ---------------------------------------------------------------- 主循环

    def run(self) -> int:
        gs = self.groups()
        if not gs:
            sys.exit("没有题组。先 fcase plan（让 agent 分类）或 fcase plan --auto")

        if self.dry:
            print(f"共 {len(gs)} 组，jobs={self.jobs}，模型={self.model or '默认'}，超时={self.timeout}s\n")
            for g in self.ready(gs)[: self.max_groups or None]:
                dep = f"  依赖 {','.join(g['depends'])}" if g["depends"] else ""
                print(f"  {g['id']:4} {g['artifact'][:24]:24} {g['qids'][0]}–{g['qids'][-1]:4} "
                      f"{len(g['qids']):2}题 ~{g['est']}min  {g['name']}{dep}")
            return 0

        pending = self.ready(gs)
        if self.max_groups:
            pending = pending[: self.max_groups]
        if not pending:
            print("没有可派发的组（依赖未满足或全部完成）")
            return 0

        self.answer_base = self.c.q("SELECT COALESCE(MAX(id),0) FROM answers")[0][0]
        tag = "/".join(x for x in (self.provider, self.model) if x) or "默认"
        print(f"{hhmmss()} 调度启动：{len(pending)} 组，jobs={self.jobs}，"
              f"模型={tag}，thinking={self.thinking or '默认'}，单题超时={self.timeout}s",
              flush=True)

        active: list[threading.Thread] = []
        deferred: list[dict] = []          # 检材还没解好的组
        started = time.time()
        try:
            while pending or deferred or any(t.is_alive() for t in active):
                active = [t for t in active if t.is_alive()]

                # 等检材就绪的组：每轮重新检查一次，好了就放回 pending
                if deferred:
                    still = []
                    for g in deferred:
                        ok, _ = self.ready_to_run(g)
                        if ok:
                            print(f"{hhmmss()} ▶ {g['id']} 检材就绪，入队", flush=True)
                            pending.append(g)
                        else:
                            still.append(g)
                    deferred = still

                while pending and len(active) < self.jobs and not self.stop.is_set():
                    g = pending.pop(0)
                    ok, why = self.ready_to_run(g)
                    if not ok:
                        # 不派、也不算失败；放回等待队列，下一轮再看
                        if g["id"] not in self._waiting:
                            self._waiting[g["id"]] = why
                            print(f"{hhmmss()} ⏸ {g['id']} 等待：{why}", flush=True)
                        deferred.append(g)
                        continue
                    self._waiting.pop(g["id"], None)
                    self.dispatched.add(g["id"])
                    t = threading.Thread(target=self.worker, args=(g,), daemon=True)
                    t.start()
                    active.append(t)

                # 心跳：把还在跑的 agent 的 last_seen 刷新一下
                if active:
                    self.c.x("UPDATE agents SET last_seen=? WHERE status='running'", (now(),))
                # 只剩等解包的组：明确告诉人，并且不无限等
                if not active and not pending and deferred:
                    if self._wait_since is None:
                        self._wait_since = time.time()
                        print(f"{hhmmss()} ⏳ 只剩 {len(deferred)} 组在等检材解包："
                              f"{', '.join(g['id'] for g in deferred)}"
                              f"（最多等 {self.wait_unpack} 秒）", flush=True)
                    elif time.time() - self._wait_since > self.wait_unpack:
                        print(f"{hhmmss()} ✗ 等解包超时，放弃这些组："
                              f"{', '.join(g['id'] for g in deferred)}", flush=True)
                        for g in deferred:
                            self.blocked.append(
                                f"- [ ] **{g['id']}**（{g['name']}）等解包超时 —— "
                                f"{self._waiting.get(g['id'], '检材未就绪')}")
                        deferred = []
                else:
                    self._wait_since = None

                time.sleep(POLL_SEC)
                if not active and not pending and not deferred:
                    break
                # 跑完一批后，可能解锁了新的组
                if len(pending) < self.jobs and len(active) < self.jobs:
                    gs = self.groups()
                    more = [g for g in self.ready(gs)
                            if g["id"] not in self.dispatched
                            and g["id"] not in self._waiting
                            and g["status"] != "doing"]
                    if self.max_groups:
                        more = more[: max(0, self.max_groups - len(more))]
                    pending.extend(more)
        except KeyboardInterrupt:
            print(f"\n{hhmmss()} 收到中断，等 worker 收尾…", flush=True)
            self.stop.set()
            for t in active:
                t.join(timeout=10)

        elapsed = int(time.time() - started)
        self.write_blocked()
        self.summary(elapsed)
        return 0

    # ---------------------------------------------------------------- 收尾

    def write_blocked(self) -> None:
        if not self.blocked:
            p = self.c.meta / "blocked.md"
            if p.is_file():
                p.unlink()
            return
        L = ["# 待人工处理", "",
             f"自动生成于 {now()}。处理完可以删掉对应行。", "",
             "## 卡住的题", ""] + self.blocked + [""]
        api_hit = [l for l in self.blocked
                   if any(m in l.lower() for m in API_MARKERS)]
        if api_hit:
            L += ["## ⚠ 看起来是模型 API 的问题，不是证据不足", "",
                  "上面有失败项带了 API 错误关键字（余额 / 额度 / 鉴权 / 限流）。",
                  "先修这个，再重跑：", "",
                  "```bash", "fcase doctor            # 会真调一次模型，直接报错因",
                  "```", ""]
        pend = self.c.meta / "pending-install.md"
        if pend.is_file():
            L += ["## 待安装", "", pend.read_text(encoding="utf-8").strip(), ""]
        (self.c.meta / "blocked.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        print(f"\n⚠ {len(self.blocked)} 题需要人工处理 → meta/blocked.md", flush=True)

    def summary(self, elapsed: int) -> None:
        tot, done = self.c.q("SELECT count(*), sum(status='done') FROM questions")[0]
        gs = self.groups()
        gdone = sum(1 for g in gs if g["status"] == "done")
        print(f"\n{hhmmss()} 调度结束：{done}/{tot} 题，{gdone}/{len(gs)} 组，"
              f"用时 {elapsed // 60} 分 {elapsed % 60} 秒")
        base = getattr(self, "answer_base", 0)
        fresh = self.c.q(
            "SELECT DISTINCT qid FROM answers WHERE id>? AND qid IS NOT NULL ORDER BY qid",
            (base,))
        if fresh:
            qids = [r[0] for r in fresh]
            print(f"\n本次新增 {len(qids)} 题：{' '.join(qids)}")
            print("（下次只看新增：fcase answers --new）")
        else:
            print("\n本次没有新增答案")
        left = [g["id"] for g in gs if g["status"] != "done"]
        if left:
            print(f"  未完成组：{', '.join(left)}（再跑一次 fcase go 会重试）")


def default_jobs() -> int:
    """按核数自动定并发。

    实测 12 并发模型请求零 429、聚合吞吐 1817 tok/s；单 pi 约 300MB 内存。
    上限压到 12：再多会被「最长单组」卡住，收益有限；下限保底 2。
    """
    import os as _os
    cores = _os.cpu_count() or 4
    mem_gb = 0
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    mem_gb = int(line.split()[1]) // (1024 * 1024)
                    break
    except OSError:
        pass
    by_cpu = max(2, cores // 2)
    by_mem = max(2, int(mem_gb / 1.2)) if mem_gb else by_cpu   # 每个 pi ≈300MB，留余量
    return max(2, min(by_cpu, by_mem, 12))


def main() -> int:
    ap = argparse.ArgumentParser(description="主调度器：按题组派活")
    ap.add_argument("--jobs", "-j", type=int, default=0, help="并发组数，0=按核数自动")
    ap.add_argument("--provider", help="模型提供方，如 opengateway / nepnep")
    ap.add_argument("--model", help="模型 id，如 deepseek/deepseek-v4.1-flash-eco")
    ap.add_argument("--thinking", help="思考档位：off / minimal / low / medium / high")
    ap.add_argument("--timeout", type=int, default=1800, help="单题超时秒数")
    ap.add_argument("--max-groups", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--redo", action="store_true", help="已答过的题也重做")
    ap.add_argument("--solve-cmd", help="自定义 solve 命令（测试用）")
    ap.add_argument("--wait-unpack", type=int, default=1800,
                    help="检材还没解包时最多等多久（秒），默认 1800")
    ap.add_argument("--batch", type=int, default=1,
                    help="组内一次做几题（共享一个会话），默认 1")
    args = ap.parse_args()

    if not args.jobs:
        args.jobs = default_jobs()
        print(f"（并发数自动定为 {args.jobs}）", flush=True)
    c = Case()
    sched = Scheduler(c, args.jobs, args.model, args.timeout, args.max_groups,
                      args.dry_run, args.redo, args.solve_cmd, args.batch,
                      args.provider, args.thinking, args.wait_unpack)

    def _stop(signum, frame):
        sched.stop.set()

    signal.signal(signal.SIGTERM, _stop)
    return sched.run()


if __name__ == "__main__":
    raise SystemExit(main())
