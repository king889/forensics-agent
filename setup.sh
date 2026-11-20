#!/usr/bin/env bash
# 按需装取证工具。自动识别包管理器：apt / dnf / yum / pacman / zypper / apk / brew。
#
#   ./setup.sh                       只看现状（不装、不用 root）
#   ./setup.sh --check [组...]       只检查装没装
#   ./setup.sh --list                看有哪些组
#   ./setup.sh --names [组...]       只打印工具名，一行一个（自己装）
#   ./setup.sh --print [组...]       只打印安装命令，不执行
#   ./setup.sh --print-all [组...]   打印所有发行版的安装命令
#   ./setup.sh --pm pacman [组...]   指定包管理器
#   ./setup.sh core disk             按组装（要 root）
#   ./setup.sh tshark exiftool       按命令名装
#   ./setup.sh --all                 全部组
#
# 名字对不上时用反查（脚本会自动提示）：
#   Debian/Ubuntu  apt-file search bin/<命令>      （apt-file 需先装）
#   Fedora/RHEL    dnf provides '*/<命令>'
#   Arch           pacman -F <命令>
#   openSUSE       zypper search --provides <命令>
#   Alpine         apk search <命令>
#   macOS          brew search <命令>
#
# 不在发行版仓库里的工具（volatility3 / jadx / ALEAPP / zeek …）用
#   tools/install.sh
# 装进本仓库的 tools/ 目录，不污染系统。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALL_GROUPS=(core disk win net image archive mobile timeline malware crypto)

# ---------------------------------------------------------------- 组说明

declare -A DESC=(
  [core]="基础：file jq rg fd xxd hexedit sqlite3 python"
  [disk]="磁盘：sleuthkit E01/AFF/VHD/VMDK/QCOW/VSS/BitLocker/FileVault LUKS LVM photorec"
  [win]="Windows：注册表 EDB OLE 事件日志 PST 回收站 快捷键 网页缓存"
  [net]="网络：tshark tcpdump tcpflow ngrep suricata netsniff tcpreplay"
  [image]="图片：exiftool exiv2 imagemagick binwalk steghide foremost zbar ffmpeg"
  [archive]="归档：7z unrar cabextract squashfs lz4 zstd arj"
  [mobile]="手机：adb apktool plist idevice"
  [timeline]="时间线：plaso（log2timeline）"
  [malware]="恶意代码：yara pefile radare2 scalpel"
  [crypto]="口令：hashcat john fcrackzip pdfcrack"
)

# 每组应该有的命令（--check 用，与包管理器无关）
declare -A BINS=(
  [core]="file jq rg fdfind xxd hexedit sqlite3 sqlcipher pip3"
  [disk]="mmls fls fsstat icat istat tsk_recover blkls mactime
          ewfinfo ewfexport ewfverify affuse affinfo
          ntfscat ntfsls testdisk photorec ddrescue dcfldd cryptsetup
          vshadowinfo bdeinfo fvdeinfo fsntfsinfo vhdiinfo vmdkinfo qcowinfo"
  [win]="esedbexport olecfexport regfexport reglookup regripper evtx_dump
         readpst vinetto pasco galleta"
  [net]="tshark capinfos editcap mergecap tcpdump tcpflow ngrep tcpick
         suricata netsniff-ng tcpreplay"
  [image]="exiftool exiv2 jhead identify convert pngcheck zbarimg qrencode
           steghide foremost binwalk ffmpeg zsteg"
  [archive]="7z unrar cabextract unsquashfs lz4 zstd cpio arj"
  [mobile]="adb apktool plistutil ideviceinfo"
  [timeline]="log2timeline.py psort.py pinfo.py"
  [malware]="yara radare2 scalpel"
  [crypto]="hashcat john fcrackzip pdfcrack"
)

# ---------------------------------------------------------------- 包名表
# 键是 "包管理器:组"。名字对不上的地方看文件末尾的反查提示。

declare -A PKGS=(
  # ---- Debian / Ubuntu
  [apt:core]="file jq ripgrep fd-find vim-common hexedit sqlite3 sqlcipher python3-pip python3-venv git"
  [apt:disk]="sleuthkit ewf-tools afflib-tools ntfs-3g testdisk gddrescue dcfldd cryptsetup lvm2
              libvhdi-utils libvmdk-utils libqcow-utils libvshadow-utils libbde-utils
              libfvde-utils libfsntfs-utils"
  [apt:win]="libesedb-utils libolecf-utils libregf-utils reglookup regripper
             python3-evtx pst-utils python3-pypff vinetto pasco galleta"
  [apt:net]="tshark tcpdump tcpflow ngrep tcpick suricata netsniff-ng tcpreplay python3-impacket"
  [apt:image]="libimage-exiftool-perl exiv2 jhead imagemagick pngcheck
               zbar-tools qrencode steghide foremost binwalk ffmpeg ruby"
  [apt:archive]="7zip unrar cabextract squashfs-tools lz4 zstd cpio arj"
  [apt:mobile]="android-sdk-platform-tools apktool libplist-utils libimobiledevice-utils"
  [apt:timeline]="plaso"
  [apt:malware]="yara python3-yara python3-pefile radare2 scalpel"
  [apt:crypto]="hashcat john fcrackzip pdfcrack"

  # ---- Fedora / RHEL / Rocky / Alma（EPEL 需先启用）
  [dnf:core]="file jq ripgrep fd-find vim-common hexedit sqlite sqlcipher python3-pip python3-devel git"
  [dnf:disk]="sleuthkit libewf-tools afflib ntfs-3g testdisk ddrescue dcfldd cryptsetup lvm2
              libvhdi-tools libvmdk-tools libqcow-tools libvshadow-tools libbde-tools
              libfvde-tools libfsntfs-tools"
  [dnf:win]="libesedb-tools libolecf-tools libregf-tools reglookup python3-evtx libpst
             python3-libpff vinetto pasco galleta"
  [dnf:net]="wireshark-cli tcpdump tcpflow ngrep tcpick suricata netsniff-ng tcpreplay"
  [dnf:image]="perl-Image-ExifTool exiv2 jhead ImageMagick pngcheck zbar qrencode
               steghide foremost binwalk ffmpeg"
  [dnf:archive]="p7zip p7zip-plugins unrar cabextract squashfs-tools lz4 zstd cpio arj"
  [dnf:mobile]="android-tools apktool libplist libimobiledevice"
  [dnf:timeline]="python3-plaso"
  [dnf:malware]="yara python3-yara python3-pefile radare2 scalpel"
  [dnf:crypto]="hashcat john fcrackzip pdfcrack"

  # ---- Arch / Manjaro
  [pacman:core]="file jq ripgrep fd vim hexedit sqlite sqlcipher python-pip git"
  [pacman:disk]="sleuthkit libewf afflib ntfs-3g testdisk ddrescue dcfldd cryptsetup lvm2"
  [pacman:win]="libesedb libolecf libregf reglookup python-evtx libpst vinetto pasco galleta"
  [pacman:net]="wireshark-cli tcpdump tcpflow ngrep tcpick suricata netsniff-ng tcpreplay"
  [pacman:image]="perl-image-exiftool exiv2 jhead imagemagick pngcheck zbar qrencode
                  steghide foremost binwalk ffmpeg"
  [pacman:archive]="p7zip unrar cabextract squashfs-tools lz4 zstd cpio arj"
  [pacman:mobile]="android-tools apktool libplist libimobiledevice"
  [pacman:malware]="yara radare2 scalpel"
  [pacman:crypto]="hashcat john fcrackzip pdfcrack"

  # ---- macOS（Homebrew，只有用户态工具，磁盘/LVM 类不全）
  [brew:core]="file jq ripgrep sqlite git"
  [brew:disk]="sleuthkit libewf afflib testdisk"
  [brew:net]="tcpdump tcpflow ngrep tcpreplay"
  [brew:image]="exiftool imagemagick binwalk ffmpeg zbar steghide"
  [brew:archive]="sevenzip unrar cabextract"
  [brew:mobile]="android-platform-tools apktool libplist libimobiledevice"
  [brew:malware]="yara radare2"
  [brew:crypto]="hashcat john"
)

# 发行版仓库里没有、或只有 AUR 的，给一句说明
declare -A NOTE=(
  [apt:timeline]="" [dnf:timeline]="" [pacman:timeline]="Arch 没有官方包，用 pipx install plaso 或 tools/install.sh plaso"
  [brew:timeline]="macOS 无 plaso，用 pipx install plaso"
  [pacman:disk]="libvhdi/libvmdk/libqcow/libvshadow/libbde/libfvde/libfsntfs 在 AUR（yay -S libvhdi ...）"
  [brew:disk]="macOS 缺 LVM / BitLocker / VSS 支持；磁盘类建议用 Linux 或 WSL2"
  [brew:win]="macOS 无 Windows 取证包，用 tools/install.sh win（纯 python 的 dissect）"
  [brew:vehicle]="macOS 无 can-utils，用 tools/install.sh vehicle（纯 python）"
  [pacman:vehicle]="can-utils 在 AUR，或 tools/install.sh vehicle"
)

# ---------------------------------------------------------------- 基础

have() { command -v "$1" >/dev/null 2>&1; }

detect_pm() {
    local p
    for p in apt-get dnf yum pacman zypper apk brew; do
        have "$p" && { echo "$p"; return; }
    done
    echo none
}

pm_key() {  # 表键名（apt-get→apt，yum→dnf）
    case $1 in
        apt-get) echo apt ;;
        yum)     echo dnf ;;
        *)       echo "$1" ;;
    esac
}

pm_label() {
    case $1 in
        apt-get) echo "Debian / Ubuntu" ;;
        dnf|yum) echo "Fedora / RHEL / Rocky / Alma" ;;
        pacman)  echo "Arch / Manjaro" ;;
        zypper)  echo "openSUSE" ;;
        apk)     echo "Alpine" ;;
        brew)    echo "macOS (Homebrew)" ;;
        *)       echo "未知" ;;
    esac
}

pm_install_cmd() {  # pm_install_cmd <pm> <pkgs...>  → 打印一行命令
    local pm=$1; shift
    [ $# -eq 0 ] && return 1
    case $pm in
        apt-get) echo "sudo apt-get install -y --no-install-recommends $*" ;;
        dnf)     echo "sudo dnf install -y $*" ;;
        yum)     echo "sudo yum install -y $*" ;;
        pacman)  echo "sudo pacman -Sy --needed --noconfirm $*" ;;
        zypper)  echo "sudo zypper install -y $*" ;;
        apk)     echo "sudo apk add $*" ;;
        brew)    echo "brew install $*" ;;
        *)       return 1 ;;
    esac
}

pm_search_hint() {  # pm_search_hint <pm> <名字>
    case $1 in
        apt-get) echo "apt-file search bin/$2   # 或 apt-cache search $2" ;;
        dnf|yum) echo "dnf provides '*/$2'" ;;
        pacman)  echo "pacman -F $2" ;;
        zypper)  echo "zypper search --provides $2" ;;
        apk)     echo "apk search $2" ;;
        brew)    echo "brew search $2" ;;
    esac
}

check_group() {
    local g=$1 miss=() ok=0 b
    for b in ${BINS[$g]}; do
        if have "$b"; then ok=$((ok + 1)); else miss+=("$b"); fi
    done
    printf '%-9s %2d ok  %2d 缺' "$g" "$ok" "${#miss[@]}"
    [ ${#miss[@]} -gt 0 ] && printf '  → %s' "${miss[*]}"
    printf '\n'
}

do_check() {
    local groups=("$@") g
    [ ${#groups[@]} -eq 0 ] && groups=("${ALL_GROUPS[@]}")
    printf '包管理器: %s (%s)\n\n' "$(detect_pm)" "$(pm_label "$(detect_pm)")"
    for g in "${groups[@]}"; do check_group "$g"; done
    echo
    printf '%-12s %s\n' vol "$(command -v vol || echo 缺)"
    printf '%-12s %s\n' regipy-dump "$(command -v regipy-dump || echo 缺)"
    printf '%-12s %s\n' olevba "$(command -v olevba || echo 缺)"
    printf '%-12s %s\n' zsteg "$(command -v zsteg || echo 缺)"
    printf '%-12s %s\n' fcase "$(command -v fcase || echo 缺)"
    echo
    echo "缺的装法：./setup.sh --print <组>    只看名字：./setup.sh --names <组>"
}

# ---------------------------------------------------------------- 参数

PM=""
MODE=install
[ $# -eq 0 ] && MODE=check

ARGS=()
while [ $# -gt 0 ]; do
    case $1 in
        --check)      MODE=check ;;
        --list)       for g in "${ALL_GROUPS[@]}"; do printf '%-9s %s\n' "$g" "${DESC[$g]}"; done; exit 0 ;;
        --names)      MODE=names ;;
        --print)      MODE=print ;;
        --print-all)  MODE=print_all ;;
        --pm)         shift; PM=${1:-} ;;
        --all|all)    ARGS+=("${ALL_GROUPS[@]}") ;;
        -h|--help)    sed -n '2,25p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *)            ARGS+=("$1") ;;
    esac
    shift
done

[ -z "$PM" ] && PM=$(detect_pm)
if [ "$PM" = none ]; then
    echo "⚠ 没找到包管理器（apt/dnf/pacman/zypper/apk/brew 都没有）"
    echo "  用 --names 拿工具名，自己装：./setup.sh --names ${ARGS[*]:-core disk}"
    [ "$MODE" = install ] && exit 1
fi

[ "$MODE" = check ] && { do_check "${ARGS[@]}"; exit 0; }

# 收集选中的组和单包
SEL_GROUPS=() WANT=()
for a in "${ARGS[@]}"; do
    if [ -n "${DESC[$a]:-}" ]; then
        SEL_GROUPS+=("$a")
    elif [ -n "${BINS[$a]:-}" ]; then
        SEL_GROUPS+=("$a")
    else
        WANT+=("$a")
    fi
done
[ ${#SEL_GROUPS[@]} -eq 0 ] && [ ${#WANT[@]} -eq 0 ] && SEL_GROUPS=(core disk)

pkgs_for() {  # pkgs_for <pm> <group> → 空格分隔的包名
    local k="$1:$2"
    echo "${PKGS[$k]:-}"
}

# ---------------------------------------------------------------- 名字模式

if [ "$MODE" = names ]; then
    # 打印命令名（不是包名），方便自己找包
    for g in "${SEL_GROUPS[@]}"; do
        echo "# $g —— ${DESC[$g]}"
        for b in ${BINS[$g]}; do echo "$b"; done
        echo
    done
    for w in "${WANT[@]}"; do echo "$w"; done
    exit 0
fi

# ---------------------------------------------------------------- 打印模式

if [ "$MODE" = print ] || [ "$MODE" = print_all ]; then
    if [ "$MODE" = print_all ]; then
        PM_LIST=(apt-get dnf pacman brew)
    else
        PM_LIST=("$PM")
    fi
    for pm in "${PM_LIST[@]}"; do
        echo "# ===== $(pm_label "$pm") ====="
        for g in "${SEL_GROUPS[@]}"; do
            list=$(pkgs_for "$(pm_key "$pm")" "$g")
            if [ -z "$list" ]; then
                note="${NOTE[$(pm_key "$pm"):$g]:-该发行版没有对应包}"
                echo "# $g —— $note"
                echo "#   工具名：$(echo ${BINS[$g]} | cut -c1-100)"
                continue
            fi
            echo "# $g —— ${DESC[$g]}"
            pm_install_cmd "$pm" $list
            [ -n "${NOTE[$(pm_key "$pm"):$g]:-}" ] && echo "# 注：${NOTE[$(pm_key "$pm"):$g]}"
        done
        if [ ${#WANT[@]} -gt 0 ]; then
            pm_install_cmd "$pm" "${WANT[@]}"
        fi
        echo
    done
    echo "# 名字对不上时反查：$(pm_search_hint "$PM" '<命令名>')"
    echo "# 发行版没有的工具：tools/install.sh"
    exit 0
fi

# ---------------------------------------------------------------- 装

run_install() {  # run_install <pm> <pkgs...>
    local pm=$1; shift
    [ $# -eq 0 ] && return 0
    case $pm in
        apt-get)
            sudo apt-get update -qq || echo "⚠ 有源失败，用旧索引继续"
            echo 'wireshark-common wireshark-common/install-setuid boolean false' \
                | sudo debconf-set-selections 2>/dev/null || true
            DEBIAN_FRONTEND=noninteractive \
                sudo apt-get install -y --no-install-recommends "$@" ;;
        dnf)    sudo dnf install -y "$@" ;;
        yum)    sudo yum install -y "$@" ;;
        pacman) sudo pacman -Sy --needed --noconfirm "$@" ;;
        zypper) sudo zypper install -y "$@" ;;
        apk)    sudo apk add "$@" ;;
        brew)   brew install "$@" ;;
    esac
}

TO_INSTALL=()
for g in "${SEL_GROUPS[@]}"; do
    echo "==> 组 $g：${DESC[$g]}"
    list=$(pkgs_for "$(pm_key "$PM")" "$g")
    if [ -z "$list" ]; then
        echo "    ⚠ $(pm_label "$PM") 没有 $g 的包表"
        [ -n "${NOTE[$(pm_key "$PM"):$g]:-}" ] && echo "      ${NOTE[$(pm_key "$PM"):$g]}"
        echo "      工具名：$(echo ${BINS[$g]} | cut -c1-110)"
        continue
    fi
    read -ra arr <<<"$list"
    TO_INSTALL+=("${arr[@]}")
    [ -n "${NOTE[$(pm_key "$PM"):$g]:-}" ] && echo "    注：${NOTE[$(pm_key "$PM"):$g]}"
done
TO_INSTALL+=("${WANT[@]}")
mapfile -t TO_INSTALL < <(printf '%s\n' "${TO_INSTALL[@]}" | awk 'NF && !seen[$0]++')

if [ ${#TO_INSTALL[@]} -eq 0 ]; then
    echo "没有可装的包。"
    echo "  看名字：./setup.sh --names ${SEL_GROUPS[*]:-core disk}"
    echo "  看命令：./setup.sh --print ${SEL_GROUPS[*]:-core disk}"
    exit 1
fi

echo "==> $(pm_label "$PM")：装 ${#TO_INSTALL[@]} 个包"
if ! run_install "$PM" "${TO_INSTALL[@]}"; then
    echo
    echo "⚠ 有包没装上。逐个反查真实包名："
    for p in "${TO_INSTALL[@]}"; do
        echo "    $p  →  $(pm_search_hint "$PM" "$p")"
    done
    echo "  也可以只拿名字自己装：./setup.sh --names ${SEL_GROUPS[*]:-core disk}"
fi

echo
echo "==> fcase 软链"
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bin/fcase" "$HOME/.local/bin/fcase"
chmod +x "$ROOT"/bin/* 2>/dev/null || true
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "⚠ $HOME/.local/bin 不在 PATH：export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo
do_check "${SEL_GROUPS[@]}"
