# 扩展

v2 的扩展几乎全是「加一个 md 文件」。

## 加一个技能

技能就是一个目录 + `SKILL.md`：

```
skills/
└── registry/
    └── SKILL.md
```

```markdown
---
name: registry
description: 分析 Windows 注册表 hive —— SAM/SECURITY/SYSTEM/NTUSER，提取用户、密码哈希、启动项、USB 历史。遇到 .hiv/.dat/.reg 或 Windows 镜像时加载。
---

# 注册表

## 1. 先看有哪些 hive
...
```

两条要求：

1. **`description` 写清「做什么 + 什么时候用」** —— 模型靠这句话决定要不要加载。
   写 "Helps with registry" 等于没写。
2. **命令要能直接复制跑** —— 不要写"用工具分析"，写具体命令和具体参数。

写完直接生效，`bin/ask` 每次启动都会重新扫描 `skills/`。

### 值得补的技能

| 技能 | 工具 | 覆盖题型 |
|---|---|---|
| `linux` | journalctl 导出 / bash_history | Linux 主机取证 |
| `crypto` | 钱包文件、密钥 | 区块链/加密货币 |
| `network` | zeek / suricata 日志 | 非 pcap 的网络日志（pcap 在 `pcap` 技能里） |
| `email` | eml / pst | 邮件 |
| `cloud` | 浏览器 IndexedDB / 云盘缓存 | 云同步痕迹 |

已完成：`windows`（Dissect + Regipy + Hayabusa）、`android`（jadx/rizin/Ghidra）、
`memory`（Vol3 + Vol2 + MemProcFS + YARA）、`vehicle`（python-can + cantools + can-utils + asammdf）。

## 加一个工具

两条路，优先第二条。

**① 宿主机 apt（要 sudo）** —— 通用小工具

```bash
./setup.sh <包名或命令名>      # 按需装，不带参数只看现状
```

写进 `setup.sh` 的 `PKGS` 和 `BINS`（命令名和包名不同就加到 `ALIAS`）。

**② 装进仓库 `tools/`（不要 sudo）** —— 大件、版本敏感、会跟系统打架的

在 `tools/install.sh` 加一个 `sec_xxx()`，然后挂到 `SECTIONS` 和 `case` 分支。

**`tools/bin` 只放取证入口，一个都不要多。** 别写 `for t in venv/bin/*; do ln -sf ...`——那会把
`activate.fish`、`python3.14`、`ipython`、`bottle.py`、`𝜋thon` 全倒进来（`tools/bin` 曾在 PATH 最前面时
把 `python` 抢走，很危险）。按名字列白名单：`for t in target-query regipy-dump ...; do`。
现在 135 个入口，加之前先问一句「agent 会直接敲这个命令吗」。

没有 sudo 也能拿到 deb 里的东西，这套已经用了很多次：

```bash
# 只下载不安装，解到指定目录
apt-get download libzmq5                    # 走 apt 的索引，不用 root
dpkg-deb -x libzmq5_*.deb tools/zeek/       # 相当于装到自定义前缀
dpkg-deb -f xxx.deb Depends                 # 先看依赖，别盲解

# 头文件也能这么来（源码编译时当 -I 用）
dpkg-deb -x libpcap0.8-dev_*.deb /tmp/pcapdev
CPPFLAGS="-I/tmp/pcapdev/usr/include" ./configure ...
```

实在要用 `-l` 链接但系统只有 `libfoo.so.1` 没有 `libfoo.so` 时：

```bash
mkdir -p /tmp/liblink
src=$(ls -1 /usr/lib/x86_64-linux-gnu/libfoo.so.* | head -1)   # 只取一个，别用通配
ln -sf "$src" /tmp/liblink/libfoo.so
```

装完两件事必做：

1. 在 `tools/doctor.sh` 的 `LIST` 里加一行 `"命令|探活参数|说明"`，
   **参数要让它真的跑一次**，只 `command -v` 没意义
2. 在相关技能的 `## 0` 里加一句检查

不需要改 `bin/fcase`，也不需要重建任何东西。

Python 工具用 `uv tool install <包>`，别用 `pip install`（PEP 668 会挡）。

## 改行为规约

`prompts/agent.md`。改完直接生效。

改的时候注意：**规约是唯一能约束模型行为的地方**（v2 没有技术强制），
所以宁短勿长 —— 太长模型会忽略。

## 改 add / unpack

`bin/add`（bash，70 行）：evi 的软链与锁。
`bin/unpack`（python，230 行）：解包防护。

`unpack` 里改限制时注意：`check()` 在解压**之前**跑，`expand()` 递归时
`budget` 是跨嵌套层累加的 —— 别只改单层上限。

## setup.sh 的坑

- **别用 `GROUPS` 当变量名** —— bash 保留变量，赋值静默失效
- **别用 `apt-cache policy | grep -q`** —— `pipefail` 下 grep 提前退出让
  apt-cache 收 SIGPIPE（141），整条管道判失败，表现为"所有包都不存在"
- 默认不装任何东西，参数可以是包名、组名，或命令名（走 `ALIAS` 映射）

## 改记录层

`bin/fcase`，300 行，只用 stdlib。改完记得：

```bash
fcase --help
cd $CASES_ROOT/test && fcase status   # 别把现有 db 弄坏
```

schema 变更时加 `ALTER TABLE` 或者写迁移，不要直接改 `SCHEMA` 就完事 ——
已有的 `evidence.db` 不会自动跟着变。

## 调 Pi 的行为

| 想改什么 | 改哪里 |
|---|---|
| 模型 | `~/.pi/agent/settings.json` 的 `defaultModel`，或 `ask --model` |
| 系统提示 | `prompts/agent.md` |
| 技能 | `skills/<name>/SKILL.md` |
| 让模型只能看不能写 | `ask` 里加 `--tools read,bash,rg` |
| 加 MCP 服务器 | `pi mcp add <name> -- <command>` |

MCP 对取证的价值目前不大 —— 大部分活是「跑一个 CLI 工具，读它的输出」，
Pi 内置的 `bash` + `rg` + `read` 已经够。真需要时再加（比如 sqlite MCP
用来查 `evidence.db` 和手机 app 数据库）。

## 排查

| 现象 | 原因 |
|---|---|
| `fcase: 找不到 case 目录` | 当前目录没有 `meta/`，或 `FCASE_ROOT` 指错 |
| 技能没被加载 | `--skill` 路径不对，或 `SKILL.md` 的 frontmatter 缺 `name`/`description` |
| `ask` 挂住不动 | 在管道里跑时没有 TTY。`ask` 已自动加 `-p`，手动跑 `pi` 时要自己加 |
| 模型不用技能 | `description` 太模糊。改成「做什么 + 什么时候用」 |
| 工具找不到 | `./setup.sh --check` |
