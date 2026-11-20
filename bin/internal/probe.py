"""probe —— 在模型动手之前，先把"候选表"算好。

为什么需要：
    实测同一批题换模型、开 thinking high 都修不好，因为错法是固定的：
    模型看到第一个"像样"的答案就停（Q09 找到 12.6 秒的那条就交卷、
    Q66 读到一个 SanDisk 就交卷、Q87 只看了一个 auth.log 轮转）。

    提示词管不住这件事，只能机械化：由脚本把全部候选列出来、排好序，
    简报里直接摆一张表。模型拿到的不是"记得去列候选"的指令，而是已经排好的结果。

    `fcase probe Q09` → 结果写进 meta/probes/Q09.md，简报自动引用。
"""

from __future__ import annotations

import gzip
import io
import json
import re
import subprocess
from pathlib import Path

# 带 regipy 的解释器（tools/venv-win）
REGIPY_PY = Path("$ROOT/tools/venv-win/bin/python3")
IMG_EXT = {".e01", ".dd", ".raw", ".img", ".bin"}


def _run(cmd: list[str], cwd: Path, timeout: int = 180) -> str:
    """跑命令拿 stdout。不用 text=True —— 镜像里路径可能是任意字节。"""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
        return (r.stdout or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _img(c, art: str) -> tuple[str, list[dict]]:
    stem = Path(art).stem
    p = None
    for d in (c.work / "unpack" / stem, c.work / stem):
        if d.is_dir():
            for f in sorted(d.rglob("*"), key=lambda x: -(x.stat().st_size if x.is_file() else 0)):
                if f.is_file() and f.suffix.lower() in IMG_EXT and "_ram" not in f.name.lower():
                    p = f
                    break
        if p:
            break
    if p is None:
        return str(c.evi / art), []
    idx = c.meta / "index" / f"{stem}.json"
    parts = []
    if idx.is_file():
        try:
            parts = json.loads(idx.read_text(encoding="utf-8")).get("partitions") or []
        except ValueError:
            parts = []
    parts = [x for x in parts if x.get("start") is not None
             and "Unallocated" not in (x.get("desc") or "")
             and "Primary Table" not in (x.get("desc") or "")]
    return str(p), parts


def _listing(c, art: str, start) -> str:
    """优先用 deep-index 已生成的 fls-<start>.txt，没有才现场跑 fls。"""
    f = c.arts / Path(art).stem / f"fls-{start}.txt"
    if f.is_file() and f.stat().st_size > 0:
        try:
            return f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    img, _ = _img(c, art)
    return _run(["fls", "-o", str(start), "-r", "-p", img], c.root, 900)


def _icat(c, art: str, start, inode: str, limit: int = 64 << 20) -> bytes:
    img, _ = _img(c, art)
    try:
        r = subprocess.run(["icat", "-o", str(start), img, inode],
                           cwd=c.root, capture_output=True, timeout=600)
        return (r.stdout or b"")[:limit]
    except (OSError, subprocess.SubprocessError):
        return b""


def _find_in_listing(listing: str, pattern: str, limit: int = 40) -> list[tuple[str, str]]:
    """从 fls 清单里找 (inode, path)。"""
    out = []
    for line in listing.splitlines():
        if re.search(pattern, line, re.I):
            m = re.search(r"(\d+)[-\d]*:\s*(\S.*)$", line)
            if m:
                out.append((m.group(1), m.group(2).strip()))
            if len(out) >= limit:
                break
    return out


# ---------------------------------------------------------------- 注册表类


_HIVE_SCRIPT = r"""
import sys, json
from regipy.registry import RegistryHive
h = RegistryHive(sys.argv[1])
out = []
try:
    root = h.get_key(sys.argv[2])
except Exception as e:
    print(json.dumps({"error": str(e)})); sys.exit(0)
def walk(node, depth, prefix=""):
    if node is None: return
    name = prefix + "/" + str(node.name or "")
    vals = {}
    try:
        for v in (node.iter_values() or []):
            n = str(v.name)
            if any(k in n.lower() for k in ("last", "arrival", "connect", "install", "time", "date")):
                vals[n] = str(v.value)[:40]
    except Exception:
        pass
    lw = ""
    try:
        lw = str(node.header.last_modified)
    except Exception:
        pass
    out.append({"key": name, "last_write": lw, "vals": vals})
    if depth > 0:
        try:
            for sk in (node.iter_subkeys() or []):
                walk(sk, depth - 1, name)
        except Exception:
            pass
walk(root, int(sys.argv[3]))
print(json.dumps(out))
"""


def _hive_dump(c, art: str, hive_name: str, key_path: str, depth: int = 3) -> list[dict]:
    """把注册表某个键下所有子键的时间相关值 dump 出来（用带 regipy 的 venv）。"""
    hv = c.arts / Path(art).stem / "hives.txt"
    hits = []
    if hv.is_file():
        hits = _find_in_listing(hv.read_text(encoding="utf-8", errors="replace"),
                                rf"config/{hive_name}$", limit=3)
    if not hits:
        for p in _img(c, art)[1]:
            hits = _find_in_listing(_listing(c, art, p["start"]),
                                    rf"config/{hive_name}$", limit=3)
            if hits:
                break
    if not hits:
        return []

    start = 0
    for p in _img(c, art)[1]:
        start = p["start"]
        break
    raw = _icat(c, art, start, hits[0][0], limit=256 << 20)
    if not raw:
        return []

    script = c.meta / ".probe-hive.py"
    hive = c.meta / ".probe-hive.bin"
    script.write_text(_HIVE_SCRIPT, encoding="utf-8")
    hive.write_bytes(raw)
    py = str(REGIPY_PY) if REGIPY_PY.is_file() else "python3"
    out = _run([py, str(script), str(hive), key_path, str(depth)], c.root, 300)
    for f in (script, hive):
        f.unlink(missing_ok=True)
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _filetime_str(v: str) -> str:
    """Windows FILETIME(100ns since 1601) → UTC+8 可读时间。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)[:26]
    if n <= 0:
        return ""
    import datetime as _dt
    try:
        t = _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(microseconds=n / 10)
        return t.astimezone(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, ValueError):
        return str(v)[:26]


def probe_usb(c, art: str) -> list[str]:
    """USB 存储设备：把所有设备按最后活动时间排序。

    Q66 错法：读到一台 SanDisk 就交卷，没比较全部设备取最晚的。
    """
    L = ["## 候选：所有 USB 存储设备（按最后活动时间排序，UTC+8）", ""]
    rows = _hive_dump(c, art, "SYSTEM", r"\ControlSet001\Enum\USBSTOR", depth=3)
    if not rows:
        L += ["_没能解析 SYSTEM hive，手动查：_", "",
              "```",
              "icat -o 0 <img> <SYSTEM inode> > /tmp/SYSTEM",
              "regipy-dump -h /tmp/SYSTEM --registry-path '\\ControlSet001\\Enum\\USBSTOR'",
              "```", ""]
        return L

    # 只保留设备层（/USBSTOR/<Disk&Ven_..>）和实例层（.../<serial>）
    items = []
    for r in rows:
        key = r.get("key") or ""
        if key.count("/") < 2:
            continue
        t = _filetime_str(r.get("last_write"))
        if not t:
            continue
        items.append((t, key, r.get("vals") or {}))
    items.sort(reverse=True)          # 最新的在最前
    L += ["| 最后活动时间 | 设备键 | 其他时间值 |", "|---|---|---|"]
    for t, key, vals in items[:25]:
        v = "; ".join(f"{k}={val}" for k, val in vals.items())
        L.append(f"| {t} | `{key[:64]}` | {v[:60]} |")
    if items:
        L += ["", f"> **最后连接的是最上面那一行**（{items[0][0]}，设备 `{items[0][1][:50]}`）。",
              "> 但注意：USBSTOR 记录的是「曾插入过的存储设备」，"
              "「最后连接」还要和 `Enum\\USB` 的 LastArrival 交叉核对；"
              "品牌名在键名 `Disk&Ven_<品牌>&Prod_<型号>` 里。",
              "> 只读到一台就交卷是最常见的错法 —— 上表已按时间倒序，取第一行。", ""]
    return L


# ---------------------------------------------------------------- 日志类


def probe_ssh(c, art: str) -> list[str]:
    """合并全部 auth.log 轮转，按时间排序取最早。"""
    L = ["## 候选：所有 SSH 成功登录（跨轮转合并排序）", ""]
    recs: list[tuple[str, str, str]] = []
    for p in _img(c, art)[1]:
        listing = _listing(c, art, p["start"])
        logs = _find_in_listing(listing, r"auth\.log")
        if not logs:
            continue
        L.append(f"### 分区 @{p['start']}：{len(logs)} 个 auth.log 文件")
        L += [f"- `{path}` (inode {ino})" for ino, path in logs]
        for ino, path in logs:
            raw = _icat(c, art, p["start"], ino)
            if not raw:
                continue
            if path.endswith(".gz"):
                try:
                    raw = gzip.decompress(raw)
                except (OSError, EOFError):
                    continue
            for ln in raw.decode("utf-8", "replace").splitlines():
                m = re.search(r"^(\S+).*?Accepted \S+ for (\S+) from ([\d.]+)", ln)
                if m:
                    recs.append((m.group(1), m.group(2), m.group(3)))
        L.append("")
    if recs:
        recs.sort()
        ips = sorted({ip for _, _, ip in recs})
        L += ["### 全部成功登录（时间正序）", "", "| 时间 | 用户 | 源 IP |", "|---|---|---|"]
        L += [f"| {t} | {u} | {ip} |" for t, u, ip in recs[:30]]
        L += ["", f"**出现过的源 IP（{len(ips)} 个）**：{', '.join(ips)}", "",
              f"> 跨全部轮转排序后，最早一条是 **{recs[0][0]}** 来自 **{recs[0][2]}**。",
              "> 题目问「首个」就取这一行 —— 不要取某一个文件里的第一行。", ""]
    else:
        L += ["_没解析出 Accepted 记录_", ""]
    return L


def probe_listen(c, art: str) -> list[str]:
    """端口：同时给出配置值和运行时 LISTEN 快照。"""
    L = ["## 候选：配置里的端口 vs 运行时实际 LISTEN", ""]
    got = False
    for p in _img(c, art)[1]:
        listing = _listing(c, art, p["start"])
        snaps = _find_in_listing(listing, r"(?i)(netstat|ss_|listening|port|connection).*\.(txt|log)")
        envs = _find_in_listing(listing, r"(?i)(^|/)\.env$")
        for ino, path in (snaps + envs)[:30]:
            raw = _icat(c, art, p["start"], ino, limit=2 << 20)
            if not raw:
                continue
            text = raw.decode("utf-8", "replace")
            hits = [l for l in text.splitlines() if re.search(r"(?i)LISTEN|^PORT=", l)]
            if hits:
                got = True
                L += [f"**`{path}`**（运行时快照，以这个为准）" if "listen" in path.lower()
                      or "netstat" in path.lower() else f"**`{path}`**（配置文件，仅作参考）", "",
                      "```"] + [h.strip()[:150] for h in hits[:15]] + ["```", ""]
    if not got:
        L += ["_没在镜像里找到 LISTEN 快照_", "",
              "手动查（挂载或 icat 出 live preservation 目录）：", "```",
              "ss -Ltn    # 或在 live preservation 里找 netstat_*", "```", ""]
    L += ["> 题目问「LISTEN 状态」→ **以 ss/netstat 的运行时输出为准**。",
          "> `.env` / systemd 里的 PORT 是配置值，可能和实际监听不同（配置 3000、实际 80 这种坑）。", ""]
    return L


# ---------------------------------------------------------------- 媒体类


def _extract_db(c, art: str, start: int, hits: list[tuple[str, str]]):
    """把 Photos.sqlite 连同 -wal / -shm 一起 icat 到临时目录再打开。

    实测：已删除的记录（ZTRASHEDSTATE=1）只在 WAL 里，只 icat 主库会查到 0 条 ——
    这也是 agent 的答案来源是「WAL frame508」的原因。
    """
    import tempfile
    base = None
    for ino, path in hits:
        if path.endswith("Photos.sqlite"):
            base = path
            break
    if not base:
        return None
    d = Path(tempfile.mkdtemp(prefix="probe-db-"))
    dest = d / "Photos.sqlite"
    stem = base[:-len(".sqlite")] if base.endswith(".sqlite") else base
    got = False
    for ino, path in hits:
        for suffix in ("", "-wal", "-shm"):
            if path == base + suffix:
                data = _icat(c, art, start, ino, limit=256 << 20)
                if data:
                    (d / ("Photos.sqlite" + suffix)).write_bytes(data)
                    if not suffix:
                        got = True
    return dest if got else None


def probe_deleted_photo(c, art: str) -> list[str]:
    L = ["## 候选：已删除照片（全部排序，含 WAL 里的记录）", ""]
    done = False
    for p in _img(c, art)[1]:
        listing = _listing(c, art, p["start"])
        hits = _find_in_listing(listing, r"Photos\.sqlite($|-wal$|-shm$)", limit=5)
        db = _extract_db(c, art, p["start"], hits)
        if not db:
            continue
        sql = ("SELECT ZFILENAME, ZTRASHEDSTATE, "
               "round(ZTRASHEDDATE-ZDATECREATED,3) AS gap_sec "
               "FROM ZASSET WHERE ZTRASHEDSTATE=1 ORDER BY gap_sec ASC LIMIT 20;")
        out = _run(["sqlite3", "-separator", " | ", str(db), sql], c.root, 120)
        if out.strip():
            done = True
            L += ["| 文件名 | 创建→删除 间隔(秒) |", "|---|---|"]
            for l in out.strip().splitlines():
                parts = [x.strip() for x in l.split(" | ")]
                if len(parts) >= 3:
                    L.append(f"| {parts[0]} | {parts[2]} |")
            L += ["", "> 按间隔升序。题目要「不足 20 秒」的那个 —— 看清定义再取，"
                  "第一行不一定就是答案。", ""]
        import shutil as _sh
        _sh.rmtree(db.parent, ignore_errors=True)
    if not done:
        L += ["_没能从镜像里取出 Photos.sqlite（含 WAL），手动查：_", "",
              "```",
              "icat -o <start> <img> <Photos.sqlite inode>      > /tmp/p.sqlite",
              "icat -o <start> <img> <Photos.sqlite-wal inode>  > /tmp/p.sqlite-wal",
              "sqlite3 /tmp/p.sqlite \"SELECT ZFILENAME, round(ZTRASHEDDATE-ZDATECREATED,3) g",
              "  FROM ZASSET WHERE ZTRASHEDSTATE=1 ORDER BY g ASC;\"",
              "```", ""]
    return L


def probe_screenshot(c, art: str) -> list[str]:
    L = ["## 候选：截图统计（多个口径都算出来）", ""]
    done = False
    for p in _img(c, art)[1]:
        listing = _listing(c, art, p["start"])
        hits = _find_in_listing(listing, r"Photos\.sqlite($|-wal$|-shm$)", limit=5)
        db = _extract_db(c, art, p["start"], hits)
        if not db:
            continue
        sql = ("SELECT 'A ZKINDSUBTYPE=10(系统判定截图)', count(*) FROM ZASSET WHERE ZKINDSUBTYPE=10 "
               "UNION ALL SELECT 'B SpringBoard导入', count(*) FROM ZASSET z "
               "JOIN ZADDITIONALASSETATTRIBUTES a ON a.ZASSET=z.Z_PK "
               "WHERE a.ZIMPORTEDBYBUNDLEIDENTIFIER='com.apple.springboard' "
               "UNION ALL SELECT 'C 图片总数 ZKIND=0', count(*) FROM ZASSET WHERE ZKIND=0 "
               "UNION ALL SELECT 'D 文件名.PNG', count(*) FROM ZASSET WHERE ZFILENAME LIKE '%.PNG';")
        out = _run(["sqlite3", "-separator", " | ", str(db), sql], c.root, 120)
        if out.strip():
            done = True
            L += ["| 口径 | 数量 |", "|---|---|"]
            for l in out.strip().splitlines():
                parts = [x.strip() for x in l.split(" | ")]
                if len(parts) == 2:
                    L.append(f"| {parts[0]} | {parts[1]} |")
            L += ["", "> 题目问「主动进行屏幕截图」→ 取语义上对的那个口径，"
                  "evidence 里写明选了哪个、为什么，并列出其他口径的数。", ""]
        import shutil as _sh
        _sh.rmtree(db.parent, ignore_errors=True)
    if not done:
        L += ["_没能取出 Photos.sqlite_", ""]
    return L


PROBES = {
    "usb": (r"(?i)(USB|闪存|外接存储|移动硬盘|U盘)", probe_usb),
    "ssh": (r"(?i)(SSH|远程登录)", probe_ssh),
    "listen": (r"(?i)(LISTEN|监听|端口号|\bPort\b|通讯埠|通讯端口)", probe_listen),
    "deleted_photo": (r"(?i)(垃圾桶|已删除|移到垃圾桶)", probe_deleted_photo),
    "screenshot": (r"(?i)(屏幕截图|截图功能)", probe_screenshot),
}


def pick(stem: str) -> list[tuple[str, object]]:
    return [(name, fn) for name, (pat, fn) in PROBES.items() if re.search(pat, stem or "")]


def build(c, qid: str):
    row = c.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        return None
    picked = pick(row["stem"] or "")
    if not picked:
        return None
    out = [f"# {qid} 预计算候选表", "",
           "> 由 `fcase probe` 生成：候选已列全并排序，**直接用这张表判断**，"
           "不要自己重新找一遍。", ""]
    for name, fn in picked:
        try:
            out += fn(c, row["artifact"] or "")
        except Exception as exc:
            out += [f"_{name} 探测失败：{type(exc).__name__}: {exc}_", ""]
    d = c.meta / "probes"
    d.mkdir(exist_ok=True)
    dest = d / f"{qid}.md"
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dest
