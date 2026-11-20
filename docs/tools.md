# 工具清单

按用途分类。**只想要名字**：`./setup.sh --names <组>`；
**想要安装命令**：`./setup.sh --print <组>`；**一次全打**：`./setup.sh --print-all`。

列说明：

- **apt** — Debian / Ubuntu / Kali
- **dnf** — Fedora / RHEL / Rocky / Alma（EPEL 需先 `dnf install epel-release`）
- **pacman** — Arch / Manjaro（标 `AUR` 的需 `yay -S`）
- **来源** — `仓库` = 发行版包；`pip`/`uv` = Python；`GH` = GitHub release（`tools/install.sh` 负责）

名字对不上时反查真实包名：

```bash
apt-file search bin/fls          # Debian/Ubuntu（先 apt install apt-file && apt-file update）
dnf provides '*/fls'             # Fedora/RHEL
pacman -F fls                    # Arch
zypper search --provides fls     # openSUSE
brew search fls                  # macOS
```

---

## core 基础

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `file` | 真实文件类型 | `file` | `file` | `file` | 仓库 |
| `jq` | JSON 处理 | `jq` | `jq` | `jq` | 仓库 |
| `rg` | 全文检索（清单里找线索的主力） | `ripgrep` | `ripgrep` | `ripgrep` | 仓库 |
| `fd` | 快速找文件 | `fd-find` | `fd-find` | `fd` | 仓库 |
| `xxd` | 十六进制查看 | `vim-common` | `vim-common` | `vim` | 仓库 |
| `hexedit` | 十六进制编辑（改副本用） | `hexedit` | `hexedit` | `hexedit` | 仓库 |
| `sqlite3` | 查库（浏览器/IM/应用数据） | `sqlite3` | `sqlite` | `sqlite` | 仓库 |
| `sqlcipher` | 加密 SQLite | `sqlcipher` | `sqlcipher` | `sqlcipher` | 仓库 |
| `python3` | 脚本 | `python3` | `python3` | `python` | 仓库 |
| `git` | 拉工具源码 | `git` | `git` | `git` | 仓库 |

## disk 磁盘镜像

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `mmls` `fls` `icat` `istat` `fsstat` `blkls` `mactime` `tsk_recover` | 分区/文件系统/文件提取/时间线 | `sleuthkit` | `sleuthkit` | `sleuthkit` | 仓库 |
| `ewfinfo` `ewfexport` `ewfverify` | E01 读取 | `ewf-tools` | `libewf-tools` | `libewf` | 仓库 |
| `affuse` `affinfo` | AFF 镜像 | `afflib-tools` | `afflib` | `afflib` | 仓库 |
| `ntfscat` `ntfsls` | NTFS 直读（sleuthkit 失败时兜底） | `ntfs-3g` | `ntfs-3g` | `ntfs-3g` | 仓库 |
| `testdisk` `photorec` | 分区修复 / 文件 carve | `testdisk` | `testdisk` | `testdisk` | 仓库 |
| `ddrescue` | 坏道镜像 | `gddrescue` | `ddrescue` | `ddrescue` | 仓库 |
| `dcfldd` | 取证级 dd（带哈希） | `dcfldd` | `dcfldd` | `dcfldd` | 仓库 |
| `cryptsetup` | LUKS / VeraCrypt | `cryptsetup` | `cryptsetup` | `cryptsetup` | 仓库 |
| `pvscan` `vgchange` `thin_ls` | LVM / thin pool | `lvm2` | `lvm2` | `lvm2` | 仓库 |
| `vhdiinfo` | VHD | `libvhdi-utils` | `libvhdi-tools` | `libvhdi` | 仓库/AUR |
| `vmdkinfo` | VMDK | `libvmdk-utils` | `libvmdk-tools` | `libvmdk` | 仓库/AUR |
| `qcowinfo` | QCOW | `libqcow-utils` | `libqcow-tools` | `libqcow` | 仓库/AUR |
| `vshadowinfo` | 卷影副本 | `libvshadow-utils` | `libvshadow-tools` | `libvshadow` | 仓库/AUR |
| `bdeinfo` | BitLocker | `libbde-utils` | `libbde-tools` | `libbde` | 仓库/AUR |
| `fvdeinfo` | FileVault | `libfvde-utils` | `libfvde-tools` | `libfvde` | 仓库/AUR |
| `fsntfsinfo` | NTFS 属性（$MFT/$UsnJrnl） | `libfsntfs-utils` | `libfsntfs-tools` | `libfsntfs` | 仓库/AUR |
| `dissect` | LVM / 非标准镜像免 root 读取 | — | — | — | pip |
| `thin_ls` `thin_dump` | LVM thin pool 解析 | `thin-provisioning-tools` | `thin-provisioning-tools` | `thin-provisioning-tools` | 仓库 |
| `bkcrack` | ZipCrypto 已知明文攻击 | — | — | — | GH |

## win Windows 取证

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `esedbexport` | ESE 数据库（SRUM/WPnd/WEBP 等） | `libesedb-utils` | `libesedb-tools` | `libesedb` | 仓库/AUR |
| `olecfexport` | OLE 复合文档（Outlook 等） | `libolecf-utils` | `libolecf-tools` | `libolecf` | 仓库/AUR |
| `regfexport` | 注册表 hive 导出 | `libregf-utils` | `libregf-tools` | `libregf` | 仓库/AUR |
| `reglookup` | 注册表查询 | `reglookup` | `reglookup` | `reglookup` | 仓库 |
| `regripper` | 注册表批量解析 | `regripper` | `regripper` | AUR | 仓库 |
| `evtx_dump` | 事件日志 | `python3-evtx` | `python3-evtx` | `python3-evtx` | 仓库 |
| `readpst` | Outlook PST | `pst-utils` | `libpst` | `libpst` | 仓库 |
| `pffexport` | Outlook 邮件目录 | `python3-pypff` | `python3-libpff` | AUR | 仓库 |
| `vinetto` | 缩略图缓存 | `vinetto` | `vinetto` | AUR | 仓库 |
| `pasco` | IE 缓存 | `pasco` | `pasco` | AUR | 仓库 |
| `galleta` | Cookie | `galleta` | `galleta` | AUR | 仓库 |
| `chainsaw` `hayabusa` | 事件日志威胁狩猎 | — | — | — | GH |
| `regipy-dump` | 注册表插件式解析（免装工具） | — | — | — | pip |

## net 网络取证

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `tshark` `capinfos` `editcap` `mergecap` | pcap 解析/统计/切分 | `tshark` | `wireshark-cli` | `wireshark-cli` | 仓库 |
| `tcpdump` | 抓包/粗读 | `tcpdump` | `tcpdump` | `tcpdump` | 仓库 |
| `tcpflow` | 按流重组 | `tcpflow` | `tcpflow` | `tcpflow` | 仓库 |
| `ngrep` | 包内文本检索 | `ngrep` | `ngrep` | `ngrep` | 仓库 |
| `tcpick` | 流还原成文件 | `tcpick` | `tcpick` | `tcpick` | 仓库 |
| `suricata` | IDS 规则匹配 | `suricata` | `suricata` | `suricata` | 仓库 |
| `netsniff-ng` | 高性能抓包 | `netsniff-ng` | `netsniff-ng` | `netsniff-ng` | 仓库 |
| `tcpreplay` | 回放 | `tcpreplay` | `tcpreplay` | `tcpreplay` | 仓库 |
| `zeek` | 协议日志化（conn/dns/http） | — | — | — | GH |
| `scapy` | Python 构造/解析报文 | `python3-scapy` | `python3-scapy` | `python-scapy` | 仓库/pip |
| `impacket` | SMB/Kerberos 解析 | `python3-impacket` | `python3-impacket` | AUR | 仓库/pip |

## image 图片与多媒体

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `exiftool` | EXIF/GPS/文档元数据 | `libimage-exiftool-perl` | `perl-Image-ExifTool` | `perl-image-exiftool` | 仓库 |
| `exiv2` | EXIF 读写 | `exiv2` | `exiv2` | `exiv2` | 仓库 |
| `jhead` | JPEG 头 | `jhead` | `jhead` | `jhead` | 仓库 |
| `identify` `convert` | 图像处理/批量比对 | `imagemagick` | `ImageMagick` | `imagemagick` | 仓库 |
| `pngcheck` | PNG 结构校验 | `pngcheck` | `pngcheck` | `pngcheck` | 仓库 |
| `zbarimg` | 二维码/条码 | `zbar-tools` | `zbar` | `zbar` | 仓库 |
| `qrencode` | 生成二维码 | `qrencode` | `qrencode` | `qrencode` | 仓库 |
| `steghide` | 隐写 | `steghide` | `steghide` | `steghide` | 仓库 |
| `zsteg` | PNG/BMP LSB 隐写 | — | — | — | gem |
| `foremost` | 文件 carve | `foremost` | `foremost` | `foremost` | 仓库 |
| `binwalk` | 固件/嵌套结构扫描 | `binwalk` | `binwalk` | `binwalk` | 仓库 |
| `ffmpeg` | 视频/音频抽帧抽轨 | `ffmpeg` | `ffmpeg` | `ffmpeg` | 仓库 |

## archive 归档

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `7z` | zip/7z/rar/iso 通用 | `7zip` | `p7zip` | `p7zip` | 仓库 |
| `unrar` | RAR | `unrar` | `unrar` | `unrar` | 仓库 |
| `cabextract` | CAB | `cabextract` | `cabextract` | `cabextract` | 仓库 |
| `unsquashfs` | squashfs | `squashfs-tools` | `squashfs-tools` | `squashfs-tools` | 仓库 |
| `lz4` `zstd` `cpio` `arj` | 各类压缩 | 同名 | 同名 | 同名 | 仓库 |
| `fcrackzip` | zip 口令爆破 | `fcrackzip` | `fcrackzip` | `fcrackzip` | 仓库 |
| `bkcrack` | ZipCrypto 已知明文 | — | — | — | GH |

## mobile 手机

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `adb` | Android 设备/备份 | `android-sdk-platform-tools` | `android-tools` | `android-tools` | 仓库 |
| `apktool` | APK 反编译 | `apktool` | `apktool` | AUR | 仓库/GH |
| `jadx` | APK 反编译成 Java | — | — | AUR | GH |
| `plistutil` | plist 解析 | `libplist-utils` | `libplist` | `libplist` | 仓库 |
| `ideviceinfo` | iOS 设备信息/备份 | `libimobiledevice-utils` | `libimobiledevice` | `libimobiledevice` | 仓库 |
| `aleapp` / `ileapp` | Android/iOS 解析套件 | — | — | — | GH |
| `frida` | 动态插桩 | — | — | — | pip |

## timeline 时间线

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `log2timeline.py` `psort.py` `pinfo.py` | plaso 全盘时间线 | `plaso` | `python3-plaso` | — | 仓库/pip |

## malware 恶意代码

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `yara` | 规则匹配 | `yara` | `yara` | `yara` | 仓库 |
| `radare2` / `rizin` | 二进制分析 | `radare2` | `radare2` | `radare2` | 仓库/GH |
| `scalpel` | 文件 carve | `scalpel` | `scalpel` | `scalpel` | 仓库 |
| `pefile` | PE 结构解析 | `python3-pefile` | `python3-pefile` | AUR | 仓库/pip |
| `olevba` `mraptor` | Office 宏 | — | — | — | pip（oletools） |
| `ghidra` | 反编译（需 JDK 21+） | — | — | — | GH（570MB） |
| `capa` | 能力识别 | — | — | — | pip |

## crypto 口令

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `hashcat` | GPU 破解 | `hashcat` | `hashcat` | `hashcat` | 仓库 |
| `john` | CPU 破解 | `john` | `john` | `john` | 仓库 |
| `fcrackzip` | zip 口令 | `fcrackzip` | `fcrackzip` | `fcrackzip` | 仓库 |
| `pdfcrack` | PDF 口令 | `pdfcrack` | `pdfcrack` | `pdfcrack` | 仓库 |

## vehicle 汽车 / CAN

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `asc2log` `log2asc` `candump` | can-utils，CAN 日志互转 | `can-utils` | `can-utils` | AUR | 仓库/GH |
| `cantools` `python-can` `udsoncan` `asammdf` | CAN/UDS 解析 | — | — | — | pip |

## 内存取证

| 命令 | 用途 | apt | dnf | pacman | 来源 |
|---|---|---|---|---|---|
| `vol` / `volatility3` | 内存镜像分析（主力） | — | — | — | pip（volatility3） |
| `vol.py` | Volatility 2（老 profile 镜像） | — | — | — | GH |
| `memprocfs` | 内存挂载成文件系统 | — | — | — | GH |

---

## 不在包管理器里的工具

这些用 `tools/install.sh` 装进仓库 `tools/`，不污染系统：

```bash
tools/install.sh            # 系统包 + python + 官方 release
tools/install.sh gh         # jadx / dex2jar / rizin / ALEAPP / apktool / protoc / sqlcipher / plaso / dissect / testdisk
tools/install.sh net        # scapy / cyberchef / zeek / suricata / tcpflow
tools/install.sh mem        # volatility3 / vol2 / MemProcFS / yara 规则
tools/install.sh vehicle    # python-can / cantools / udsoncan / asammdf / can-utils
tools/install.sh ghidra     # Ghidra（570MB，需 JDK 21+）
tools/install.sh sys        # 只装系统包（自动识别发行版）
```

装完入口在 `tools/bin/`，`bin/solve` 会自动加入 `PATH`。验证：`tools/doctor.sh`。

## 必需 / 可选

**必需**（没有它流水线跑不动）：`fls` `icat` `mmls` `fsstat`（sleuthkit）、`7z`、`rg`、`sqlite3`、`file`、`python3`

**按检材类型可选**：

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

## macOS 说明

Homebrew 能装用户态工具（sleuthkit、libewf、binwalk、exiftool、ffmpeg、yara、radare2、hashcat），
但**磁盘类不完整**：无 LVM、无 BitLocker/FileVault 解密、无 VSS。
磁盘镜像类检材建议用 Linux 或 WSL2；纯文件/图片/APK/网络类在 macOS 上可用。

```bash
brew install sleuthkit libewf binwalk exiftool ffmpeg yara radare2 hashcat john
```
