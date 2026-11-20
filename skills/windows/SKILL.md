---
name: windows
description: Windows 取证。磁盘镜像（E01/vhd/vmdk/qcow2/raw）里的 NTFS、注册表 hive、EVTX 事件日志、Prefetch、LNK/JumpList、Amcache、ShimCache、SRUM、ShellBags、浏览器历史、时间线。检材是 Windows 镜像、注册表、evtx、hive 时加载。
---

# Windows 取证

主力是 **Dissect**（Fox-IT，671 个插件，直接读 E01/vhd/vmdk，不用转 raw）。
配合 TSK（inode 级操作）、Regipy（注册表）、Hayabusa（EVTX 检测）、Hindsight
（浏览器）、Plaso（时间线）。

**Eric Zimmerman Tools 在 Linux 上跑不了** —— 官方发的是 win-x64 单文件 exe，
没有 dll 也没跨平台构建。Dissect 覆盖了它全部功能，对照表见 §2。

## 0. 认检材

| 拿到什么 | 怎么开 |
|---|---|
| `.E01` / `.Ex01` | 直接给 Dissect 或 TSK，**不用转 raw** |
| `.vhd` / `.vhdx` / `.vmdk` / `.qcow2` | Dissect 直接开 |
| `.dd` / `.raw` / `.img` / `.bin` | 先 `mmls` 看分区表 |
| 注册表 hive（`SOFTWARE` `SYSTEM` `NTUSER.DAT` `Amcache.hve`） | §3 |
| `.evtx` | §4 |
| 已导出的 `C:\Users\...` 目录树 | §6 浏览器、§3 注册表 |

```bash
target-info evi/win.E01          # 磁盘/卷/文件系统一览，先跑这个
ewfinfo evi/win.E01              # E01 元数据（采集人、时间、软件版本）
```

## 1. 五分钟出结果

```bash
target-query -f os evi/win.E01              # 系统版本，确认是不是 Windows
target-query -f version evi/win.E01
target-query -l                             # 全部插件，671 个
```

`target-query -f <插件> <目标>` 是核心用法，输出可以是 csv/json：
`target-query -f mft.records --csv work/mft.csv evi/win.E01`。

**先探路再全量** —— `mft.timeline` 在一个 200G 镜像上能出几百万行。

## 2. EZ Tools 对照表

| 要什么 | EZ Tools | 这里用 |
|---|---|---|
| MFT 记录 | MFTECmd | `target-query -f mft.records` |
| MFT 时间线 | MFTECmd | `target-query -f mft.timeline` |
| USN 日志 | MFTECmd | `target-query -f usnjrnl` |
| Prefetch | PECmd | `target-query -f prefetch` |
| 事件日志 | EvtxECmd | `target-query -f evtx` / `hayabusa` |
| 快捷方式 | LECmd | `target-query -f lnk` |
| 跳转列表 | JLECmd | `target-query -f jumplist` |
| Amcache | AmcacheParser | `target-query -f amcache.applications` |
| ShimCache | AppCompatCacheParser | `target-query -f shimcache` |
| ShellBags | SBECmd | `target-query -f shellbags` |
| SRUM | SrumECmd | `target-query -f sru.application` |
| 回收站 | RBCmd | `target-query -f recyclebin` |
| 用户运行记录 | — | `target-query -f userassist` |
| 开机启动项 | RECmd | `target-query -f runkeys` |
| 服务 | RECmd | `target-query -f services` |
| 计划任务 | — | `target-query -f tasks` |
| Defender 日志 | — | `target-query -f defender.evtx` |
| 注册表 | RECmd | `target-reg` / `regipy`（§3） |

## 3. 注册表

**用 Dissect 读整盘里的 hive（推荐，自动挂载）**

```bash
target-reg evi/win.E01 -k 'HKLM\SYSTEM\CurrentControlSet\Services'
target-reg evi/win.E01 -k 'HKCU\Software\Microsoft\Windows\CurrentVersion\Run'
target-reg evi/win.E01 -k 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' -d 2
```

**用 Regipy 读单个 hive 文件（已导出的）**

```bash
regipy-dump evi/NTUSER.DAT                          # 全部 key 转 json
regipy-dump evi/NTUSER.DAT --as-json
regipy-plugins-list                                  # 看有哪些分析插件
regipy-plugins-run evi/NTUSER.DAT -o work/out.json -p userassist
regipy-plugins-run evi/SYSTEM -o work/svc.json -p services
regipy-parse-header evi/SOFTWARE                     # hive 元数据、最后写入时间
regipy-process-transaction-logs evi/SOFTWARE         # 处理 .LOG1/.LOG2
```

注册表分析的高价值路径：`Run`/`RunOnce`（开机启动）、`Services`（服务持久化）、
`USBSTOR`（插过什么 U 盘）、`UserAssist`（运行过什么程序）、
`RecentDocs`、`ShellBags`（访问过哪些目录）、`Amcache`（程序首次执行）。

## 4. EVTX 事件日志

```bash
# 从镜像里先导出来
target-fs evi/win.E01 cp /Windows/System32/winevt/Logs/Security.evtx work/evtx/
# 或者直接让 Dissect 读
target-query -f evtx evi/win.E01 --csv work/evtx.csv

# Hayabusa：4000+ 检测规则，直接出告警
hayabusa csv-timeline -d work/evtx -o work/timeline.csv -w
hayabusa logon-summary -d work/evtx          # 登录汇总
hayabusa pivot-keywords-list -d work/evtx    # 值得追的关键词
hayabusa update-rules                        # 规则更新（首次可能要用）
```

关键 Event ID：`4624` 登录成功 / `4625` 登录失败 / `4688` 进程创建 /
`4720` 建用户 / `7045` 装服务 / `1102` 日志被清。

## 5. 提取文件

```bash
target-fs evi/win.E01 ls /Users
target-fs evi/win.E01 cat '/Users/alice/Desktop/flag.txt'
target-fs evi/win.E01 cp '/Users/alice/Desktop/flag.txt' work/
target-fs evi/win.E01 walk /Users --recursive | rg -i 'flag|secret'
```

TSK 的 inode 级操作（Dissect 打不开或要恢复删除文件时）：

```bash
mmls evi/win.E01                             # 找 NTFS 分区起始扇区
fls -r -o 2048 evi/win.E01 | rg -i flag      # 列目录，-o 是分区偏移
icat -o 2048 evi/win.E01 <inode> > work/x    # 按 inode 取文件
fls -r -d -o 2048 evi/win.E01 | rg -i flag   # -d 只看已删除
tsk_recover -o work/recovered evi/win.E01    # 批量恢复删除文件
```

**Alternate Data Streams**（藏 flag 的经典位置）：

```bash
fls -r -o 2048 evi/win.E01 | rg ':'          # 带 :$DATA 的就是 ADS
icat -o 2048 evi/win.E01 <inode>-128-1 > work/ads
```

## 6. 浏览器历史

```bash
hindsight.py -i 'work/Users/alice/AppData/Local/Google/Chrome/User Data' \
             -o work/hindsight -f sqlite
hindsight.py -i 'work/Users/alice/AppData/Local/Microsoft/Edge/User Data' -o work/edge
```

输入要指向 **`User Data` 目录**（里面是 `Default/History`、`Default/Cookies`、
`Default/Login Data`），不是单个 `History` 文件。

没有 Hindsight 时的兜底：

```bash
sqlite3 -readonly work/.../History \
  'select datetime(last_visit_time/1000000-11644473600,"unixepoch") as t,url,title from urls order by t desc limit 30'
```

Chrome 时间戳是 **1601 纪元、微秒**，`/1000000-11644473600` 转 Unix。

`Local Storage/leveldb`、`IndexedDB`、`Session Storage` **不是 SQLite**，是 LevelDB：

```bash
ldb-dump 'work/Users/alice/AppData/Local/Google/Chrome/User Data/Default/Local Storage/leveldb'
ldb-dump '.../IndexedDB/https_example_com_0.indexeddb.leveldb' --grep flag
ldb-dump '.../leveldb' --deleted      # 已删除但还残留在 .ldb 里的记录
```

`ldb-dump` 纯 Python，能读 WAL 和 snappy 压缩块，并把删除记录标成 `DEL`。

## 7. 时间线

```bash
log2timeline.py --storage-file work/t.plaso evi/win.E01
psort.py -o work/timeline.csv work/t.plaso
psort.py -o work/timeline.csv work/t.plaso 'date > "2025-06-01"'
```

只要 MFT 时间线的话，Dissect 更快：

```bash
target-query -f mft.timeline evi/win.E01 > work/mft_timeline.txt
```

## 8. 坑

| 现象 | 原因 / 解法 |
|---|---|
| `ImportError: cannot import name '_Globber'` | Dissect 只支持到 Python 3.13，venv 必须是 3.12 |
| `target-query` 跑很久不出结果 | 插件输出巨大，先 `-f os` 探路，或加 `--csv` 重定向 |
| Dissect 说找不到 OS 插件 | 镜像里没有 Windows 系统卷（可能只有数据分区），走 TSK |
| BitLocker 卷打不开 | 需要恢复密钥：`target-info -K keychain.json` |
| `fls` 列出的路径怪 | 分区偏移 `-o` 没给对，先用 `mmls` 看起始扇区 |
| 时间差 8 小时 | EVTX/MFT 内部是 UTC，报告里要写清时区 |
| `hayabusa` 报没有规则 | `hayabusa update-rules`，或检查 `tools/hayabusa/rules/` |
| Chrome 历史时间全是 1601 年 | 正常，是 WebKit 纪元，见 §6 换算 |
| 注册表 hive 改了时间戳 | `regipy-parse-header` 看 hive 自己的 last written，不是文件 mtime |
