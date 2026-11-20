#!/usr/bin/env bash
# 把 Android / 移动取证工具装到本仓库的 tools/ 目录里（不污染系统）。
#
#   tools/install.sh              装 apt + python + 官方 release（不含 ghidra）
#   tools/install.sh venv         只装 python 工具
#   tools/install.sh gh           只装 GitHub release（jadx/dex2jar/rizin/ALEAPP）
#   tools/install.sh ghidra       额外装 Ghidra（570MB，需要 JDK 21+）
#   tools/install.sh apt          只装 apt 包（要 sudo）
#   tools/install.sh net          网络取证：scapy / cyberchef / zeek / suricata / tcpflow
#   tools/install.sh mem          内存取证：volatility3 / vol2 / MemProcFS / yara 规则
#   tools/install.sh vehicle      汽车取证：python-can / cantools / udsoncan / asammdf / can-utils
#
# 装完在 tools/bin/ 下都有入口，bin/ask 会自动把它加到 PATH。
# 验证：tools/doctor.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${TOOLS_DIR:-$ROOT/tools}"
BIN="$TOOLS/bin"
DL="$TOOLS/_dl"
mkdir -p "$TOOLS" "$BIN" "$DL"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '    \033[33m⚠\033[0m    %s\n' "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

# 下载并校验不是 HTML 错误页
dl() {
    local url=$1 out=$2
    if [ -s "$out" ]; then ok "已缓存 $(basename "$out")"; return 0; fi
    curl -fsSL --retry 3 --retry-delay 2 --max-time 900 -o "$out.part" "$url" \
        && mv "$out.part" "$out" && ok "$(basename "$out") ($(du -h "$out" | cut -f1))"
}

# 用 7z 解 zip，避免依赖 unzip
unzip_to() {  # unzip_to <zip> <destdir>
    rm -rf "$2" && mkdir -p "$2" && 7z x -y -bso0 -bsp0 -o"$2" "$1" >/dev/null
}

# 把目录里唯一的顶层目录提上来（github zip 都套一层）
flatten() {  # flatten <dir>
    local d=$1 n
    n=$(find "$d" -mindepth 1 -maxdepth 1 | wc -l)
    if [ "$n" -eq 1 ] && [ -d "$(find "$d" -mindepth 1 -maxdepth 1)" ]; then
        local inner; inner=$(find "$d" -mindepth 1 -maxdepth 1)
        shopt -s dotglob
        mv "$inner"/* "$d"/ 2>/dev/null
        shopt -u dotglob
        rmdir "$inner" 2>/dev/null
    fi
}

# ---------------------------------------------------------------- apt

sec_apt() {
    say "apt 包"
    local pkgs=(openjdk-21-jdk-headless apktool android-sdk-libsparse-utils
                protobuf-compiler libleveldb-dev python3-dev python3-venv
                build-essential curl wget git testdisk foremost sqlcipher
                radare2 libimage-exiftool-perl sqlite3 yara binutils)
    local avail=() missing=()
    for p in "${pkgs[@]}"; do
        local pol; pol=$(apt-cache policy "$p" 2>/dev/null)
        if grep -q 'Candidate: [^(]' <<<"$pol"; then avail+=("$p"); else missing+=("$p"); fi
    done
    [ ${#missing[@]} -gt 0 ] && warn "仓库里没有: ${missing[*]}"
    sudo apt-get update -qq || warn "apt update 有源失败，用旧索引继续"
    DEBIAN_FRONTEND=noninteractive sudo apt-get install -y --no-install-recommends "${avail[@]}"
}

# ---------------------------------------------------------------- python

sec_venv() {
    say "python 工具 → $TOOLS/venv"
    if [ ! -x "$TOOLS/venv/bin/python" ]; then
        python3 -m venv "$TOOLS/venv" || { warn "venv 建失败（要 python3-venv）"; return 1; }
    fi
    local pip="$TOOLS/venv/bin/pip"
    "$pip" install -q --upgrade pip wheel >/dev/null 2>&1
    # plyvel 要 libleveldb-dev，没装就跳过它
    local want=(androguard apkid apkleaks pyaxmlparser frida-tools
                sqlite-dissect bbpb blackboxprotobuf)
    if [ -f /usr/include/leveldb/db.h ]; then want+=(plyvel); else
        warn "没 libleveldb-dev，跳过 plyvel（apt 组里有）"
    fi
    "$pip" install -q "${want[@]}" 2>&1 | tail -5

    # sqlite-dissect 用了 python3.14 删掉的 sqlite3.version
    local sd="$TOOLS/venv/lib/python"*/site-packages/sqlite_dissect/export/sqlite_export.py
    for f in $sd; do
        [ -f "$f" ] && sed -i 's/^from sqlite3 import version$/from sqlite3 import sqlite_version as version/' "$f"
    done
    local n=0
    for f in "$TOOLS/venv/bin"/*; do
        local b; b=$(basename "$f")
        case $b in python*|pip*|[Aa]ctivate*) continue ;; esac
        [ -x "$f" ] && { ln -sf "$f" "$BIN/$b"; n=$((n + 1)); }
    done
    ok "venv 工具 $n 个已链到 tools/bin"
}

# ---------------------------------------------------------------- github release

sec_jadx() {
    say "jadx（DEX → Java）"
    if [ -x "$TOOLS/jadx/bin/jadx" ]; then ok "已装"; return; fi
    local v=v1.5.6
    dl "https://github.com/skylot/jadx/releases/download/$v/jadx-${v#v}.zip" "$DL/jadx.zip" || return 1
    unzip_to "$DL/jadx.zip" "$TOOLS/jadx" && chmod +x "$TOOLS/jadx/bin/"*
    ln -sf "$TOOLS/jadx/bin/jadx" "$BIN/jadx"
    ln -sf "$TOOLS/jadx/bin/jadx-gui" "$BIN/jadx-gui"
    ok "jadx $v"
}

sec_dex2jar() {
    say "dex2jar（DEX → JAR）"
    if [ -x "$TOOLS/dex2jar/d2j-dex2jar.sh" ]; then ok "已装"; return; fi
    dl "https://github.com/pxb1988/dex2jar/releases/download/v2.4/dex-tools-v2.4.zip" "$DL/dex2jar.zip" || return 1
    unzip_to "$DL/dex2jar.zip" "$TOOLS/dex2jar" && flatten "$TOOLS/dex2jar"
    chmod +x "$TOOLS/dex2jar"/*.sh
    ln -sf "$TOOLS/dex2jar/d2j-dex2jar.sh" "$BIN/dex2jar"
    ln -sf "$TOOLS/dex2jar/d2j-dex2jar.sh" "$BIN/d2j-dex2jar"
    ok "dex2jar v2.4"
}

sec_rizin() {
    say "rizin（二进制逆向）"
    if [ -x "$BIN/rizin" ] && [ -e "$BIN/rizin" ]; then ok "已装"; return; fi
    # linux 只有 static 包，131MB
    dl "https://github.com/rizinorg/rizin/releases/download/v0.9.1/rizin-v0.9.1-static-x86_64.tar.xz" "$DL/rizin.tar.xz" || return 1
    rm -rf "$TOOLS/rizin" && mkdir -p "$TOOLS/rizin"
    # 不能 --strip-components：tar 里是 bin/ lib/ share/，剥掉后 bin/rizin
    # 会和 share/rizin 目录撞名，真正的二进制就丢了
    tar xJf "$DL/rizin.tar.xz" -C "$TOOLS/rizin" || { warn "解压失败"; return 1; }
    # static 包的布局是扁平的：tools/rizin/rizin，不是 bin/rizin
    local rb="$TOOLS/rizin/bin/rizin"
    [ -x "$rb" ] || rb=$(find "$TOOLS/rizin" -maxdepth 3 -type f -name rizin -perm -u+x | head -1)
    if [ -z "$rb" ]; then warn "没找到 rizin 二进制"; return 1; fi
    ln -sf "$rb" "$BIN/rizin"
    for t in rz-bin rz-asm rz-hash rz-find rz-gg; do
        [ -x "$TOOLS/rizin/bin/$t" ] && ln -sf "$TOOLS/rizin/bin/$t" "$BIN/$t"
    done
    ok "rizin v0.9.1"
}

sec_aleapp() {
    say "ALEAPP（Android 全盘解析）"
    if [ -x "$TOOLS/aleapp/ALEAPP.AppImage" ]; then ok "已装"; return; fi
    local url="https://github.com/abrignoni/ALEAPP/releases/download/v2026.4.5/ALEAPP-2026.4.5-linux-x64.AppImage"
    mkdir -p "$TOOLS/aleapp"
    dl "$url" "$TOOLS/aleapp/ALEAPP.AppImage" || return 1
    chmod +x "$TOOLS/aleapp/ALEAPP.AppImage"
    ln -sf "$TOOLS/aleapp/ALEAPP.AppImage" "$BIN/aleapp"
    ok "ALEAPP v2026.4.5（AppImage，自带 python）"
}

sec_ileapp() {
    say "iLEAPP（iOS 全盘解析，纯本地，运行时不联网）"
    if [ -x "$TOOLS/venv-ios/bin/python" ] && [ -f "$TOOLS/iLEAPP/ileapp.py" ]; then ok "已装"; return; fi
    command -v git >/dev/null || { warn "缺 git"; return 1; }
    if [ ! -d "$TOOLS/iLEAPP/.git" ]; then
        git clone --depth 1 https://github.com/abrignoni/iLEAPP.git "$TOOLS/iLEAPP" || return 1
    fi
    uv venv "$TOOLS/venv-ios" --python 3.12 || return 1
    uv pip install --python "$TOOLS/venv-ios/bin/python" -r "$TOOLS/iLEAPP/requirements.txt" || return 1
    cat > "$BIN/ileapp" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
exec "$ROOT/venv-ios/bin/python" "$ROOT/iLEAPP/ileapp.py" "$@"
WRAP
    chmod +x "$BIN/ileapp"
    ok "iLEAPP $(cd "$TOOLS/iLEAPP" && git log -1 --format=%cd --date=short)"
}

sec_bring2lite() {
    say "bring2lite"
    # 上游只有 tkinter GUI，没有 CLI —— agent 用不了。用 sqlite-dissect 替代。
    warn "bring2lite 是 GUI-only（from classes.gui import GUI），跳过；用 sqlite-dissect"
}

sec_jdk() {
    say "JDK 25（Temurin，自带，不碰系统 java；Ghidra 12 要求 25+）"
    if [ -x "$TOOLS/jdk/bin/java" ]; then ok "已装"; return; fi
    local url="https://api.adoptium.net/v3/binary/latest/25/ga/linux/x64/jdk/hotspot/normal/eclipse"
    dl "$url" "$DL/jdk.tar.gz" || return 1
    rm -rf "$TOOLS/jdk" && mkdir -p "$TOOLS/jdk"
    tar xzf "$DL/jdk.tar.gz" -C "$TOOLS/jdk" --strip-components=1 || { warn "解压失败"; return 1; }
    for b in java javac jar; do
        [ -x "$TOOLS/jdk/bin/$b" ] && ln -sf "$TOOLS/jdk/bin/$b" "$BIN/$b"
    done
    ok "JDK $("$TOOLS/jdk/bin/java" -version 2>&1 | head -1 | cut -d'"' -f2)"
}

sec_apktool() {
    say "apktool（APK 解包，jar 版，不依赖 apt）"
    if [ -f "$TOOLS/apktool/apktool.jar" ]; then ok "已装"; return; fi
    mkdir -p "$TOOLS/apktool"
    dl "https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar" \
        "$TOOLS/apktool/apktool.jar" || return 1
    cat > "$BIN/apktool" <<EOF
#!/bin/sh
JAVA="$TOOLS/jdk/bin/java"
[ -x "\$JAVA" ] || JAVA=java
exec "\$JAVA" -jar "$TOOLS/apktool/apktool.jar" "\$@"
EOF
    chmod +x "$BIN/apktool"
    ok "apktool v3.0.3"
}

sec_platformtools() {
    say "Android platform-tools（adb / fastboot）"
    if [ -x "$TOOLS/platform-tools/adb" ]; then ok "已装"; return; fi
    dl "https://dl.google.com/android/repository/platform-tools-latest-linux.zip" \
        "$DL/platform-tools.zip" || return 1
    unzip_to "$DL/platform-tools.zip" "$TOOLS/platform-tools" && flatten "$TOOLS/platform-tools"
    chmod +x "$TOOLS/platform-tools/"*
    for b in adb fastboot; do
        [ -x "$TOOLS/platform-tools/$b" ] && ln -sf "$TOOLS/platform-tools/$b" "$BIN/$b"
    done
    ok "adb $("$TOOLS/platform-tools/adb" version 2>&1 | head -1)"
}

sec_protoc() {
    say "protoc（Protobuf 编译器）"
    if [ -x "$TOOLS/protoc/bin/protoc" ]; then ok "已装"; return; fi
    dl "https://github.com/protocolbuffers/protobuf/releases/download/v36.2/protoc-36.2-linux-x86_64.zip" \
        "$DL/protoc.zip" || return 1
    unzip_to "$DL/protoc.zip" "$TOOLS/protoc" && chmod +x "$TOOLS/protoc/bin/protoc"
    ln -sf "$TOOLS/protoc/bin/protoc" "$BIN/protoc"
    ok "protoc v36.2"
}

sec_simg2img() {
    say "simg2img（Android sparse → raw，现场编译）"
    if [ -x "$TOOLS/simg2img/simg2img" ]; then ok "已装"; return; fi
    have g++ || { warn "没有 g++，跳过"; return 1; }
    if [ ! -d "$TOOLS/simg2img/.git" ]; then
        git clone -q --depth 1 https://github.com/anestisb/android-simg2img "$TOOLS/simg2img" \
            || { warn "clone 失败"; return 1; }
    fi
    ( cd "$TOOLS/simg2img" && make -s >/dev/null 2>&1 ) || { warn "编译失败"; return 1; }
    for b in simg2img simg2simg img2simg; do
        [ -x "$TOOLS/simg2img/$b" ] && ln -sf "$TOOLS/simg2img/$b" "$BIN/$b"
    done
    ok "simg2img（另带 simg2simg / img2simg）"
}

sec_sqlcipher() {
    say "sqlcipher（加密 SQLite）"
    if [ -x "$BIN/sqlcipher" ]; then ok "已装"; return; fi
    [ -x "$TOOLS/venv/bin/pip" ] || { warn "先跑 tools/install.sh venv"; return 1; }
    "$TOOLS/venv/bin/pip" install -q sqlcipher3-binary 2>&1 | tail -3
    # 源码在 tools/sqlcipher.py（跟着仓库走），bin 里只放转发脚本
    [ -f "$TOOLS/sqlcipher.py" ] || { warn "缺 tools/sqlcipher.py"; return 1; }
    cat > "$BIN/sqlcipher" <<EOF
#!/bin/sh
exec "$TOOLS/venv/bin/python" "$TOOLS/sqlcipher.py" "\$@"
EOF
    chmod +x "$BIN/sqlcipher"
    ok "sqlcipher（python 实现，带 .tables/.schema）"
}

sec_plaso() {
    say "plaso（时间线）+ pyewf（E01 读写，不需要 ewf-tools）"
    if [ ! -x "$TOOLS/venv-plaso/bin/log2timeline" ]; then
        have uv || { warn "没有 uv，跳过"; return 1; }
        uv venv -q --python 3.14 "$TOOLS/venv-plaso" || { warn "建 venv 失败"; return 1; }
        uv pip install -q --python "$TOOLS/venv-plaso/bin/python" plaso \
            || { warn "装 plaso 失败"; return 1; }
    fi
    for t in log2timeline psort pinfo image_export; do
        [ -x "$TOOLS/venv-plaso/bin/$t" ] && ln -sf "$TOOLS/venv-plaso/bin/$t" "$BIN/$t"
    done
    ln -sf "$TOOLS/venv-plaso/bin/log2timeline" "$BIN/log2timeline.py"
    ln -sf "$TOOLS/venv-plaso/bin/psort" "$BIN/psort.py"
    ln -sf "$TOOLS/venv-plaso/bin/pinfo" "$BIN/pinfo.py"
    # pyewf 提供 E01 读写；系统只有 libewf 库没有 ewfinfo 命令
    for pair in "info:ewfinfo" "export:ewfexport" "verify:ewfverify"; do
        sub=${pair%%:*}; name=${pair##*:}
        cat > "$BIN/$name" <<EOF
#!/bin/sh
exec "$TOOLS/venv-plaso/bin/python" "$TOOLS/ewf.py" $sub "\$@"
EOF
        chmod +x "$BIN/$name"
    done
    ok "plaso $(log2timeline.py --version 2>/dev/null | awk '{print $NF}') + ewfinfo/ewfexport/ewfverify"
}

sec_testdisk() {
    say "PhotoRec / TestDisk（源码编，免 sudo；系统没有 ncurses 头文件就自己编一份）"
    if [ -x "$TOOLS/testdisk/photorec" ]; then
        ok "photorec $("$TOOLS/testdisk/photorec" /version 2>/dev/null | head -1 | cut -d, -f1)"
        return 0
    fi
    local b="$TOOLS/_build" ncp="$TOOLS/_build/ncurses"
    mkdir -p "$b"

    if [ ! -f "$ncp/include/ncurses.h" ]; then
        dl "https://ftp.gnu.org/gnu/ncurses/ncurses-6.5.tar.gz" "$DL/ncurses.tgz" || return 1
        rm -rf "$b/ncurses-6.5"; tar xzf "$DL/ncurses.tgz" -C "$b" || { warn "解压失败"; return 1; }
        ( cd "$b/ncurses-6.5" \
          && ./configure --prefix="$ncp" --without-shared --without-debug \
                --without-ada --without-tests --enable-widec >/dev/null 2>&1 \
          && make -j"$(nproc)" >/dev/null 2>&1 || true
          # C++ 绑定编不过不影响，只需要 libncursesw.a 和头文件
          make install.libs >/dev/null 2>&1 || true
          mkdir -p "$ncp/include" "$ncp/bin"
          cp include/curses.h include/term.h include/unctrl.h \
             include/panel.h include/menu.h include/form.h "$ncp/include/" 2>/dev/null
          ln -sf curses.h "$ncp/include/ncurses.h"
          cp lib/libncursesw.a "$ncp/lib/" 2>/dev/null
          cat > "$ncp/bin/ncursesw6-config" <<EOF
#!/bin/sh
case "\$1" in
  --cflags) echo "-I$ncp/include" ;;
  --libs)   echo "-L$ncp/lib -lncursesw" ;;
  *)        echo "-I$ncp/include -L$ncp/lib -lncursesw" ;;
esac
EOF
          chmod +x "$ncp/bin/ncursesw6-config"
        ) || { warn "ncurses 编译失败"; return 1; }
        ok "ncurses 6.5（$ncp）"
    fi

    dl "https://www.cgsecurity.org/testdisk-7.2.tar.bz2" "$DL/testdisk.tar.bz2" || return 1
    rm -rf "$b/testdisk-7.2"
    7z x -y -o"$b" "$DL/testdisk.tar.bz2" >/dev/null && 7z x -y -o"$b" "$b/testdisk.tar" >/dev/null
    ( cd "$b/testdisk-7.2" \
      && PATH="$ncp/bin:$PATH" CPPFLAGS="-I$ncp/include" LDFLAGS="-L$ncp/lib" \
         ./configure --prefix="$b/testdisk" --without-ntfs3 --without-ewf --without-jpeg \
         >/dev/null 2>&1 \
      && make -j"$(nproc)" >/dev/null 2>&1 ) || { warn "testdisk 编译失败"; return 1; }
    mkdir -p "$TOOLS/testdisk"
    cp "$b/testdisk-7.2/src/photorec" "$b/testdisk-7.2/src/testdisk" "$TOOLS/testdisk/"
    chmod +x "$TOOLS/testdisk/"*
    ln -sf "$TOOLS/testdisk/photorec" "$BIN/photorec"
    ln -sf "$TOOLS/testdisk/testdisk" "$BIN/testdisk"
    ok "photorec 7.2 + testdisk 7.2（$(du -sh "$TOOLS/testdisk" | cut -f1)）"
    warn "photorec 是 TUI，非交互必须用 /cmd：photorec /log /d out /cmd img partition_none,search"
}

sec_win() {
    say "Windows 取证：Dissect + Regipy + Hindsight + Hayabusa"
    have uv || { warn "没有 uv，跳过"; return 1; }
    # dissect 用了 glob._Globber，Python 3.14 已经删掉，必须 3.12
    if [ ! -x "$TOOLS/venv-win/bin/target-query" ]; then
        uv venv -q --python 3.12 "$TOOLS/venv-win" || { warn "建 venv 失败"; return 1; }
        uv pip install -q --python "$TOOLS/venv-win/bin/python" \
            dissect regipy pyhindsight click tabulate || { warn "装失败"; return 1; }
        # pyhindsight 的 Chrome 解析器不在 PyPI，从 GitHub 装
        uv pip install -q --python "$TOOLS/venv-win/bin/python" \
            "ccl_chromium_reader @ git+https://github.com/cclgroupltd/ccl_chromium_reader.git" \
            2>/dev/null || warn "ccl_chromium_reader 装失败（Chrome/Edge 解析会退化）"
    fi
    # 只链取证入口，别把 venv 的 activate/python/ipython/bottle.py 一起倒进 tools/bin
    local t
    for t in target-info target-query target-shell target-fs target-dd target-dump target-diff \
             target-mount target-reg target-yara target-inspect target-qfind \
             regipy-dump regipy-diff regipy-parse-header regipy-plugins-list regipy-plugins-run \
             regipy-process-transaction-logs hindsight.py thumbcache-extract thumbcache-extract-indexed \
             parse-lnk dissect-ntds dissect-sru dissect-ual dissect-certlog dissect-impacket \
             vbk-extract vma-extract vmtar fve-dd adcrypt backup-extract dump-nskeyedarchiver \
             envelope-decrypt rgeoip rdump vba_extract.py; do
        [ -x "$TOOLS/venv-win/bin/$t" ] && ln -sf "$TOOLS/venv-win/bin/$t" "$BIN/$t"
    done
    ok "Dissect（$("$TOOLS/venv-win/bin/target-query" -l 2>/dev/null | wc -l) 行插件表）+ regipy + hindsight"

    # Hayabusa：Rust 单文件，官方发 linux musl 包，不需要 .NET
    local hb="$TOOLS/hayabusa/hayabusa-4.4.0-lin-x64-musl"
    if [ ! -x "$hb" ]; then
        dl "https://github.com/Yamato-Security/hayabusa/releases/download/v4.4.0/hayabusa-4.4.0-lin-x64-musl.zip" \
            "$DL/hayabusa.zip" || return 1
        unzip_to "$DL/hayabusa.zip" "$TOOLS/hayabusa"
        chmod +x "$TOOLS/hayabusa/hayabusa-"* 2>/dev/null
    fi
    ln -sf "$hb" "$BIN/hayabusa"
    ok "hayabusa v4.4.0（EVTX 检测，自带 4000+ 规则）"

    warn "Eric Zimmerman Tools 是 win-x64 单文件 exe，Linux 跑不了；功能见 skills/windows"
}

sec_ghidra() {
    say "Ghidra（570MB，JDK 21+）"
    if [ -x "$TOOLS/ghidra/support/analyzeHeadless" ]; then ok "已装"; return; fi
    [ -x "$TOOLS/jdk/bin/java" ] || have java || { warn "先跑 tools/install.sh jdk"; return 1; }
    dl "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip" "$DL/ghidra.zip" || return 1
    unzip_to "$DL/ghidra.zip" "$TOOLS/ghidra" && flatten "$TOOLS/ghidra"
    chmod +x "$TOOLS/ghidra/support/"* 2>/dev/null
    # Ghidra 要 JAVA_HOME，写个包装别污染全局
    cat > "$BIN/ghidra-headless" <<EOF
#!/bin/sh
# 自动带脚本目录；-scriptPath 必须放在项目位置/名称之后，否则解析失败
export JAVA_HOME="$TOOLS/jdk"
export PATH="\$JAVA_HOME/bin:\$PATH"
T=\${GHIDRA_TIMEOUT:-300}
A=\${GHIDRA_ANALYSIS_TIMEOUT:-180}
CMD="$TOOLS/ghidra/support/analyzeHeadless"
if [ "\$T" = "0" ]; then
    exec "\$CMD" "\$@" -analysisTimeoutPerFile "\$A" -scriptPath "$TOOLS/ghidra-scripts"
fi
exec timeout -k 10 "\$T" "\$CMD" "\$@" -analysisTimeoutPerFile "\$A" -scriptPath "$TOOLS/ghidra-scripts"
EOF
    chmod +x "$BIN/ghidra-headless"
    ok "Ghidra 12.2"
}

# ---------------------------------------------------------------- 网络取证

sec_scapy() {
    say "Scapy（python 包）"
    "$TOOLS/venv/bin/python" -c 'import scapy' 2>/dev/null && { ok "已装"; return; }
    uv pip install --python "$TOOLS/venv/bin/python" scapy >/dev/null && ok "scapy $("$TOOLS/venv/bin/python" -c 'import scapy;print(scapy.__version__)')"
}

sec_cyberchef() {
    say "CyberChef（npm 源码 + node API）"
    if [ -f "$TOOLS/cyberchef/node_modules/cyberchef/src/node/index.mjs" ] && [ -x "$BIN/cyberchef" ]; then ok "已装"; return; fi
    have node || { warn "需要 node"; return 1; }
    have npm  || { warn "需要 npm"; return 1; }
    mkdir -p "$TOOLS/cyberchef" && cd "$TOOLS/cyberchef" || return 1
    [ -f package.json ] || npm init -y >/dev/null 2>&1
    # cyberchef 的 postinstall 会跑 grunt 但本地没有，先跳过脚本
    npm install --ignore-scripts --no-audit --no-fund cyberchef >/dev/null 2>&1 || { warn "npm install 失败"; return 1; }
    # 注意：别用 npm prune --omit=dev —— terser 是 devDependency，但源码里直接 import
    ( cd node_modules/cyberchef && npm install --ignore-scripts --no-audit --no-fund >/dev/null 2>&1 )
    # crypto-api 的 ESM 相对导入缺 .mjs 后缀，node 直接跑会 ERR_MODULE_NOT_FOUND
    python3 - "$TOOLS/cyberchef" <<'PYEOF'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
pat = re.compile(r"""(from\s+|import\s*\(\s*)(['"])(\.{1,2}/[^'"]*?)\2""")
n = 0
files = list(root.glob("node_modules/**/crypto-api/**/*.js")) + \
        list(root.glob("node_modules/**/crypto-api/**/*.mjs"))
for f in files:
    s = f.read_text(encoding="utf-8", errors="ignore"); o = s
    def fix(m):
        p = m.group(3)
        if p.endswith((".js", ".mjs", ".json", ".cjs")): return m.group(0)
        return f"{m.group(1)}{m.group(2)}{p}.mjs{m.group(2)}"
    s = pat.sub(fix, s)
    if s != o: f.write_text(s, encoding="utf-8"); n += 1
print(f"    修正 crypto-api ESM 导入: {n} 个文件")
PYEOF
    # cli 脚本跟着 TOOLS 走（TOOLS_DIR 改到别处时也能用）
    [ "$ROOT/tools/cyberchef-cli.mjs" = "$TOOLS/cyberchef-cli.mjs" ] || cp "$ROOT/tools/cyberchef-cli.mjs" "$TOOLS/cyberchef-cli.mjs"
    cat > "$BIN/cyberchef" <<EOF
#!/usr/bin/env bash
set -euo pipefail
T="$TOOLS"
exec node --no-warnings "\$T/cyberchef-cli.mjs" "\$@"
EOF
    chmod +x "$BIN/cyberchef"
    ok "cyberchef $(node --no-warnings "$TOOLS/cyberchef-cli.mjs" -l | wc -l) 个操作"
    cd "$ROOT" || true
}

# 从 ubuntu 仓库拉一个 deb 解到某目录（不需要 sudo）
deb_into() {  # deb_into <包名> <目标目录>
    local pkg=$1 dest=$2 tmp
    tmp=$(mktemp -d)
    if ( cd "$tmp" && timeout 180 apt-get download "$pkg" >/dev/null 2>&1 ) && ls "$tmp"/*.deb >/dev/null 2>&1; then
        for d in "$tmp"/*.deb; do dpkg-deb -x "$d" "$dest"; done
        rm -rf "$tmp"; return 0
    fi
    rm -rf "$tmp"; warn "apt-get download $pkg 失败"; return 1
}

sec_zeek() {
    say "Zeek 9（deb 解包，不装系统）"
    local Z="$TOOLS/zeek"
    if [ -x "$BIN/zeek" ] && "$BIN/zeek" --version >/dev/null 2>&1; then ok "已装"; return; fi
    local base="https://download.opensuse.org/repositories/security:/zeek/xUbuntu_26.04/amd64"
    rm -rf "$Z" && mkdir -p "$Z"
    dl "$base/zeek-core_9.0.1-0_amd64.deb" "$DL/zeek-core.deb" || return 1
    dpkg-deb -x "$DL/zeek-core.deb" "$Z"
    # libzmq 及其依赖不在基础系统里，同样解包带进来
    [ -s "$DL/libzmq5.deb" ] || curl -fsSL -o "$DL/libzmq5.deb" "http://archive.ubuntu.com/ubuntu/pool/universe/z/zeromq3/libzmq5_4.3.5-1build4_amd64.deb"
    [ -s "$DL/libsodium26.deb" ] || curl -fsSL -o "$DL/libsodium26.deb" "http://archive.ubuntu.com/ubuntu/pool/main/libs/libsodium/libsodium26_1.0.22-2_amd64.deb"
    [ -s "$DL/libpgm.deb" ] || curl -fsSL -o "$DL/libpgm.deb" "http://archive.ubuntu.com/ubuntu/pool/universe/libp/libpgm/libpgm-5.3-0t64_5.3.128~dfsg-3_amd64.deb"
    [ -s "$DL/libnorm.deb" ] || curl -fsSL -o "$DL/libnorm.deb" "http://ftp.us.debian.org/debian/pool/main/n/norm/libnorm1t64_1.5.9+dfsg-4+b1_amd64.deb"
    for d in libzmq5 libsodium26 libpgm libnorm; do [ -s "$DL/$d.deb" ] && dpkg-deb -x "$DL/$d.deb" "$Z"; done
    cat > "$BIN/zeek" <<EOF
#!/usr/bin/env bash
set -euo pipefail
T="$TOOLS"; P="\$T/zeek/opt/zeek"
export LD_LIBRARY_PATH="\$T/zeek/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export ZEEKPATH="\$P/share/zeek:\$P/share/zeek/builtin-plugins:\$P/share/zeek/policy:\$P/share/zeek/site"
exec "\$P/bin/zeek" "\$@"
EOF
    chmod +x "$BIN/zeek"
    ln -sf ../zeek/opt/zeek/bin/zeek-cut "$BIN/zeek-cut"
    "$BIN/zeek" --version 2>/dev/null | head -1 | sed 's/^/    /'
    ok "Zeek（+ zeek-cut）"
}

sec_suricata() {
    say "Suricata 8（deb 解包 + 依赖一起带）"
    local S="$TOOLS/suricata"
    if [ -x "$BIN/suricata" ] && "$BIN/suricata" --build-info >/dev/null 2>&1; then ok "已装"; return; fi
    rm -rf "$S" && mkdir -p "$S"
    dl "https://ppa.launchpadcontent.net/oisf/suricata-stable/ubuntu/pool/main/s/suricata/suricata_8.0.8-0ubuntu3_amd64.deb" "$DL/suricata.deb" || return 1
    dpkg-deb -x "$DL/suricata.deb" "$S"
    local l
    for l in libevent-2.1-7t64 libevent-pthreads-2.1-7t64 libhiredis1.1.0 libunwind8 libnet9 \
             libnetfilter-queue1 libnfnetlink0 libhyperscan5; do
        deb_into "$l" "$S" || true
    done
    cat > "$BIN/suricata" <<EOF
#!/usr/bin/env bash
set -euo pipefail
T="$TOOLS"; S="\$T/suricata"
export LD_LIBRARY_PATH="\$S/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
# -l 目录不存在时 suricata 直接拒绝启动，先建出来
prev=""
for a in "\$@"; do
    case "\$prev" in -l|--log-dir) mkdir -p "\$a" 2>/dev/null || true ;; esac
    case "\$a" in -l=*|--log-dir=*) mkdir -p "\${a#*=}" 2>/dev/null || true ;; esac
    prev="\$a"
done
for a in "\$@"; do
    case "\$a" in -c|--config|-c=*|--config=*) exec "\$S/usr/bin/suricata" "\$@" ;; esac
done
exec "\$S/usr/bin/suricata" \\
    -c "\$S/etc/suricata/suricata.yaml" \\
    --set classification-file="\$S/etc/suricata/classification.config" \\
    --set reference-config-file="\$S/etc/suricata/reference.config" \\
    --set threshold-file="\$S/etc/suricata/threshold.config" \\
    --set default-rule-path="\$S/usr/share/suricata/rules" \\
    "\$@"
EOF
    chmod +x "$BIN/suricata"
    "$BIN/suricata" --build-info 2>/dev/null | head -1 | sed 's/^/    /'
    ok "Suricata（规则要自己写 -S，或放 tools/suricata/usr/share/suricata/rules/）"
}

sec_tcpflow() {
    say "tcpflow 1.6.1（源码编译，pcap/boost 头文件用 deb 解包）"
    if [ -x "$BIN/tcpflow" ] && "$BIN/tcpflow" -h 2>&1 | grep -q 'TCPFLOW version'; then ok "已装"; return; fi
    local B="$TOOLS/_build/tcpflow" && rm -rf "$B" && mkdir -p "$B"
    have g++ || { warn "需要 g++"; return 1; }
    # 头文件：libpcap-dev / libboost-dev 解包（不装系统）
    [ -s "$DL/libpcap-dev.deb" ] || curl -fsSL -o "$DL/libpcap-dev.deb" "http://archive.ubuntu.com/ubuntu/pool/main/libp/libpcap/libpcap0.8-dev_1.11.0-1ubuntu1_amd64.deb"
    [ -s "$DL/boost-dev.deb" ]  || curl -fsSL -o "$DL/boost-dev.deb" "http://archive.ubuntu.com/ubuntu/pool/main/b/boost1.83/libboost1.83-dev_1.83.0-5ubuntu1.1_amd64.deb"
    dpkg-deb -x "$DL/libpcap-dev.deb" "$B/pcap"
    dpkg-deb -x "$DL/boost-dev.deb" "$B/boost"
    dl "https://github.com/simsong/tcpflow/releases/download/tcpflow-1.6.1/tcpflow-1.6.1.tar.gz" "$DL/tcpflow.tar.gz" || return 1
    tar xzf "$DL/tcpflow.tar.gz" -C "$B"
    mkdir -p "$B/liblink"
    local l src
    for l in dbus-1 crypto z; do
        # 注意 .so.1 和 .so.1.3.1 会同时匹配，必须只取一个，否则 ln 报错被吞掉
        src=$(ls -1 /usr/lib/x86_64-linux-gnu/lib"$l".so.* 2>/dev/null | head -1)
        [ -n "$src" ] && ln -sf "$src" "$B/liblink/lib$l.so"
    done
    ( cd "$B/tcpflow-1.6.1" && \
      CPPFLAGS="-DHAVE_LIBPCAP=1 -I$B/pcap/usr/include -I$B/boost/usr/include" \
      LDFLAGS="-L$B/pcap/usr/lib/x86_64-linux-gnu -L$B/liblink" \
      ./configure --prefix="$B/inst" --without-cairo >/dev/null 2>&1 && \
      make -j"$(nproc)" \
        LIBS="-lpcap -ldbus-1 -lcrypto -lz /usr/lib/x86_64-linux-gnu/libibverbs.so.1 /usr/lib/x86_64-linux-gnu/libnl-3.so.200 /usr/lib/x86_64-linux-gnu/libnl-route-3.so.200" \
        LDFLAGS="-L$B/pcap/usr/lib/x86_64-linux-gnu -L$B/liblink" >/dev/null 2>&1 ) || { warn "编译失败"; return 1; }
    mkdir -p "$TOOLS/tcpflow" && cp "$B/tcpflow-1.6.1/src/tcpflow" "$TOOLS/tcpflow/tcpflow"
    cat > "$BIN/tcpflow" <<EOF
#!/usr/bin/env bash
set -euo pipefail
T="$TOOLS"
exec "\$T/tcpflow/tcpflow" "\$@"
EOF
    chmod +x "$BIN/tcpflow"
    "$BIN/tcpflow" -h 2>&1 | head -1 | sed 's/^/    /'
    ok "tcpflow"
}

# ---------------------------------------------------------------- 内存取证

sec_mem() {
    say "内存取证：volatility3 / vol2 / MemProcFS / yara 规则"
    sec_mem_vol3
    sec_mem_vol2
    sec_mem_procfs
    sec_mem_yara
}

sec_mem_vol3() {
    say "Volatility 3（uv tool，带 pycryptodome/capstone/yara）"
    # 关键：hashdump/cachedump/lsadump 依赖 pycryptodome，缺了 vol3 会静默跳过这些插件
    # （插件列表里直接不出现，不报错不警告），所以用 --with 一起装，并按 hashdump 是否存在判断
    if ! { command -v vol >/dev/null 2>&1 && vol --help 2>&1 | grep -q 'windows.hashdump'; }; then
        uv tool install --force volatility3 --with pycryptodome --with capstone \
            --with yara-python --with pyyaml >/dev/null 2>&1 \
            && ok "vol $(vol -h 2>&1 | head -1 | sed 's/.*Framework //')" \
            || { warn "volatility3 安装失败"; return 1; }
        vol --help 2>&1 | grep -q 'windows.hashdump' \
            && ok "hashdump/lsadump/cachedump 在册" \
            || warn "hashdump 仍缺失，检查 pycryptodome"
    else
        ok "已装"
    fi
    # 包装器：缺依赖时大声拒跑 + 缓存/符号表落仓库内（vol 自己不提示，只能靠包装器兜）
    mkdir -p "$TOOLS/_cache/vol3"
    cat > "$BIN/vol" <<EOF
#!/usr/bin/env bash
# Volatility 3 包装器。三件 vol 自己不会说的事：
#   1. 缺 pycryptodome 时 hashdump/cachedump/lsadump 会被【静默跳过】，这里先探活再拒跑
#   2. 缓存（PDB/ISF）从 ~/.cache/volatility3 改到仓库内 tools/_cache/vol3
#   3. 有 tools/volatility3-symbols 就自动带 -s
set -uo pipefail
T="$TOOLS"
VOLDIR="\$(uv tool dir 2>/dev/null || echo "\$HOME/.local/share/uv/tools")/volatility3"
[ -x "\$VOLDIR/bin/vol" ] || { echo "vol3 没装：\$T/install.sh mem" >&2; exit 1; }
if ! "\$VOLDIR/bin/python" -c 'import Crypto, capstone' >/dev/null 2>&1; then
    echo "vol3 依赖不全：hashdump/cachedump/lsadump 会被静默跳过（不报错，插件直接消失）。" >&2
    echo "修复：uv tool install --force volatility3 --with pycryptodome --with capstone --with yara-python --with pyyaml" >&2
    exit 1
fi
mkdir -p "\$T/_cache/vol3"
ARGS=(--cache-path "\$T/_cache/vol3")
[ -d "\$T/volatility3-symbols" ] && ARGS+=(-s "\$T/volatility3-symbols")
exec "\$VOLDIR/bin/vol" "\${ARGS[@]}" "\$@"
EOF
    chmod +x "$BIN/vol"
    ok "包装器 tools/bin/vol（缓存 tools/_cache/vol3）"
    warn "Windows 符号表不预装（840MB）。首次分析自动从 msdl.microsoft.com 拉 PDB；"
    warn "离线环境另跑：tools/install.sh mem-symbols"
}

sec_mem_symbols() {
    say "Volatility 3 Windows 符号表（840MB）"
    local d="$TOOLS/volatility3-symbols"
    if [ -d "$d/windows" ]; then ok "已装"; return; fi
    mkdir -p "$d"
    dl "https://downloads.volatilityfoundation.org/volatility3/symbols/windows.zip" "$DL/vol3-windows-symbols.zip" || return 1
    7z x -y -bso0 -bsp0 -o"$d" "$DL/vol3-windows-symbols.zip" >/dev/null && ok "符号表在 $d"
    warn "用的时候加 -s $d（或写进 ~/.config/volatility3/volatility3.json）"
}

sec_mem_vol2() {
    say "Volatility 2.6.1（自带 Python 2.7.18，系统没有 py2 也能跑）"
    if [ -x "$BIN/vol2" ] && "$BIN/vol2" --info >/dev/null 2>&1; then ok "已装"; return; fi
    have gcc || { warn "需要 gcc"; return 1; }
    local P="$TOOLS/py27"
    # 1) Python 2.7.18：gcc 15 默认 gnu23，asdl.h 里 bool/false 会撞关键字，必须 -std=gnu17
    if [ ! -x "$P/bin/python2.7" ]; then
        dl "https://www.python.org/ftp/python/2.7.18/Python-2.7.18.tgz" "$DL/Python-2.7.18.tgz" || return 1
        rm -rf "$TOOLS/_build/py27" && mkdir -p "$TOOLS/_build/py27"
        tar xzf "$DL/Python-2.7.18.tgz" -C "$TOOLS/_build/py27"
        ( cd "$TOOLS/_build/py27/Python-2.7.18" && \
          ./configure --prefix="$P" --enable-unicode=ucs4 CFLAGS="-std=gnu17 -fcommon -O2" >/dev/null 2>&1 && \
          make -j"$(nproc)" >/dev/null 2>&1 && make install >/dev/null 2>&1 ) || { warn "py2.7 编译失败"; return 1; }
        ok "Python 2.7.18"
    fi
    # 2) pip（2.7 专用引导脚本）
    if [ ! -x "$P/bin/pip" ]; then
        curl -fsSL -o "$DL/get-pip-27.py" https://bootstrap.pypa.io/pip/2.7/get-pip.py && \
            "$P/bin/python2.7" "$DL/get-pip-27.py" --no-warn-script-location >/dev/null 2>&1
    fi
    # yara-python<4.3 是最后支持 py2 的版本，vol2 的 yarascan 插件要用
    "$P/bin/pip" install --no-warn-script-location pycryptodome distorm3 "yara-python<4.3" >/dev/null 2>&1 \
        && ok "pycryptodome + distorm3 + yara-python"
    # 3) vol2 要 sqlite3，但系统没有 sqlite3.h → 从 deb 解头文件，单独编 _sqlite3.so
    if ! "$P/bin/python2.7" -c 'import sqlite3' 2>/dev/null; then
        deb_into libsqlite3-dev "$TOOLS/_build/sqlite-dev" >/dev/null 2>&1
        local SD="$TOOLS/_build/sqlite-dev"
        if [ -f "$SD/usr/include/sqlite3.h" ]; then
            ( cd "$TOOLS/_build/py27/Python-2.7.18" && \
              gcc -shared -fPIC -std=gnu17 -fcommon -O2 -DMODULE_NAME='"sqlite3"' \
                  -I. -IInclude -I"$SD/usr/include" Modules/_sqlite/*.c \
                  -o "$P/lib/python2.7/lib-dynload/_sqlite3.so" \
                  /usr/lib/x86_64-linux-gnu/libsqlite3.so.0 2>/dev/null ) && ok "sqlite3 模块"
        fi
    fi
    # 4) vol2 源码
    if [ ! -f "$TOOLS/volatility2/vol.py" ]; then
        dl "https://github.com/volatilityfoundation/volatility/archive/refs/tags/2.6.1.tar.gz" "$DL/vol2.tar.gz" || return 1
        rm -rf "$TOOLS/volatility2" && mkdir -p "$TOOLS/volatility2"
        tar xzf "$DL/vol2.tar.gz" -C "$TOOLS/volatility2" --strip-components=1
    fi
    cat > "$BIN/vol2" <<EOF
#!/usr/bin/env bash
set -euo pipefail
T="$TOOLS"
exec "\$T/py27/bin/python2.7" "\$T/volatility2/vol.py" "\$@"
EOF
    chmod +x "$BIN/vol2"
    "$BIN/vol2" --info 2>/dev/null | head -1 | sed 's/^/    /'
    ok "Volatility 2.6.1"
}

sec_mem_procfs() {
    say "MemProcFS v5.19（deb 解包的 libfuse2/libusb 一起带）"
    # -help 的退出码不是 0，pipefail 下要 || true，否则每次都重装
    if [ -x "$BIN/memprocfs" ] && { "$BIN/memprocfs" -help 2>&1 || true; } | grep -q 'MemProcFS v'; then ok "已装"; return; fi
    dl "https://github.com/ufrisk/MemProcFS/releases/download/v5.19/MemProcFS_files_and_binaries_v5.19.4-linux_x64-20261114.tar.gz" "$DL/memprocfs.tar.gz" || return 1
    rm -rf "$TOOLS/memprocfs" && mkdir -p "$TOOLS/memprocfs"
    tar xzf "$DL/memprocfs.tar.gz" -C "$TOOLS/memprocfs"
    deb_into libfuse2t64 "$TOOLS/memprocfs/lib" >/dev/null 2>&1
    deb_into libusb-1.0-0 "$TOOLS/memprocfs/lib" >/dev/null 2>&1
    cat > "$BIN/memprocfs" <<EOF
#!/usr/bin/env bash
set -euo pipefail
T="$TOOLS"
export LD_LIBRARY_PATH="\$T/memprocfs/lib/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "\$T/memprocfs/memprocfs" "\$@"
EOF
    cat > "$BIN/memprocfs-python" <<EOF
#!/usr/bin/env bash
# MemProcFS 的 Python API：带好 PYTHONPATH + LD_LIBRARY_PATH
set -euo pipefail
T="$TOOLS"
export LD_LIBRARY_PATH="\$T/memprocfs/lib/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export PYTHONPATH="\$T/memprocfs\${PYTHONPATH:+:\$PYTHONPATH}"
exec "\${MEMPY:-\$T/venv/bin/python}" "\$@"
EOF
    chmod +x "$BIN/memprocfs" "$BIN/memprocfs-python"
    "$BIN/memprocfs" -help 2>&1 | grep -m1 'MemProcFS v' | sed 's/^ */    /'
    ok "MemProcFS + Python API（memprocfs-python）"
}

sec_mem_yara() {
    say "YARA 规则：signature-base + CTF 规则"
    uv pip install --python "$TOOLS/venv/bin/python" yara-python >/dev/null 2>&1 && ok "yara-python"
    if [ ! -d "$TOOLS/yara-rules/signature-base" ]; then
        dl "https://codeload.github.com/Neo23x0/signature-base/tar.gz/refs/heads/master" "$DL/sigbase.tar.gz" || return 1
        rm -rf "$TOOLS/_build/sigbase" && mkdir -p "$TOOLS/_build/sigbase"
        tar xzf "$DL/sigbase.tar.gz" -C "$TOOLS/_build/sigbase"
        mkdir -p "$TOOLS/yara-rules"
        cp -r "$TOOLS/_build/sigbase"/signature-base-master/yara "$TOOLS/yara-rules/signature-base"
    fi
    ok "规则 $(ls "$TOOLS/yara-rules/signature-base"/*.yar 2>/dev/null | wc -l) 条文件 + ctf.yar"
}

# ---------------------------------------------------------------- 汽车 / CAN 总线

sec_vehicle() {
    say "汽车取证：python-can / cantools / udsoncan / asammdf / can-utils"
    sec_vehicle_py
    sec_vehicle_canutils
}

sec_vehicle_py() {
    say "Python 侧（tools/venv-auto，py3.12 —— asammdf 的 numpy/pandas 在 3.14 上容易翻车）"
    if [ ! -x "$TOOLS/venv-auto/bin/python" ]; then
        uv venv "$TOOLS/venv-auto" --python 3.12 >/dev/null 2>&1 || { warn "venv 建不起来"; return 1; }
    fi
    uv pip install --python "$TOOLS/venv-auto/bin/python" python-can cantools udsoncan asammdf >/dev/null 2>&1 \
        && ok "python-can / cantools / udsoncan / asammdf" \
        || { warn "pip 安装失败"; return 1; }
    # venv 里的命令行工具链到 tools/bin
    local c
    for c in cantools can_logconvert can_logger can_player can_viewer can_bridge canconvert cancompare; do
        [ -x "$TOOLS/venv-auto/bin/$c" ] && ln -sf "../venv-auto/bin/$c" "$BIN/$c"
    done
    "$TOOLS/venv-auto/bin/python" - <<'EOF' | sed 's/^/    /'
import can, cantools, udsoncan, asammdf
print(f"python-can {can.__version__} / cantools {cantools.__version__} / udsoncan {udsoncan.__version__} / asammdf {asammdf.__version__}")
EOF
    ok "CLI: cantools / can_logconvert / canconvert / cancompare"
}

sec_vehicle_canutils() {
    say "can-utils（deb 解包，只依赖 libc，不装 socketcan 服务）"
    if [ -x "$TOOLS/can-utils/bin/candump" ]; then ok "已装"; return; fi
    rm -rf "$TOOLS/can-utils" && mkdir -p "$TOOLS/can-utils"
    deb_into can-utils "$TOOLS/can-utils" || return 1
    local b n cnt=0
    for b in "$TOOLS/can-utils/usr/bin"/*; do
        n=$(basename "$b")
        ln -sf "../can-utils/usr/bin/$n" "$BIN/$n"; cnt=$((cnt + 1))
    done
    ok "$cnt 个命令：candump / cansniffer / log2asc / asc2log / log2long / canbusload ..."
    warn "candump/cansniffer 需要真 CAN 口（vcan 要 sudo modprobe vcan）；做题基本只用 log2asc / asc2log / log2long"
}

# ---------------------------------------------------------------- main

SECTIONS=("$@")
[ ${#SECTIONS[@]} -eq 0 ] && SECTIONS=(apt venv jdk jadx dex2jar rizin aleapp apktool platformtools protoc simg2img sqlcipher plaso win testdisk net mem vehicle)

for s in "${SECTIONS[@]}"; do
    case $s in
        apt)         sec_apt ;;
        venv|python) sec_venv ;;
        gh)          sec_jadx; sec_dex2jar; sec_rizin; sec_aleapp; sec_apktool; sec_platformtools; sec_protoc; sec_simg2img; sec_sqlcipher; sec_plaso; sec_win; sec_testdisk; sec_zeek; sec_suricata; sec_mem; sec_vehicle ;;
        jdk)         sec_jdk ;;
        apktool)     sec_apktool ;;
        platformtools|adb) sec_platformtools ;;
        protoc)      sec_protoc ;;
        simg2img)    sec_simg2img ;;
        sqlcipher)   sec_sqlcipher ;;
        plaso|log2timeline) sec_plaso ;;
        win|windows|dissect) sec_win ;;
        testdisk|photorec) sec_testdisk ;;
        net|network) sec_scapy; sec_cyberchef; sec_zeek; sec_suricata; sec_tcpflow ;;
        mem|memory)  sec_mem ;;
        auto|vehicle|can) sec_vehicle ;;
        python-can|cantools|udsoncan|asammdf|can-utils) sec_vehicle ;;
        mem-symbols) sec_mem_symbols ;;
        vol3|volatility3) sec_mem_vol3 ;;
        vol2|volatility2) sec_mem_vol2 ;;
        memprocfs)   sec_mem_procfs ;;
        yara-rules)  sec_mem_yara ;;
        scapy)       sec_scapy ;;
        cyberchef)   sec_cyberchef ;;
        zeek)        sec_zeek ;;
        suricata)    sec_suricata ;;
        tcpflow)     sec_tcpflow ;;
        jadx)        sec_jadx ;;
        dex2jar)     sec_dex2jar ;;
        rizin)       sec_rizin ;;
        aleapp)      sec_aleapp ;;
        ileapp)      sec_ileapp ;;
        bring2lite)  sec_bring2lite ;;
        ghidra)      sec_ghidra ;;
        *)           warn "未知段: $s（apt venv gh net mem vehicle jadx dex2jar rizin aleapp ileapp bring2lite ghidra zeek suricata tcpflow cyberchef scapy）" ;;
    esac
done

say "完成"
echo "    入口都在 $BIN"
echo "    验证：$ROOT/tools/doctor.sh"
echo "    加 PATH：export PATH=\"$BIN:\$PATH\""
