# 内存取证（Memory Forensics）

> 目标：拿到一个内存镜像，**5 分钟内**说清楚「跑过什么进程、连过谁、藏了什么、flag 在哪」。
> 工具：`vol`(Vol3) / `vol2`(Vol2) / `memprocfs` / `yara` / `strings` / `rg`。
> 全部装在 `tools/`，`export PATH="$PWD/tools/bin:$PATH"` 之后直接用。

---

## 0. 先认检材（30 秒）

| 文件名 / 后缀 | 是什么 | 谁读得动 |
|---|---|---|
| `.raw` `.mem` `.bin` `.vmem` `.001` | 原始物理内存 / VMware 内存 | `vol` `vol2` `memprocfs` 全行 |
| `.dmp` | Windows 崩溃转储 | `vol -f x.dmp` 直接吃；**minidump（几十 KB~几 MB）不行**，要 kernel/full dump |
| `hiberfil.sys` | 休眠文件（等于一份内存） | `vol -f hiberfil.sys windows.pslist` |
| `.lime` | LiME 抓的 Linux 内存 | `vol -f x.lime linux.pslist`，**需要 ISF 符号表**（见 §2.3） |
| `.vmss` `.vmsn` | VMware 快照 | `vol -f x.vmss`；或 `memprocfs -device x.vmss -mount` |
| `pagefile.sys` | 页面文件 | 单独没用，配主镜像：`memprocfs -device x.raw -pagefile0 pagefile.sys` |
| `*.zip` 里套一层 | 压缩包 | **先 `unpack`**，别原地 7z |

**第一件事永远是 `windows.info`**：拿不到 `NtMajorVersion` / `KDBG` 就说明镜像不对（分卷缺了、抓的时候用了不支持的格式、或者这是台 Linux）。

```bash
vol -f evi/mem.raw windows.info          # 出 Kernel Base / DTB / 版本号
vol -f evi/mem.raw windows.info --csv     # 想喂给脚本时
```

> `tools/bin/vol` 是**包装器**，不是裸 vol：
> - 缺 `pycryptodome` 时**直接拒跑**并给修复命令（裸 vol 会静默丢掉 hashdump/cachedump/lsadump）
> - 缓存（PDB/ISF）落在 `tools/_cache/vol3`，不污染 `~`
> - `tools/volatility3-symbols/` 存在时自动带 `-s`

---

## 1. 五分钟出结果（顺序别改）

```bash
M=evi/mem.raw

# ① 进程三件套：活的 / 树 / 池扫描（藏起来的）
vol -f $M windows.pslist    --csv > work/pslist.csv
vol -f $M windows.pstree    > work/pstree.txt
vol -f $M windows.psscan    --csv > work/psscan.csv
#    pslist 没有、psscan 有 → 进程被摘链（DKOM 隐藏）
#    pslist 有、psscan 没有 → 进程已退出但对象还在

# ② 谁在跑什么命令（一眼看出 powershell -enc）
vol -f $M windows.cmdline

# ③ 连过谁（CTF 里最常出 flag 的地方之一）
vol -f $M windows.netscan

# ④ 注入 / 可疑内存段
vol -f $M windows.malfind --dump          # --dump 会把可疑段倒到当前目录

# ⑤ 直接找 flag（先暴力，后精细）
strings -a -n 6 $M | rg -i 'flag\{|ctf\{|[a-z0-9]{2,10}\{[^}]{6,80}\}'
yara -w -s tools/yara-rules/ctf.yar $M
```

跑完这五步还没头绪，再往下翻。

---

## 2. Volatility 3（主力）

### 2.1 常用插件（Windows）

| 想知道 | 插件 | 备注 |
|---|---|---|
| 系统版本 / KDBG | `windows.info` | 第一步 |
| 进程列表 | `windows.pslist` `windows.pstree` `windows.psscan` | 三个一起比 |
| 命令行 | `windows.cmdline` | |
| 环境变量 | `windows.envars` | 常藏 flag |
| 网络连接 | `windows.netscan` `windows.netstat` | netscan 扫池，netstat 走链表 |
| 加载的 DLL | `windows.dlllist` | `--pid N` 过滤 |
| 内存段 | `windows.vadinfo` `windows.vadwalk` | 看 RWX |
| 注入 | `windows.malfind` | RWX + MZ 头 |
| 句柄 | `windows.handles` | 找打开的文件/注册表 |
| 文件对象 | `windows.filescan` | 配合 `windows.dumpfiles --virtaddr 0x...` 捞文件 |
| 驱动 | `windows.driverscan` `windows.modules` `windows.drivermodule` | rootkit 检查 |
| 服务 | `windows.svcscan` `windows.svclist` | |
| 计划任务 | `windows.scheduled_tasks` | |
| 注册表 | `windows.registry.hivelist` `windows.registry.printkey --key "..."` | |
| 用户行为 | `windows.registry.userassist` | 点过什么 |
| 哈希 | `windows.hashdump` `windows.cachedump` `windows.lsadump` | **要 pycryptodome**，见 §7 |
| 剪贴板 / 控制台 | `windows.consoles` `windows.cmdscan` | cmdscan 常出历史命令 |
| 时间线 | `timeliner.Timeliner` | 慢，最后用 |
| YARA | `windows.vadyarascan --yara-file rules.yar` `windows.vadregexscan` | 比全盘 yara 快得多 |

```bash
# 过滤 / 输出
vol -f $M windows.dlllist --pid 1234
vol -f $M -o work/vol3 windows.malfind --dump     # 输出目录
vol -f $M windows.hashdump --csv
vol -f $M windows.registry.printkey --key 'ControlSet001\Services\Tcpip\Parameters'
```

### 2.2 符号表（Windows）

Vol3 靠 PDB 找内核结构体。**首次分析会自动从 `msdl.microsoft.com` 下 PDB**，缓存在 `~/.cache/volatility3`。
- 有网 → 什么都不用做。
- 断网 / 慢 → 预先下整套符号表（840MB）：
  ```bash
  ./tools/install.sh mem-symbols     # 落到 tools/volatility3-symbols/
  vol -s tools/volatility3-symbols -f $M windows.pslist
  ```
- 报了 `Unable to validate the plugin requirements` / `no symbol table` → 十有八九是版本太新（PDB 没公开）或镜像头部被改过。

### 2.3 Linux 镜像要 ISF

```bash
# vol3 只认「符号表目录」(-s)，不认单个 json 文件路径
vol -s /path/to/isf-dir -f x.lime linux.pslist
# 自建 ISF（要有同一内核的 vmlinux/System.map）：
#   dwarf2json linux --elf vmlinux > isf.json，丢进一个目录再用 -s 指过去
```
> 手上没有匹配的 ISF 时，**别死磕**：`strings + rg` + `memprocfs` 的原始视图往往更快。

---

## 3. Volatility 2（老镜像 / 老插件）

自带的 Python 2.7.18 在 `tools/py27`，**跟系统 py3 完全隔离**，直接 `vol2` 就行。

什么时候用 vol2 而不是 vol3：
1. **Windows XP / 2003 / Vista 老镜像** —— vol3 对 XP 支持差，vol2 有完整 profile。
2. vol3 认不出 banner（`windows.info` 报 no symbol），vol2 的 `imageinfo` 靠 KDBG 扫描还能猜出来。
3. 某些只有 vol2 有的插件：`connscan` `sockets` `sessions` `consoles` `yarascan`(win) `hollowfind`。

```bash
vol2 -f evi/xp.raw imageinfo                 # 猜 profile，输出 Suggested Profile(s)
vol2 -f evi/xp.raw --profile=WinXPSP3x86 pslist
vol2 -f evi/xp.raw --profile=WinXPSP3x86 netscan
vol2 -f evi/xp.raw --profile=WinXPSP3x86 yarascan --yara-file=tools/yara-rules/ctf.yar
vol2 -f evi/xp.raw --profile=Win7SP1x64 malfind --dump-dir=work/vol2
vol2 -f evi/xp.raw --profile=Win7SP1x64 dumpfiles --dump-dir=work/vol2
```

**vol2 ↔ vol3 插件对照**

| vol2 | vol3 |
|---|---|
| `pslist` `pstree` `psscan` | 同名 `windows.*` |
| `netscan` / `connections` / `connscan` | `windows.netscan` / `windows.netstat` |
| `cmdline` `cmdscan` `consoles` | 同名 |
| `dlllist` `ldrmodules` | 同名 |
| `malfind` | `windows.malfind` |
| `hivelist` `printkey` `userassist` | `windows.registry.*` |
| `hashdump` `lsadump` `cachedump` | `windows.hashdump` 等 |
| `filescan` + `dumpfiles` | 同名 |
| `yarascan` | `windows.vadyarascan`（更快） |
| `imageinfo` | `windows.info` |

> 老镜像（XP 时代）常常 `vol2 imageinfo` 猜 profile 都猜不准 → 试 `WinXPSP2x86` / `WinXPSP3x86` 逐个来。

---

## 4. MemProcFS（把内存挂成文件系统）

```bash
# ① 挂载（WSL 里 /dev/fuse 已就绪）
mkdir -p work/mem
memprocfs -device evi/mem.raw -mount work/mem &

# ② 直接翻目录，比敲插件快得多
ls work/mem/name/                 # 按进程名，每个进程一个目录
ls work/mem/pid/                 # 按 PID
cat work/mem/name/explorer.exe/cmdline.txt
ls  work/mem/name/explorer.exe/modules/
ls  work/mem/registry/           # 注册表全树，直接 cat 值
ls  work/mem/files/              # 文件系统视图（NTFS 解析出来）
ls  work/mem/misc/               # 系统信息、网络、驱动

# ③ 一次性取证扫描（挂载目录下出 forensic/）
memprocfs -device evi/mem.raw -mount work/mem -forensic work/forensic
#   forensic/csv/*.csv  ：进程、网络、注入、YARA 命中，直接 rg
#   -forensic-yara-rules tools/yara-rules/ctf.yar
#   -forensic-process-skip svchost.exe,lsass.exe   跳过噪声

# ④ 卸载
fusermount -u work/mem
```

**Python API**（Agent 里批量拿数据用，比解析文本稳）：

```bash
memprocfs-python -c '
import memprocfs
vmm = memprocfs.Vmm(["-device","evi/mem.raw"])
for p in vmm.process_list():
    print(p.pid, p.name, p.eprocess)
'
```

```python
# 常用对象
vmm.process_list()          # 进程列表
vmm.process(pid).maps       # 内存映射（可读区域）
vmm.process(pid).modules    # 模块列表
vmm.registry                # 注册表
vmm.vfs.list("/")           # 虚拟文件系统
```
> API 的完整方法列表见 `tools/memprocfs/vmmdll.h` 和 `memprocfs_example.py`。

**MemProcFS 独有能力**
- `-pagefile0..9` 把页面文件接回主镜像（vol3 做不到）。
- `-vm` 直接解析 VM 里的客户机内存。
- 支持 **LiveRAM / DMA 硬件 / 远程 LeechAgent**（`-remote`）。
- 挂载后 `work/mem/forensic/` 里直接是 CSV，`rg` 一把梭。

---

## 5. YARA / strings / rg（找 flag 的最后一道）

```bash
# 规则位置
tools/yara-rules/ctf.yar             # 自己写的：flag / 凭据 / mimikatz / 注入 / 钱包
tools/yara-rules/signature-base/     # Neo23x0 750 条：APT / 木马 / webshell / CVE

# 扫内存镜像
yara -w -s tools/yara-rules/ctf.yar evi/mem.raw
yara -w -r tools/yara-rules/signature-base evi/mem.raw      # 全量，慢但全
yara -w -s -t mem -p 8 rules.yar mem.raw                    # 多线程 + 超时

# strings 两档：快扫 / 全扫
strings -a -n 6 evi/mem.raw | rg -i 'flag|ctf\{'            # 快
strings -a -e l -n 6 evi/mem.raw | rg -i 'flag'             # 16 位小端（UTF-16LE，Windows 字符串多）
rg -a -i -o '.{0,40}flag\{[^}]{4,120}\}.{0,10}' evi/mem.raw # 上下文
```

**注意**
- `strings` 默认只抓 ASCII；Windows 内存里大量是 UTF-16 → **一定要加 `-e l`** 再扫一遍。
- 扫 `signature-base` 目录时规则文件自身也会命中（规则里写了特征串），属正常，加 `-w` 消警告。
- 大镜像（>8G）先 `strings` 落盘再 `rg`，比反复扫镜像快 10 倍：
  ```bash
  strings -a -n 6 evi/mem.raw > work/mem.strings
  rg -i 'flag\{' work/mem.strings
  ```

---

## 6. 典型题目套路

| 题面关键词 | 打法 |
|---|---|
| 「进程里有恶意程序」 | `psscan` vs `pslist` 差集 → `cmdline` → `malfind --dump` → `yara` 扫 dump |
| 「他下载了什么文件」 | `filescan` + `dumpfiles`，或 `memprocfs` 的 `work/mem/files/` |
| 「密码是什么」 | `windows.hashdump`（NTLM）→ 解不开就 `strings \| rg -i 'pass'`；`lsadump` 看明文 |
| 「访问了哪个网址」 | `netscan` + `strings \| rg 'https?://'` + 浏览器进程内存里 `rg 'GET /'` |
| 「flag 被编码/加密」 | 先 `yara` 命中位置 → 用 `dd` 截那一段 → `cyberchef` 解 |
| 「隐藏进程 / rootkit」 | `psscan`−`pslist`、`drivermodule`、`ssdt`、`callbacks` |
| 「内存马 / webshell」 | `malfind` + `windows.vadyarascan --yara-file webshell.yar` |
| 「bitlocker / 加密容器」 | `windows.truecrypt`、`strings \| rg -i 'bitlocker\|recovery key'` |
| 「Linux 内存」 | `vol -f x.lime linux.pslist`（要 ISF）；没有就 `strings`+`rg` |

---

## 7. 坑表（都是真踩过的）

| 现象 | 原因 / 解法 |
|---|---|
| `vol --help` 里**没有 `hashdump` / `lsadump` / `cachedump`** | 缺 `pycryptodome`，vol3 会**静默跳过**这些插件（不报错、不警告）。用仓库里的 `tools/bin/vol` 会直接拒跑并提示；修复：`./tools/install.sh vol3` |
| 直接敲 `vol` 行为和文档不一样（没缓存/没符号表） | PATH 里 `~/.local/bin/vol` 排在前面，那是裸 vol。确认 `which vol` → `tools/bin/vol` |
| `Unable to validate the plugin requirements` | 符号表拿不到 → 联网 / `-s tools/volatility3-symbols` |
| `windows.info` 卡在 `Determining profile` | 镜像不是完整物理内存（可能只是 minidump 或分卷缺片） |
| `vol2` 报 `No module named _sqlite3` | py2 编译时没 sqlite3 头 → `install.sh mem` 已从 deb 解头文件单独编好 |
| py2.7 编译报 `cannot use keyword 'false'` | gcc 15 默认 gnu23 撞 `asdl.h` → 必须 `CFLAGS="-std=gnu17 -fcommon"` |
| `memprocfs: libfuse.so.2: cannot open shared object` | 依赖没带 → 用 `tools/bin/memprocfs` 包装器（自动设 `LD_LIBRARY_PATH`） |
| `memprocfs` 挂载目录空 / 立刻退出 | 镜像不是 Windows 物理内存；看 `-v` 输出。Linux 内存 MemProcFS 不支持 |
| `strings` 扫不到中文/宽字符 flag | 加 `-e l`（UTF-16LE） |
| `yara` 报 `may slow down scanning` | 正则太宽，`-w` 消掉；或改成 `fast` 模式 |
| `vol` 输出被 `--csv` 弄乱 | `--csv` 只对支持 renderer 的插件有效，不行就 `> file.txt` 自己 awk |
| 内存镜像特别大（>32G） | 先 `strings` 落盘；`vol` 加 `--parallelism processes`；别对整盘跑 `yara -r` |

---

## 8. 装了什么

```
vol       Volatility 3 2.28.2（uv tool，含 pycryptodome/capstone/yara-python）105 个 windows 插件
vol2      Volatility 2.6.1 + 自带 Python 2.7.18（tools/py27），364 行 profile 列表
memprocfs MemProcFS 5.19.4 + libfuse2/libusb（解包自带），含 Python API
yara      yara 4.5.5 + ctf.yar + signature-base 750 条
strings   binutils；rg ripgrep
```
