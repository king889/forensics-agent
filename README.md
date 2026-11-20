# forensic-agent

用 AI agent 做数字取证：**给定检材与题目，产出带证据定位的答案表**。

一套可复现的流水线，不是一次性问答：

```
检材(只读) → 解包 / 索引 → 题目切组 → 每组一个 agent 会话 → 答案 + 证据定位
```

---

## 目录

- [功能](#功能)
- [环境要求](#环境要求)
- [安装](#安装)
- [部署到另一台机器](#部署到另一台机器)
- [配置](#配置)
- [使用](#使用)
- [产物结构](#产物结构)
- [命令参考](#命令参考)
- [预置脚本](#预置脚本)
- [工具清单](#工具清单)
- [设计约定](#设计约定)
- [已知限制](#已知限制)
- [排错](#排错)

---

## 功能

### 支持自动化的检材读取

| 检材类型 | 读取方式 |
|---|---|
| E01 / RAW / VHD / VMDK / QCOW | sleuthkit 直读；或 `ffs`/`mmls` 定位分区后按偏移读 |
| 压缩包（zip/7z/rar） | 并行解包，落盘后按普通文件处理 |
| 手机备份（iOS / Android 目录） | 目录遍历生成清单 |
| Linux 镜像（ext4 / xfs / **LVM**） | `dissect` 免 root 读取；LVM thin pool 可切出 tmeta/tdata |
| 内存镜像（.raw / .mem） | Volatility 3 |
| APK | jadx / apktool + Frida |
| CAN 总线日志（.asc/.blf） | 内置统计脚本，无需 python-can |
| 无文件系统的私有格式 | 签名 carve（`binwalk` / PhotoRec / 内置 find-sqlite） |

### 分析与记录能力

- **检材索引**：一次性生成完整文件清单（2–100 万行），并派生
  `top-dirs` / `hives` / `ci-files` / `databases` / `media` / `ext-count` 分类清单
- **证据库**：SQLite 记录 `artifacts` / `findings` / `answers` / `attempts` / `groups` / `agents`
- **线索定位**：每条结论附 locator（帧号、inode、注册表路径、DB 主键、文件偏移）
- **原始输出留存**：每次工具调用的 stdout/stderr 落盘并计算 SHA-256
- **命令审计**：`meta/cmdlog.jsonl` 记录每条命令的时间、退出码、耗时、输出字节数
- **题组调度**：按组派活、依赖解锁、资源分池、超时终止、失败重试
- **简报生成**：每题注入题干、答案格式、检材读法、已有清单、已有线索、行为规约
- **候选表预计算**：极值/计数/端口/删除项类题，脚本先列全候选并排序
- **单题题解**：`meta/writeups/Q07.md` 含尝试记录、线索、死路

### 安全控制

| 控制 | 实现 |
|---|---|
| 检材只读 | `evi/` 目录 `chmod 555`，写入被拒 |
| 工具白名单 | `guard.ts` 只放行注册过的命令，拒绝安装/`sudo`/写 `evi/` |
| 危险命令拦截 | `find /`、对镜像 `grep -a`、逐 inode `icat` 循环等直接拒绝并给出替代写法 |
| 输出上限 | 单次输出截 3 KB，全文落盘；硬上限 64 MB 直接 kill |
| 超时 | 按工具分别设限（见 `config.json.tool_timeouts`），默认 180 s |
| 尝试预算 | 每次尝试最多 40 条命令，超出提示收敛 |
| 凭据隔离 | key 不进仓库，由 Pi 从 `~/.pi/agent/` 解析 |

---

## 环境要求

| 项 | 要求 |
|---|---|
| OS | Linux 或 WSL2（Ubuntu 22.04+ 验证） |
| Python | ≥ 3.11 |
| [Pi](https://github.com/badlogic/pi-mono) | 1.5.x |
| 磁盘 | 检材体积的 2 倍以上（解包 + 工作副本） |
| 内存 | 8 GB 起；解析内存镜像建议 16 GB+ |

必需工具：`fls` `icat` `mmls` `fsstat`（sleuthkit）、`7z`、`rg`、`sqlite3`、`file`

按需工具：`ffmpeg`（视频）、`volatility3`（内存）、`jadx`/`apktool`（APK）、
`dissect`（LVM/非标准镜像）、`thin_ls`（LVM thin pool）、`exiftool`、`zbarimg`

---

## 安装

> 从零到能跑的完整命令见 **[docs/quickstart.md](docs/quickstart.md)**
> （含 Pi 安装、工具分包、凭据、自检）。

```bash
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent
```

### 1. 宿主工具（自动识别发行版）

支持 **apt / dnf / yum / pacman / zypper / apk / brew**，各自有自己的包名表。

```bash
./setup.sh --list          # 看有哪些组
./setup.sh --check         # 只看装没装，不用 root
./setup.sh core disk       # 按组装（需要 root）
./setup.sh --all           # 全装

# 不想让它装，只要命令
./setup.sh --names core disk        # 只打印工具名，一行一个
./setup.sh --print core disk        # 只打印本机发行版的安装命令
./setup.sh --print-all disk         # 打印所有发行版的安装命令
./setup.sh --pm pacman core         # 指定包管理器
```

分组：`core` `disk` `win` `net` `image` `archive` `mobile` `timeline` `malware` `crypto`

完整工具清单（命令名 / 用途 / 各发行版包名 / 安装来源）见
**[docs/tools.md](docs/tools.md)**。

名字对不上时反查真实包名：

```bash
dnf provides '*/fls'        # Fedora / RHEL
pacman -F fls               # Arch
apt-file search bin/fls     # Debian / Ubuntu
```

### 2. 第三方工具（装进仓库 `tools/`，不污染系统）

```bash
tools/install.sh           # 系统包 + python + 官方 release（自动识别发行版）
tools/install.sh sys       # 只装系统包
tools/install.sh net       # 只装网络：scapy cyberchef zeek suricata tcpflow
tools/install.sh mem       # 只装内存：volatility3 vol2 MemProcFS yara 规则
tools/install.sh vehicle   # 只装车联网：python-can cantools udsoncan asammdf can-utils
tools/install.sh gh        # 只装 GitHub release：jadx dex2jar rizin ALEAPP
tools/install.sh ghidra    # 额外装 Ghidra（570 MB，需 JDK 21+）

tools/doctor.sh            # 逐个真跑一遍，确认能调用
```

装完入口在 `tools/bin/`，`bin/solve` 会自动加入 `PATH`。

### 3. 配模型

仓库不含任何 key。`config.json` 只声明用哪个 provider / 模型，
key 由 Pi 从环境变量或 `~/.pi/agent/auth.json` 解析。

**用哪家都行**，分两种情况：

```bash
# A. Pi 内置 provider（openai / anthropic / deepseek / gemini / openrouter /
#    groq / xai / moonshot / qwen / minimax / zai / github-copilot …）
#    不需要 models.json，配 key 就行
export DEEPSEEK_API_KEY=sk-...
pi auth login deepseek --api-key
# 然后 config.json: {"provider": "deepseek", "model": "deepseek-chat"}

# B. 自建 / 第三方 OpenAI 兼容网关，或本地 ollama / vLLM
mkdir -p ~/.pi/agent
cp templates/models.json ~/.pi/agent/models.json   # 改 baseUrl / apiKey / models[].id
export MYGATEWAY_API_KEY=...
# 然后 config.json: {"provider": "mygateway", "model": "vendor/model-name"}
```

完整说明（含内置 provider 表、本地模型、常见错法）见
[`docs/setup-credentials.md`](docs/setup-credentials.md)。

### 4. 自检

```bash
fcase doctor            # Python / 工具 / pi / 凭据 / 实际调用，一次查完
fcase doctor --no-net   # 只查配置，不花 token
```

---

## 部署到另一台机器

完整步骤见 **[docs/quickstart.md](docs/quickstart.md)**。最简一条线：

```bash
# Pi（官方安装脚本）
curl -fsSL https://pi.dev/install.sh | sh

# 仓库
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent

# 宿主工具（apt，需要 sudo）
./setup.sh core disk

# 第三方工具（装进仓库 tools/，不污染系统）
tools/install.sh

# 模型：内置 provider 举例（换成你在用的那家）
export DEEPSEEK_API_KEY="sk-xxx"
pi auth login deepseek --api-key
# 自定义网关 / 本地模型才需要：cp templates/models.json ~/.pi/agent/models.json

# 自检
fcase doctor
```

---

## 配置

### `config.json`

```json
{
  "_comment": "provider/model 换成你自己的，见 docs/setup-credentials.md",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "thinking": "off",
  "batch": 2,
  "jobs": 0,
  "attempt_max_calls": 40,
  "attempt_soft_deadline_s": 480,
  "stdout_preview_bytes": 3072,
  "tool_timeouts": { "fls": 300, "icat": 60, "volatility3": 900 }
}
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `provider` | — | provider 名：Pi 内置的（`openai` `anthropic` `deepseek` `gemini` `openrouter` …）或 `~/.pi/agent/models.json` 里自定义的 |
| `model` | — | 模型 ID，须属于该 provider；`fcase run --model` 可覆盖 |
| `thinking` | `off` | Pi 的思考档位：`off`/`minimal`/`low`/`medium`/`high` |
| `batch` | `2` | 组内一次做几题（共享一个会话）；越大越省冷启动，但上下文更长 |
| `jobs` | `0` | 并发组数；`0` = 按 `min(核数/2, 内存GB/1.2, 12)` 自动 |
| `attempt_max_calls` | `40` | 单次尝试最多执行多少条命令，超出提示收敛 |
| `attempt_soft_deadline_s` | `480` | 软超时，到时提示提交或标 blocked |
| `stdout_preview_bytes` | `3072` | 回给模型的输出预览大小；全文落盘 |
| `tool_timeouts` | 见上 | 按工具名设超时秒数；未列出的用 180 s |

改完不需要重启，下一次 `fcase run` 生效。

> 仓库里的 `provider` / `model` 是示例值，第一次用请先改成你自己能用的
> （内置 provider 只改这两行 + 配 key 即可）。

### 环境变量

| 变量 | 作用 |
|---|---|
| `FORENSICS_ROOT` | 仓库根目录（`bin/solve` 用它定位 skills / guard） |
| `FCASE_ROOT` | 显式指定 case 目录；不设则从 cwd 向上找 `meta/` |
| `CASE_DIR` | `internal/drive.sh` 使用，默认取 `pwd` |
| `CASES_ROOT` | `bin/case` 建目录的父路径，默认 `$HOME/cases` |
| `TOOLS_DIR` | 第三方工具安装位置，默认 `<repo>/tools` |

### 换模型 / 换 provider

改 `config.json` 即可，不用改代码。命令行参数优先于配置：

```bash
fcase run --provider openrouter --model anthropic/claude-sonnet-4.5
fcase go --jobs 8 --batch 3 --thinking low
```

也可以用环境变量临时切（不改文件）：

```bash
FCASE_PROVIDER=openai FCASE_MODEL=gpt-5 fcase run
```

---

## 两个会话，别混用

**开发会话**（改代码、看设计）和**做题会话**（跑 case、盯进度）分开，
否则每次监视进度都会把几十屏看板灌进开发上下文，两边都难受。

做题时开一个独立 tmux 会话，三个窗格：进度看板 / 日志 / shell：

```bash
cd ~/forensics-agent
bin/case-session /mnt/d/Cyber/Forensic/APK2026          # 只开会话
bin/case-session /mnt/d/Cyber/Forensic/APK2026 --run    # 顺便起 fcase run
```

```
┌──────────────────────┬──────────────┐
│ fcase board -w 5     │              │
├──────────────────────┤    shell     │
│ tail -F run.log      │              │
└──────────────────────┴──────────────┘
```

| 操作 | 命令 |
|---|---|
| 接入 | `tmux attach -t fcase-APK2026` |
| 离开（会话继续跑） | `Ctrl-b` 然后 `d` |
| 关闭 | `tmux kill-session -t fcase-APK2026` |

没有 tmux 就开两个终端：

```bash
# 终端 1
cd /path/to/case && fcase board -w 5     # 原地刷新，Ctrl-C 退出
# 终端 2
cd /path/to/case && fcase run
```

`fcase run` 本身是后台进程，关掉终端也会继续跑；
`fcase board -w` 只是看，不改变任何状态。

---

## 使用

### 五条命令

```bash
# 1. 建 case：检材软链进来，题目就位
fcase init ~/cases/c1 --evi /path/to/检材 --question /path/to/题目.md

# 2. 解包 + 建索引 + 生成文件清单（幂等，做过就跳过）
cd ~/cases/c1
fcase unpack

# 3. 开始做题（后台，每组建一个独立会话）
fcase run

# 4. 看进度
fcase board

# 5. 停止
fcase stop
```

`fcase run` 依次自动完成：登记检材 → 导入题目 → 没有分组则自动粗分 → 起调度循环。

### 题目文件格式

最简形式，一行一题：

```markdown
1. image.E01 里第一个分区的起始扇区是多少？
2. 该分区的文件系统类型是什么？
```

带分值/选项（常见比赛格式，支持 `#`/`##` 任意层级）：

```markdown
# 手机取证

## 1. 单选题（必答，10分）
分析 phone.E01，该手机安装了几款短视频应用？
- A. 1
- B. 2
- C. 3

## 2. 填空题（必答，10分）
该应用的包名是什么？
```

题目与检材的绑定规则（按优先级）：

1. 题干里带扩展名的完整文件名（如 `黄志远/phone.E01`、`image.E01`）
2. 加粗标注（`**phone.E01**`）
3. 中文简称 + 设备关键词（`分析林小婉手机`、`林小碗手表`，允许 1 字错别字）
4. 「接上题」继承上一题
5. 只用一个检材时自动绑定

都失败时 `fcase import --dry-run` 会标出来，可用 `--map "组名=检材路径"` 手动指定。

### 看进度与结果

```bash
fcase board            # 一屏进度：题号 / 状态 / 答案
fcase answers          # 全部答案
fcase answers --new    # 只看上次查看之后新增的
fcase why Q07          # 单题题解（含证据链、尝试记录、死路）
fcase agents           # 每个 agent 在跑哪题、上次命令多久前
fcase status           # 吞吐 / 工具耗时 / 超时与拦截统计
```

---

## 产物结构

```
~/cases/c1/
├── evi/                      原始检材（软链，目录锁 555）
├── work/                     解包产物、中间文件
├── artifacts/<检材>/
│   ├── INDEX.md              该检材是什么、怎么读
│   ├── fls-*.txt             完整文件清单（一次生成，全组复用）
│   ├── dirwalk.txt           目录型检材的文件清单
│   ├── target-walk.txt       LVM 检材经 dissect 生成的清单
│   ├── top-dirs.txt          目录速览（两层级聚合）
│   ├── hives.txt             注册表 hive / 事件日志
│   ├── ci-files.txt          凭据 / 配置类
│   ├── databases.txt         数据库 / 浏览器库
│   ├── media.txt             图片 / 视频 / 文档
│   ├── ext-count.txt         扩展名分布
│   └── README-HINT-*.txt     特殊读法（LVM、CAN 日志、私有格式）
└── meta/
    ├── question.md           题目
    ├── map.md / map.json     分组结果
    ├── answers.md            答案表（交卷用）
    ├── findings.md           线索（带定位符）
    ├── blocked.md            待人工处理的题
    ├── run.log               运行日志
    ├── drive.log             多轮调度日志
    ├── cmdlog.jsonl          命令审计
    ├── writeups/Q07.md       单题题解
    └── evidence.db           SQLite 真源
```

---

## 命令参考

### 主命令

| 命令 | 说明 |
|---|---|
| `fcase doctor [--no-net]` | 环境自检 |
| `fcase init <dir> [--evi D] [--question F]` | 新建 case |
| `fcase unpack [--force]` | 解包 + 索引 + 清单（幂等） |
| `fcase run [轮数]` | 后台做题（默认 10 轮） |
| `fcase board` | 进度看板 |
| `fcase stop` | 停止并复位 `doing` 状态 |

### 记录与查看

| 命令 | 说明 |
|---|---|
| `fcase answers [--new]` | 答案表 |
| `fcase why <QID>` | 单题题解，写入 `meta/writeups/` |
| `fcase agents` | agent 状态表 |
| `fcase status` | 遥测：吞吐、超时、病态命令计数 |
| `fcase ls` / `hash <f>` | 登记检材 / 计算 sha256 |
| `fcase note <kind> <text> [--q Q] [--locator L]` | 手工记线索 |
| `fcase answer <q> <a> [--evidence E] [--confidence C]` | 手工记答案 |
| `fcase deadend <text> [--q Q]` | 记死路，后续不再重走 |

### 索引与分组

| 命令 | 说明 |
|---|---|
| `fcase index <检材\|all>` | 生成检材索引（分区/文件系统/数据库清单） |
| `fcase deep-index <检材>` | 生成完整文件清单（fls / dissect walk / 目录遍历） |
| `fcase plan` | 生成分类模板，交给 agent 精细分组 |
| `fcase plan --apply` | 校验 `meta/map.json` 并入库 |
| `fcase plan --auto` | 按检材+连续题粗分（兜底） |
| `fcase brief <QID...>` | 手工重建简报 |

### 执行控制

| 命令 | 说明 |
|---|---|
| `fcase go [--jobs N] [--batch N] [--model M]` | 手动起一轮调度 |
| `fcase drive [轮数]` | 自动反复 `go` 直到做完 |
| `fcase unpack-all [--force]` | 并行解包全部压缩包 |
| `fcase extract <检材> [--grep RE] [--paths F] [-o D]` | 批量取文件（一次开镜像） |
| `fcase probe [QID...]` | 预计算候选表 |
| `fcase tools` | 列出可用工具与预置脚本 |

---

## 预置脚本

`scripts/` 下的脚本可独立使用，也可被 agent 调用：

| 脚本 | 用途 |
|---|---|
| `xor-decrypt.py <in> <out> --key K [--hex]` | XOR 解密 |
| `sqlite-dump.py <db> [--list] [--table T] [--sql Q]` | 只读查库 |
| `plist2json.py <plist> [-o out]` | plist 转 json（含二进制格式、越界 date 修复） |
| `find-sqlite.py <image> [--out D]` | 从无文件系统镜像按签名 carve SQLite |
| `hash-file.py <file...>` | 一次算 md5/sha1/sha256 |
| `can-asc-summary.py <asc> [--id HEX] [--window S]` | CAN 日志统计：报文周期/抖动/突发检测 |
| `lvm-thin-dump.py <image> --partition-lba N -o D` | 从 E01 解析 LVM2 元数据，切出 thin pool |
| `image-jigsaw.py <dir> [-o out] [--grid WxH]` | 碎片拼图（边缘匹配 + 二维生长） |

---

## 工具清单

按用途分类的完整清单见 **[docs/tools.md](docs/tools.md)**：每条列出命令名、
用途、apt / dnf / pacman 包名、安装来源（发行版仓库 / pip / GitHub release）。

速查：

```bash
./setup.sh --list                  # 组和说明
./setup.sh --check                 # 每组缺什么
./setup.sh --names disk            # 只打印命令名（自己装）
./setup.sh --print disk            # 打印本机安装命令
./setup.sh --print-all disk        # 打印所有发行版的安装命令
```

**必需**：`fls` `icat` `mmls` `fsstat`、`7z`、`rg`、`sqlite3`、`file`、`python3`

**按检材类型**：

| 检材 | 需要 |
|---|---|
| E01 / RAW / VHD / VMDK / QCOW | `disk` 组 |
| 内存镜像 | `tools/install.sh mem` |
| APK | `mobile` 组 + `tools/install.sh gh` |
| pcap | `net` 组 |
| Windows 镜像 | `win` 组 + `tools/install.sh win` |
| LVM / 非标准镜像 | `lvm2` + `dissect` |
| CAN 日志 | `tools/install.sh vehicle` |
| 视频 | `ffmpeg` |

**平台差异**：Linux 各发行版功能完整；macOS 通过 Homebrew 只能装用户态工具，
无 LVM / BitLocker / VSS，磁盘镜像类建议用 Linux 或 WSL2。

---

## 设计约定

**组是调度单位，题是提交单位。** 2–4 题一组，同组共享中间产物。
组太粗会被最长的那组拖住墙钟，可用 `fcase plan` 让 agent 重新切分。

**简报预载。** 每题开工前生成简报：题干、答案格式、检材读法、已有清单、
已有线索、行为规约。agent 拿到即开工，不需要先探索目录。

**索引用一次。** 每个检材的完整文件清单只生成一次，
后续所有题都在清单上检索，不重复扫描镜像。

**候选表由程序算。** 极值类题（最后/最早/唯一/哪一个）由脚本先列全候选并排序，
模型只负责解释选择，避免"看到第一个像样的就停"。

**尝试隔离。** `attempts` 只追加；简报只喂当前轮的线索，旧线索归档但可查。
重试不会继承上一轮的错误结论。

**输出有界。** 回给模型的输出截到 `stdout_preview_bytes`，全文落盘；
需要细节用 `fcase extract` 或用 `read` 打开落盘文件。

更多设计说明：[`docs/architecture.md`](docs/architecture.md)、
[`docs/workflow.md`](docs/workflow.md)。

---

## 已知限制

| 场景 | 状态 |
|---|---|
| LVM thin pool 中的 VM 磁盘 | 可切出 tmeta/tdata 并 `thin_ls`；若磁盘在 Ceph BlueStore 内需 ceph 工具 |
| 厂商私有格式（手表/固件） | 无公开解析器，只能签名 carve 或人工逆向 |
| VeraCrypt 容器 | WSL 缺内核 `cast5`/`blowfish`，`cryptsetup` 不可用；Linux 原生或 Windows 版可用 |
| 加密压缩包 | 依赖已知密码；未内置暴力破解流程 |
| 单色背景的碎片拼图 | 边缘匹配退化，不保证完美还原 |
| 离线运行 | 可接本地模型（ollama / vLLM，见 setup-credentials.md），但需足够上下文窗口 |
| macOS 做磁盘镜像 | 缺 LVM / BitLocker / VSS；用户态工具（文件/图片/APK/pcap）可用 |

---

## 排错

| 现象 | 处理 |
|---|---|
| `fcase run` 立即退出 | `fcase doctor` 看凭据/模型；`meta/run.log` 看具体错误 |
| `worker 无输出` | `pi --provider <p> --model <m> -p "回复 OK"` 手测 |
| 题一直 `blocked` | 看 `meta/blocked.md`：每条都带失败原因；API 类错误（402/401/429/余额）会单独标一节 |
| `blocked.md` 里有 402 / insufficient | 模型账号余额或额度问题，不是证据问题；`fcase doctor` 会直接报错因 |
| `该类别暂无工具支持` | `tools/install.sh` 装对应组 |
| 解包慢 | 大镜像写入耗时正常；`fcase unpack` 幂等，第二次秒过 |
| `/tmp` 满 | `/tmp` 可能是内存盘，把临时输出放 `~/scratch` |
| 检材路径报"逃逸检材根目录" | 检材必须位于 `evi/` 下 |
| `capinfos 解析失败` | 文件不是合法 pcap，先用 `fcase triage` 确认真实类型 |

---

## 许可

未指定。使用前请确认 `setup.sh` 与 `tools/install.sh` 中第三方工具各自的许可条款
（多为 GPL / Apache / MIT，部分商用工具需自行购买授权）。
