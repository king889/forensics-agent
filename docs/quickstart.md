# 部署到另一台机器

从零到能跑，完整命令。每段都可以直接整块复制。

- [Debian / Ubuntu / WSL2](#debian--ubuntu--wsl2)
- [Fedora / RHEL / Rocky / Alma](#fedora--rhel--rocky--alma)
- [Arch / Manjaro](#arch--manjaro)
- [openSUSE / Alpine](#opensuse--alpine)
- [macOS](#macos)
- [只想要工具名字](#只想要工具名字)

---

## 0. 前置包（一次性）

```bash
sudo apt-get update
sudo apt-get install -y \
  git curl ca-certificates build-essential \
  python3 python3-pip python3-venv
```

要求 Python ≥ 3.11：

```bash
python3 --version    # 低于 3.11 需要先升级
```

---

## 1. 装 Pi

```bash
curl -fsSL https://pi.dev/install.sh | sh

# 让 pi 进 PATH（写进 shell 配置，长期生效）
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/.local/bin:$PATH"

pi --version         # 期望 1.5.x
```

---

## 2. 拉仓库

```bash
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent
chmod +x bin/fcase bin/*.sh bin/internal/*.sh setup.sh tools/*.sh
```

---

## 3. 装宿主工具

```bash
./setup.sh --check                  # 先看缺什么（不需要 sudo）

# 必需
./setup.sh core disk

# 按检材类型追加
./setup.sh win                      # Windows：注册表/E01/事件日志/PST
./setup.sh net                      # 网络：tshark/tcpflow/suricata
./setup.sh image                    # 图片：exiftool/binwalk/zbar/ffmpeg
./setup.sh archive                  # 归档：7z/unrar/squashfs
./setup.sh mobile                   # 手机：adb/apktool/libimobiledevice
./setup.sh timeline                 # 时间线：plaso
./setup.sh crypto                   # 口令：hashcat/john
```

一次性全装：`./setup.sh --all`

---

## 4. 装第三方工具（装进仓库 `tools/`，不污染系统）

```bash
tools/install.sh                    # apt + python + GitHub release
```

按需分组：

```bash
tools/install.sh net                # zeek suricata tcpflow scapy cyberchef
tools/install.sh mem                # volatility3 vol2 MemProcFS yara 规则
tools/install.sh vehicle            # python-can cantools udsoncan asammdf can-utils
tools/install.sh gh                 # jadx dex2jar rizin ALEAPP
tools/install.sh ghidra             # Ghidra（570MB，需 JDK 21+）
```

装完验证：

```bash
tools/doctor.sh
```

---

## 5. 配模型凭据

Pi 需要 provider 定义 + key。仓库不含任何 key。

```bash
mkdir -p ~/.pi/agent

# 5.1 放 provider 定义（模板在仓库里）
cp templates/models.json ~/.pi/agent/models.json

# 5.2 二选一配 key
# 方式 A：环境变量（key 不落盘）
echo 'export OPENGATEWAY_API_KEY="你的key"' >> ~/.bashrc
source ~/.bashrc

# 方式 B：让 Pi 存（写进 ~/.pi/agent/auth.json）
pi auth login deepseek --api-key

# 5.3 验证
pi auth check --provider deepseek       # → ready
```

用别的厂商：编辑 `~/.pi/agent/models.json` 的 `_template` 段，
再把 `~/forensics-agent/config.json` 里的 `provider` / `model` 改成对应值。
详见 [setup-credentials.md](setup-credentials.md)。

---

## 6. 自检

```bash
cd ~/forensics-agent
./bin/fcase doctor
```

全部通过会输出「环境就绪」。有问题会逐条指出，例如：

```
✗ 凭据引用 $OPENGATEWAY_API_KEY，环境变量未设置且 auth.json 里也没有
    → export OPENGATEWAY_API_KEY=<你的 key> 或 pi auth login deepseek --api-key
```

只查配置不花 token：`./bin/fcase doctor --no-net`

---

## 7. 建 case 并开工

```bash
# 7.1 建 case（检材软链进来，题目就位）
./bin/fcase init ~/cases/c1 \
  --evi /path/to/检材目录 \
  --question /path/to/题目.md

# 7.2 解包 + 建索引 + 生成文件清单（幂等，做过就跳过）
cd ~/cases/c1
~/forensics-agent/bin/fcase unpack

# 7.3 开始做题（后台，每组建独立会话）
~/forensics-agent/bin/fcase run

# 7.4 看进度（另开一个终端 / tmux，别占着当前会话）
~/forensics-agent/bin/fcase board -w 5      # 原地刷新，Ctrl-C 退出
~/forensics-agent/bin/fcase answers --new

# 或者一次开好三个窗格（进度 / 日志 / shell）
~/forensics-agent/bin/case-session ~/cases/c1

# 7.5 停止
~/forensics-agent/bin/fcase stop
```

**建议把 `bin` 加进 PATH**，之后直接敲 `fcase`：

```bash
echo 'export PATH="$HOME/forensics-agent/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
fcase doctor
```

---

## 8. 一次装完（复制整块）

```bash
set -e

# 前置
sudo apt-get update
sudo apt-get install -y git curl ca-certificates build-essential \
                        python3 python3-pip python3-venv

# Pi
curl -fsSL https://pi.dev/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# 仓库
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent
chmod +x bin/fcase bin/*.sh bin/internal/*.sh setup.sh tools/*.sh
echo 'export PATH="$HOME/forensics-agent/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/forensics-agent/bin:$PATH"

# 宿主工具（需要 sudo 密码）
./setup.sh core disk win net image archive

# 第三方工具
tools/install.sh
tools/doctor.sh || true

# provider 定义
mkdir -p ~/.pi/agent
cp templates/models.json ~/.pi/agent/models.json

# key（改成你自己的）
echo 'export OPENGATEWAY_API_KEY="sk-xxxxxxxx"' >> ~/.bashrc
export OPENGATEWAY_API_KEY="sk-xxxxxxxx"

# 自检
fcase doctor
```

---

## Fedora / RHEL / Rocky / Alma

```bash
# 0. 前置（EPEL 提供不少取证包）
sudo dnf install -y epel-release
sudo dnf install -y git curl gcc gcc-c++ make python3 python3-pip python3-devel

# 1. Pi
curl -fsSL https://pi.dev/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# 2. 仓库
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent
chmod +x bin/fcase bin/*.sh bin/internal/*.sh setup.sh tools/*.sh
export PATH="$HOME/forensics-agent/bin:$PATH"

# 3. 工具（自动用 dnf）
./setup.sh core disk win net image archive

# 4. 第三方工具
tools/install.sh

# 5. 凭据
mkdir -p ~/.pi/agent && cp templates/models.json ~/.pi/agent/models.json
echo 'export OPENGATEWAY_API_KEY="你的key"' >> ~/.bashrc && source ~/.bashrc

# 6. 自检
fcase doctor
```

SELinux 若拦截读取，给检材目录打标或临时放宽：

```bash
sudo semanage fcontext -a -t user_home_t "/path/to/检材(/.*)?"
sudo restorecon -R /path/to/检材
```

## Arch / Manjaro

```bash
# 0. 前置
sudo pacman -Sy --needed --noconfirm base-devel git curl python python-pip

# 1. Pi
curl -fsSL https://pi.dev/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. 仓库
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent
chmod +x bin/fcase bin/*.sh bin/internal/*.sh setup.sh tools/*.sh
export PATH="$HOME/forensics-agent/bin:$PATH"

# 3. 工具（自动用 pacman）
./setup.sh core disk win net image archive

# 4. AUR 里的（需要 yay / paru）
yay -S --needed libvhdi libvmdk libqcow libvshadow libbde libfvde libfsntfs \
             apktool regripper plaso python-pypff vinetto pasco galleta can-utils

# 5. 第三方工具
tools/install.sh

# 6. 凭据 + 自检
mkdir -p ~/.pi/agent && cp templates/models.json ~/.pi/agent/models.json
echo 'export OPENGATEWAY_API_KEY="你的key"' >> ~/.bashrc && source ~/.bashrc
fcase doctor
```

## openSUSE / Alpine

没有内置包名表，用打印模式拿命令自己装：

```bash
./setup.sh --names core disk win net image archive    # 工具名
./setup.sh --print core disk                          # 安装命令（按本机包管理器生成）

# openSUSE 反查包名
zypper search --provides fls
# Alpine 反查
apk search sleuthkit
```

Alpine 是 musl + busybox，sleuthkit / libewf 等多数包存在但版本较旧；
内存与 Java 类工具（Ghidra、plaso）建议改用 glibc 发行版或容器。

## macOS

Homebrew 能装用户态工具，**磁盘类不完整**（无 LVM / BitLocker / VSS）。
纯文件、图片、APK、pcap 类检材可用；磁盘镜像建议 Linux 或 WSL2。

```bash
# 0. Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 1. Pi
curl -fsSL https://pi.dev/install.sh | sh

# 2. 仓库
git clone https://github.com/king889/forensics-agent.git ~/forensics-agent
cd ~/forensics-agent
chmod +x bin/fcase bin/*.sh bin/internal/*.sh setup.sh tools/*.sh
export PATH="$HOME/forensics-agent/bin:$PATH"

# 3. 工具（自动用 brew）
./setup.sh core disk net image archive mobile malware crypto

# 4. 第三方工具
tools/install.sh

# 5. 凭据 + 自检
mkdir -p ~/.pi/agent && cp templates/models.json ~/.pi/agent/models.json
echo 'export OPENGATEWAY_API_KEY="你的key"' >> ~/.zshrc && source ~/.zshrc
fcase doctor
```

macOS 上 `evi/` 的 `chmod 555` 保护生效，但注意 APFS 快照与 Spotlight 索引
可能改动访问时间；需要严格只读时把检材放只读挂载的 DMG 里。

## 只想要工具名字

不装、不跑脚本，只要清单：

```bash
./setup.sh --list                    # 组和说明
./setup.sh --names core disk         # 每组应有的命令名，一行一个
./setup.sh --names all               # 全部
./setup.sh --check                   # 对照本机，看缺哪个
```

完整对照表（命令名 / 用途 / apt / dnf / pacman 包名 / 来源）见
[tools.md](tools.md)。

反查真实包名：

```bash
apt-file search bin/fls      # Debian/Ubuntu
dnf provides '*/fls'         # Fedora/RHEL
pacman -F fls                # Arch
zypper search --provides fls # openSUSE
brew search fls              # macOS
```

---

## 装完先跑一遍冒烟测试

用 4 字节假检材 + 1 道题，验证 Pi、凭据、工具链、调度是否全通。约 30 秒。

```bash
mkdir -p /tmp/smoke/evi
printf '\xeb\x3c\x90DEMO' > /tmp/smoke/evi/a.img
printf '1. a.img 第一个字节（十六进制）？\n' > /tmp/smoke/q.md

fcase init /tmp/smoke/c --evi /tmp/smoke/evi --question /tmp/smoke/q.md
cd /tmp/smoke/c
fcase unpack
fcase run
fcase board
```

期望 `fcase board` 出现：

```
Q01 ✓ 填空   a.img 第一个字节（十六进制）？   0xEB (十进制 235)
进度 1/1  ★ 全答完
```

看到这个就说明：模型能调通、工具在白名单里、调度能派活、答案能落库。

没出现答案时按顺序看：

```bash
fcase doctor                     # 1. 凭据 / 余额 / 实际调用
cat meta/blocked.md              # 2. 失败原因（API 报错会原样贴出来）
cat artifacts/a/G1/logs/Q01.log  # 3. 该组的完整日志
```

`blocked.md` 里如果出现 `402 / insufficient / quota / 401 / 429` 这类字样，
说明是**模型账号的问题**（余额、额度、鉴权、限流），不是取证逻辑的问题 ——
`blocked.md` 会单独用一节把这类失败标出来。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `pi: command not found` | `export PATH="$HOME/.local/bin:$PATH"`，或重开终端 |
| `fcase: 找不到 case 目录` | 必须先 `cd` 到 case 目录，或 `export FCASE_ROOT=/path/to/case` |
| `doctor` 说 provider 未定义 | 第 5.1 步没做，或 `models.json` 里 provider 名与 `config.json` 不一致 |
| `doctor` 说凭据缺失 | 第 5.2 步没做；注意环境变量名要和 `models.json` 里的 `$XXX` 一致 |
| `setup.sh` 卡在密码 | 它需要 sudo，交互输入即可；非交互环境用 `sudo -v` 先缓存 |
| 解包很慢 | 大镜像写入耗时正常；`fcase unpack` 幂等，第二次秒过 |
| `/tmp` 满 | `/tmp` 可能是内存盘，把临时输出放 `~/scratch` |

---

## 磁盘与内存建议

| 项 | 建议 |
|---|---|
| 磁盘 | 检材体积 × 2 以上（解包 + 工作副本） |
| 内存 | 8 GB 起；解析内存镜像建议 16 GB+ |
| 检材位置 | 放本机磁盘（NTFS/exFAT 经 9p 挂载时随机读很慢，会拖慢 `fls`） |
| swap | 至少 8 GB，避免 Volatility 峰值把进程杀掉 |
