#!/usr/bin/env bash
# 逐个验证工具能不能真的跑起来（不是只看在不在 PATH）。
#   tools/doctor.sh          只看 tools/bin + PATH 里的
#   tools/doctor.sh -v       显示每条的版本输出
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${TOOLS_DIR:-$ROOT/tools}"
export PATH="$TOOLS/bin:$ROOT/bin:$PATH"
VERBOSE=0
[ "${1:-}" = "-v" ] && VERBOSE=1

# name|探活参数|说明
LIST=(
  "java|-version|JRE（jadx/apktool 依赖）"
  "aleapp|--help|Android 全盘解析"
  "ileapp|--version|iOS 全盘解析（→ _lava_artifacts.db）"
  "jadx|--version|DEX → Java"
  "dex2jar|--help|DEX → JAR"
  "androguard|--version|APK/DEX 分析"
  "apkid|--version|加固/混淆识别"
  "apkleaks|-h|URL/Key/Token 扫描"
  "frida|--version|动态 Hook（客户端）"
  "rizin|-v|二进制逆向"
  "radare2|-v|二进制逆向（备选）"
  "apktool|--version|APK 解包"
  "simg2img||sparse → raw"
  "adb|version|设备连接"
  "mmls||分区表"
  "fls||文件系统列举"
  "icat||按 inode 取文件"
  "tshark|-v|流量"
  "zeek|--version|流量 → 协议日志（conn/dns/http）"
  "zeek-cut|-h|Zeek 日志切列"
  "suricata|--build-info|IDS 规则匹配"
  "tcpflow|-h|TCP 流还原成文件"
  "cyberchef|-l|编码/加密链（508 个操作）"
  "vol|-h|内存取证 Vol3（进程/DLL/网络）"
  "vol2|--info|内存取证 Vol2（老镜像/旧 profile）"
  "memprocfs|-help|内存镜像挂成虚拟文件系统"
  "cantools|--version|DBC 解码（车速/转速/车门）"
  "log2asc||candump log → ASC（can-utils）"
  "sqlite3|-version|数据库"
  "sqlcipher|-version|加密数据库"
  "ewfinfo||E01 元数据（pyewf）"
  "target-query|--help|Dissect 统一查询"
  "regipy-dump|--help|注册表解析"
  "hindsight.py|--help|浏览器历史"
  "hayabusa|help|EVTX 检测"
  "photorec|/version|签名雕刻（删除文件恢复）"
  "ldb-dump|--help|LevelDB（含删除记录）"
  "exiftool|-ver|EXIF"
  "log2timeline.py|--version|时间线"
  "rg|--version|全文搜索"
  "yara|--version|规则匹配"
  "7z||解包"
  "foremost|-V|文件雕刻"
  "protoc|--version|Protobuf"
  "bbpb|--help|无 .proto 解析 protobuf"
  "sqlite_dissect|--help|SQLite 删除记录（bring2lite 只有 GUI）"
)

ok=0; bad=(); EXTRA=3   # scapy / vol(插件) / 汽车四件套 是独立探活，不在 LIST 里
printf '%-16s %-6s %s\n' 工具 状态 说明
printf '%-16s %-6s %s\n' ---- ---- ----
for row in "${LIST[@]}"; do
    IFS='|' read -r name args desc <<<"$row"
    if ! command -v "$name" >/dev/null 2>&1; then
        printf '%-16s \033[90m%-6s\033[0m %s\n' "$name" "未装" "$desc"
        bad+=("$name")
        continue
    fi
    # 有的工具没有 --version，给空参数就只测能不能启动
    local_raw=$(timeout 25 "$name" $args 2>&1); rc=$?
    local_out=$(head -3 <<<"$local_raw")
    # 退出码 0 但输出里是错误，也算失败（jadx 没有 java 时就这样）
    if grep -qiE 'Traceback|no .java. command|JAVA_HOME|not found|command not found|No such file' <<<"$local_raw"; then
        printf '%-16s \033[31m%-6s\033[0m %s\n' "$name" "失败" "$desc"
        [ $VERBOSE = 1 ] && printf '    %s\n' "$(head -1 <<<"$local_raw")"
        bad+=("$name")
        continue
    fi
    if [ "$rc" -eq 124 ]; then
        printf '%-16s \033[33m%-6s\033[0m %s（超时，可能想连设备）\n' "$name" "超时" "$desc"
        ok=$((ok + 1))
    elif [ -n "$local_out" ]; then
        printf '%-16s \033[32m%-6s\033[0m %s\n' "$name" "ok" "$desc"
        [ $VERBOSE = 1 ] && printf '    %s\n' "$(head -1 <<<"$local_out")"
        ok=$((ok + 1))
    else
        printf '%-16s \033[31m%-6s\033[0m %s\n' "$name" "失败" "$desc"
        bad+=("$name")
    fi
done

# Scapy 单独测：LIST 里没法传带空格的 -c 参数
# 汽车取证专项：真造一条 BLF → 用 DBC 编码 → 再解码，光 import 说明不了问题
AUTOPY="$TOOLS/venv-auto/bin/python"
if [ -x "$AUTOPY" ]; then
    auto_out=$(cd /tmp && timeout 60 "$AUTOPY" - <<'PYEOF' 2>&1
import can, cantools, tempfile, os
dbc = """VERSION ""
BO_ 291 T: 8 X
 SG_ Spd : 0|8@1+ (1,0) [0|255] "km/h" Y
"""
d = tempfile.mkdtemp(); dbp = os.path.join(d, "t.dbc")
open(dbp, "w").write(dbc)
db = cantools.database.load_file(dbp)
data = db.encode_message("T", {"Spd": 88})
f = open(os.path.join(d, "t.blf"), "wb"); w = can.BLFWriter(f)
w.on_message_received(can.Message(arbitration_id=0x123, data=data, timestamp=0.0)); w.stop(); f.close()
m = next(iter(can.LogReader(os.path.join(d, "t.blf"))))
print(db.decode_message(m.arbitration_id, m.data)["Spd"])
PYEOF
)
    if [ "$(tail -1 <<<"$auto_out")" = "88" ]; then
        printf '%-16s \033[32m%-6s\033[0m %s\n' "汽车四件套" "ok" "BLF 写入→读回→DBC 解码 = 88"
        ok=$((ok + 1))
    else
        printf '%-16s \033[31m%-6s\033[0m %s\n' "汽车四件套" "失败" "BLF/DBC 端到端跑不通"
        [ $VERBOSE = 1 ] && printf '    %s\n' "$(tail -2 <<<"$auto_out")"
        bad+=("汽车四件套")
    fi
fi

# vol3 专项：只测 `vol -h` 会漏掉「缺 pycryptodome 导致 hashdump/lsadump/cachedump 被静默跳过」
if command -v vol >/dev/null 2>&1; then
    vhelp=$(timeout 40 vol --help 2>&1)
    if grep -q 'windows.hashdump' <<<"$vhelp"; then
        printf '%-16s \033[32m%-6s\033[0m %s\n' "vol(插件)" "ok" "hashdump/lsadump/cachedump 在册"
        ok=$((ok + 1))
    else
        printf '%-16s \033[31m%-6s\033[0m %s\n' "vol(插件)" "失败" "缺 pycryptodome，hashdump 等被静默跳过"
        bad+=("vol(插件)")
    fi
fi

if "$TOOLS/venv/bin/python" -c 'from scapy.all import IP, TCP, wrpcap; print(IP()/TCP())' 2>/dev/null | grep -q 'TCP'; then
    printf '%-16s \033[32m%-6s\033[0m %s\n' "scapy" "ok" "造包/读包（python）"
    [ $VERBOSE = 1 ] && printf '    %s\n' "$("$TOOLS/venv/bin/python" -c 'import scapy;print(scapy.__version__)')"
    ok=$((ok + 1))
else
    printf '%-16s \033[31m%-6s\033[0m %s\n' "scapy" "失败" "造包/读包（python）"
    bad+=("scapy")
fi

# Ghidra 单独测：跑一次真实的 import + 反编译，8 秒左右。
# 只看 command -v 没意义 —— 缺 JAVA_HOME 时它能启动但什么也做不了。
if command -v ghidra-headless >/dev/null 2>&1; then
    if command -v gcc >/dev/null 2>&1; then
        gtmp=$(mktemp -d)
        printf 'const char* f(void){return "FLAG_ghidra_ok";}\nint g(int a){return a*2;}\n' > "$gtmp/x.c"
        gcc -shared -fPIC -O1 -o "$gtmp/x.so" "$gtmp/x.c" 2>/dev/null
        mkdir -p "$gtmp/p"
        gout=$(timeout 200 ghidra-headless "$gtmp/p" t -import "$gtmp/x.so" \
                 -postScript DecompileToC.java "$gtmp/out.c" f -deleteProject 2>&1)
        if grep -q FLAG_ghidra_ok "$gtmp/out.c" 2>/dev/null; then
            printf '%-16s \033[32m%-6s\033[0m %s\n' "ghidra-headless" "ok" "原生库逆向（实测出 C 代码）"
            [ $VERBOSE = 1 ] && printf '    %s\n' "$(grep -m1 '反编译完成' <<<"$gout")"
            ok=$((ok + 1))
        else
            printf '%-16s \033[31m%-6s\033[0m %s\n' "ghidra-headless" "失败" "原生库逆向（反编译没出结果）"
            [ $VERBOSE = 1 ] && printf '    %s\n' "$(tail -2 <<<"$gout")"
            bad+=("ghidra-headless")
        fi
        rm -rf "$gtmp"
    else
        printf '%-16s \033[33m%-6s\033[0m %s\n' "ghidra-headless" "跳过" "原生库逆向（没有 gcc，无法造测试样本）"
        ok=$((ok + 1))
    fi
    TOTAL=$(( ${#LIST[@]} + 1 ))
else
    printf '%-16s \033[90m%-6s\033[0m %s\n' "ghidra-headless" "未装" "原生库逆向（可选）"
    bad+=("ghidra-headless")
    TOTAL=$(( ${#LIST[@]} + 1 ))
fi

echo
echo "可用 $ok / $(( ${#LIST[@]} + EXTRA ))"
if [ ${#bad[@]} -gt 0 ]; then
    echo "未装或失败: ${bad[*]}"
    echo "装: $ROOT/tools/install.sh     或   $ROOT/setup.sh <包名>"
fi
