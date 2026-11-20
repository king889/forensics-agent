"""fcase 的 5 个主命令：init / unpack / run / board / stop

设计目标：**使用者只需要记 5 个动词**，其余（probe、brief、extract、
deep-index、drive）都由这 5 个内部调度。

    fcase init <case目录> --evi <检材目录> [--question <题目.md>]
    fcase unpack            # 解包 + 建索引 + 生成清单（幂等，已做过就跳过）
    fcase run               # 后台起做题循环，每组建新会话
    fcase board             # 看进度
    fcase stop              # 停
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

_FCASE = Path(__file__).resolve().parents[1] / "fcase"

def die(msg: str, code: int = 2) -> None:
    print(f"fcase: {msg}", file=sys.stderr)
    raise SystemExit(code)



# ---------------------------------------------------------------- init


def cmd_init(c, a) -> None:
    """新建 case：目录骨架 + 检材软链 + 题目就位。

    注意：这一步发生在 case 还不存在的时候，所以不能依赖 c（Case 对象），
    所有校验自己 die。
    """

    case_dir = Path(a.case_dir).expanduser().resolve()
    meta = case_dir / "meta"
    evi = case_dir / "evi"
    if meta.is_dir():
        print(f"{case_dir} 已经是 case（有 meta/），跳过创建")
    else:
        for d in (evi, meta, case_dir / "work"):
            d.mkdir(parents=True, exist_ok=True)
        (meta / "question.md").write_text(
            "# 题目\n\n> 一行一题，题号用 `1.` `2.` 或 `## 1.` 都行。\n\n", encoding="utf-8")
        print(f"已建 case: {case_dir}")

    if a.evi:
        src = Path(a.evi).expanduser().resolve()
        if not src.is_dir():
            die(f"检材目录不存在: {src}")
        os.chmod(evi, 0o755)
        n = 0
        for p in sorted(src.iterdir()):
            if p.name.startswith("."):
                continue
            dst = evi / p.name
            if dst.exists() or dst.is_symlink():
                continue
            os.symlink(p, dst)
            n += 1
        os.chmod(evi, 0o555)
        print(f"软链 {n} 个检材 → {evi}（已锁 555）")

    if a.question:
        q = Path(a.question).expanduser().resolve()
        if not q.is_file():
            die(f"题目文件不存在: {q}")
        (meta / "question.md").write_text(q.read_text(encoding="utf-8", errors="replace"),
                                          encoding="utf-8")
        print(f"题目已就位: {meta / 'question.md'}")

    print(f"\n下一步：\n  cd {case_dir}\n  fcase unpack\n  fcase run\n")


# ---------------------------------------------------------------- unpack


def cmd_unpack(c, a) -> None:
    """解包 + 建索引 + 生成清单。全部幂等，已做过会跳过。"""
    # 0) 先登记检材（init 只做了软链，数据库里还没有记录）
    if c.db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0:
        subprocess.run([sys.executable, str(_FCASE), "ls"],
                       cwd=c.root, capture_output=True)
    if c.db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0:
        print("evi/ 里没有检材。先把文件放进 evi/（或用 fcase init --evi <目录>）")
        return

    # 1) 压缩包并行解
    ups = [r["path"] for r in c.db.execute("SELECT path FROM artifacts ORDER BY size_bytes DESC")
           if Path(r["path"]).suffix.lower() in (".zip", ".7z", ".rar")]
    if ups:
        print(f"== 解包 {len(ups)} 个压缩包（并行）==")
        script = Path(__file__).resolve().parent / "unpack"
        procs = []
        for name in ups:
            cmd = ["python3", str(script), f"evi/{name}"]
            if a.force:
                cmd.append("--force")
            log = c.meta / ".unpack.log"
            procs.append((name, _sp_popen(cmd, c.root, log)))
        for name, p in procs:
            rc = p.wait()
            print(f"  {'✓' if rc == 0 else '✗'} {name}" + (f"  rc={rc}" if rc else ""))
    else:
        print("== 没有压缩包，跳过解包 ==")

    # 2) 建索引（分区/文件系统/库）
    print("\n== 建索引 ==")
    arts = [r["path"] for r in c.db.execute("SELECT path FROM artifacts ORDER BY size_bytes DESC")]
    for name in arts:
        r = subprocess.run([sys.executable, str(_FCASE), "index", name],
                           cwd=c.root, capture_output=True, text=True)
        ok = r.returncode == 0
        print(f"  {'✓' if ok else '·'} {name}")

    # 3) 生成清单（fls / dissect walk / 目录遍历）
    print("\n== 生成清单 ==")
    for name in arts:
        r = subprocess.run([sys.executable, str(_FCASE), "deep-index", name],
                           cwd=c.root, capture_output=True, text=True)
        if r.returncode == 0:
            tail = (r.stdout or "").strip().splitlines()
            print(f"  ✓ {name}" + (f"   {tail[-1][:70]}" if tail else ""))
        else:
            # 没有文件系统的检材（内存镜像、加密容器）跳过是正常的
            print(f"  – {name}（无标准文件系统，跳过）")

    print("\n下一步：fcase run")


def _sp_popen(cmd, cwd, log):
    fh = log.open("ab")
    return subprocess.Popen(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                            start_new_session=True)


# ---------------------------------------------------------------- run / stop


def _pidfile(c) -> Path:
    return c.meta / ".run.pid"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_run(c, a) -> None:
    """后台起做题循环（每组一个新会话）。已在跑则提示。

    没有题组时自动粗分（plan --auto），这样使用者不需要单独记 plan 命令；
    想要精细分组就先跑 `fcase plan` 交给 agent 分类再 `--apply`。
    """
    # 题目还没导入就先导入（init 只把 question.md 放到位，没解析）
    if c.db.execute("SELECT count(*) FROM questions").fetchone()[0] == 0:
        qmd = c.meta / "question.md"
        if not qmd.is_file():
            die(f"没有题目：{qmd} 不存在")
        print("导入题目 …")
        r = subprocess.run([sys.executable, str(_FCASE), "import", "meta/question.md"],
                           cwd=c.root, capture_output=True, text=True)
        if r.returncode != 0:
            die(f"导入题目失败: {(r.stderr or r.stdout)[-300:]}")
        tail = (r.stdout or "").strip().splitlines()
        if tail:
            print(f"  {tail[-1][:80]}")

    have = c.db.execute("SELECT count(*) FROM groups").fetchone()[0]
    if have == 0:
        print("还没有题组，先自动粗分 …")
        r = subprocess.run([sys.executable, str(_FCASE), "plan", "--auto"],
                           cwd=c.root, capture_output=True, text=True)
        if r.returncode != 0:
            die(f"自动分组失败: {(r.stderr or r.stdout)[-300:]}")
    pf = _pidfile(c)
    if pf.is_file():
        try:
            old = int(pf.read_text().strip() or 0)
        except ValueError:
            old = 0
        if old and _alive(old):
            die(f"已经在跑（pid {old}）。要停用 `fcase stop`", 1)
        pf.unlink(missing_ok=True)

    drive = Path(__file__).resolve().parent / "drive.sh"
    if not drive.is_file():
        die(f"缺少 {drive}")

    log = c.meta / "run.log"
    fh = log.open("ab")
    p = subprocess.Popen(["bash", str(drive), str(a.rounds)], cwd=c.root,
                         stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    pf.write_text(str(p.pid), encoding="utf-8")
    print(f"已启动 pid={p.pid}  rounds={a.rounds}")
    print(f"  日志 meta/run.log")
    print(f"  看进度 fcase board")
    print(f"  停止   fcase stop")


def cmd_stop(c, a) -> None:
    """停止做题：杀进程组 + 把 doing 退回 todo。"""
    pf = _pidfile(c)
    killed = 0
    if pf.is_file():
        try:
            pid = int(pf.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid and _alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                killed += 1
            except OSError:
                pass
    # 兜底：按命令行匹配调度器/solve
    for pat in ("scheduler.py", "bin/solve", "internal/drive.sh"):
        r = subprocess.run(["pkill", "-f", pat], capture_output=True)
        if r.returncode == 0:
            killed += 1
    time.sleep(2)
    for pat in ("scheduler.py", "bin/solve"):
        subprocess.run(["pkill", "-9", "-f", pat], capture_output=True)
    pf.unlink(missing_ok=True)
    (c.meta / ".solve-par.pid").unlink(missing_ok=True)

    with c.db:
        n = c.db.execute("UPDATE questions SET status='todo' WHERE status='doing'").rowcount
        c.db.execute("UPDATE groups SET status='todo' WHERE status='doing'")
    print(f"已停止（{killed} 个进程组/进程），{n} 道 doing 题退回 todo")


REQUIRED = ["fls", "icat", "mmls", "fsstat", "7z", "rg", "sqlite3", "file"]
NICE = ["ffmpeg", "xxd", "strings", "exiftool", "jadx", "zbarimg",
        "volatility3", "target-fs", "thin_ls", "asc2log"]
PI_CONFIG = Path.home() / ".pi" / "agent" / "models.json"


def _ok(m: str) -> None:
    print(f"  \033[32m✓\033[0m {m}")


def _bad(m: str, hint: str = "") -> None:
    print(f"  \033[31m✗\033[0m {m}")
    if hint:
        print(f"      → {hint}")


def _warn(m: str) -> None:
    print(f"  \033[33m·\033[0m {m}")


def _pi_auth_ready(provider: str) -> bool:
    """问 pi 这个 provider 的凭据是否就绪（内置 provider 不必写进 models.json）。"""
    pi = shutil.which("pi")
    if not pi:
        return False
    try:
        r = subprocess.run([pi, "auth", "check", "--provider", provider],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and "ready" in (r.stdout or "").lower()


def cmd_doctor(c, a) -> None:
    problems = 0

    # ---------------- 1. Python ----------------
    print("\n== Python ==")
    v = sys.version_info
    if v >= (3, 11):
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _bad(f"Python {v.major}.{v.minor}（需要 ≥3.11）", "装 3.11+ 或改 pyproject")
        problems += 1

    # ---------------- 2. 工具链 ----------------
    print("\n== 取证工具 ==")
    missing = []
    for t in REQUIRED:
        p = shutil.which(t)
        if p:
            _ok(f"{t}  {p}")
        else:
            _bad(t, "跑 ./setup.sh " + t)
            missing.append(t)
    if missing:
        problems += 1
    nice_missing = [t for t in NICE if not shutil.which(t)]
    if nice_missing:
        _warn(f"可选工具未装：{' '.join(nice_missing)}（按需 ./tools/install.sh）")

    # ---------------- 3. Pi ----------------
    print("\n== Pi ==")
    pi = shutil.which("pi")
    if not pi:
        _bad("找不到 pi", "pip/npm 安装 @earendil-works/pi-coding-agent")
        problems += 1
    else:
        try:
            r = subprocess.run([pi, "--version"], capture_output=True, text=True, timeout=30)
            _ok(f"pi {r.stdout.strip()}")
        except (OSError, subprocess.SubprocessError) as exc:
            _bad(f"pi 无法运行: {exc}")
            problems += 1

    # ---------------- 4. 模型与凭据 ----------------
    print("\n== 模型凭据 ==")
    prov = model = None
    try:
        cfg = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
        prov, model = cfg.get("provider"), cfg.get("model")
    except (OSError, ValueError):
        pass
    if not prov or not model:
        _warn("config.json 里没有 provider/model")
    else:
        print(f"  config.json: provider={prov}  model={model}")

    provs = {}
    if PI_CONFIG.is_file():
        try:
            provs = (json.loads(PI_CONFIG.read_text(encoding="utf-8")).get("providers") or {})
        except (OSError, ValueError):
            provs = {}

    if prov and prov not in provs:
        # 可能是 Pi 内置 provider（openai / anthropic / deepseek / openrouter …），
        # 内置的不需要 models.json，直接问 pi 自己。
        if _pi_auth_ready(prov):
            _ok(f"provider '{prov}' 是 Pi 内置的，凭据就绪")
        elif not PI_CONFIG.is_file():
            _bad(f"provider '{prov}' 既不在 Pi 内置列表里，也没有 {PI_CONFIG}",
                 "内置 provider 直接 pi auth login；自定义的照 templates/models.json 建一份")
            problems += 1
        else:
            _bad(f"provider '{prov}' 未定义且凭据未就绪",
                 f"内置 provider：pi auth login {prov} --api-key；"
                 "自定义 provider：在 ~/.pi/agent/models.json 里加定义（见 templates/models.json）")
            problems += 1
    elif prov:
        if True:
            _ok(f"provider '{prov}' 已定义")
            ids = [m.get("id") for m in (provs.get(prov, {}).get("models") or [])]
            if model and model not in ids:
                _warn(f"该 provider 下没有列出模型 '{model}'：可用 {ids[:3]}…")
            # key 是否存在（不回显）
            raw = provs.get(prov, {}).get("apiKey", "")
            def _auth_json_has(provider: str) -> bool:
                try:
                    d = json.loads((Path.home() / ".pi" / "agent" / "auth.json")
                                   .read_text(encoding="utf-8"))
                    return bool((d.get(provider) or {}).get("key"))
                except (OSError, ValueError):
                    return False

            if isinstance(raw, str) and raw.startswith("$"):
                env = raw[1:]
                if os.environ.get(env):
                    _ok(f"凭据来自环境变量 ${env}（已设置）")
                elif _auth_json_has(prov):
                    # Pi 在环境变量缺失时会回退到 auth.json
                    _ok("凭据来自 ~/.pi/agent/auth.json")
                else:
                    _bad(f"凭据引用 ${env}，环境变量未设置且 auth.json 里也没有",
                         f"export {env}=<你的 key> 或 pi auth login {prov} --api-key")
                    problems += 1
            elif raw:
                _ok(f"凭据写在 models.json 里（{len(raw)} 字符，明文）")
            else:
                # 可能在 auth.json
                auth_f = Path.home() / ".pi" / "agent" / "auth.json"
                have = False
                try:
                    authd = json.loads(auth_f.read_text(encoding="utf-8"))
                    have = bool((authd.get(prov) or {}).get("key"))
                except (OSError, ValueError):
                    pass
                if have:
                    _ok(f"凭据来自 auth.json")
                else:
                    _bad(f"provider '{prov}' 没有凭据",
                         f"pi auth login {prov} --api-key")
                    problems += 1

    # ---------------- 5. 真实调用 ----------------
    if prov and model and not a.no_net and shutil.which("pi"):
        print("\n== 实际调用模型 ==")
        try:
            r = subprocess.run(["pi", "--provider", prov, "--model", model,
                                "--no-session", "-p", "只回复两个字：就绪"],
                               capture_output=True, text=True, timeout=120)
            out = (r.stdout or "").strip().splitlines()
            text = out[-1] if out else ""
            if r.returncode == 0 and "就绪" in text:
                _ok("模型可用")
            else:
                _bad(f"调用失败 rc={r.returncode}: {(text or r.stderr)[:120]}",
                     "检查 key / 余额 / baseUrl")
                problems += 1
        except (OSError, subprocess.SubprocessError) as exc:
            _bad(f"调用异常: {exc}")
            problems += 1

    # ---------------- 结论 ----------------
    print()
    if problems == 0:
        print("\033[32m环境就绪，可以 fcase unpack / fcase run\033[0m")
    else:
        print(f"\033[31m有 {problems} 项需要处理\033[0m（见上面 → 后面的提示）")
        raise SystemExit(1)
