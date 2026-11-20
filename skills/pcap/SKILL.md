---
name: pcap
description: 分析 pcap/pcapng 流量包 —— 协议分布、Zeek 协议日志、HTTP 对象导出、TCP 流还原、Suricata 告警、DNS/TLS 域名、凭证、USB HID、ICMP 隧道。遇到 .pcap/.pcapng/.cap 或流量分析题时加载。
---

# 流量分析

## 0. 工具分工（先认工具，别乱试）

| 工具 | 什么时候用 | 命令 |
|---|---|---|
| `capinfos` | 第一眼：包数、时间、大小 | `capinfos -a -e -c evi/x.pcap` |
| `tshark` | 精确到帧、字段提取、跟随流 | `tshark -r x.pcap -Y ...` |
| `zeek` | **要协议日志**（conn/dns/http/tls/files） | `cd work/zeek && zeek -r ../../evi/x.pcap` |
| `zeek-cut` | 切 zeek 日志的列（不用记列号） | `zeek-cut query < dns.log` |
| `tcpflow` | 把每条 TCP 流还原成独立文件 | `tcpflow -r x.pcap -o work/flows` |
| `suricata` | 用规则批量告警（已知攻击特征） | `suricata -r x.pcap -S rules -l work/log` |
| `cyberchef` | 编码/加密套娃（base64→gzip→xor） | `cyberchef "From Base64" "Gunzip"` |
| `scapy` | 造包、改包、非常规统计 | `python -c 'from scapy.all import *'` |

`tshark` 的 `-r` 指定文件，`-Y` 是显示过滤，`-z` 是统计。**`-f` 捕获过滤在读文件时无效**。

## 1. 五分钟出结果

```bash
capinfos -a -e -c -u evi/capture.pcap            # 时间范围、包数
tshark -r evi/capture.pcap -q -z io,phs          # 协议分层，看有没有 http/dns/tls
strings -n 6 evi/capture.pcap | rg -i 'flag|ctf|\{'   # 明文 flag 最快路径
mkdir -p work/zeek && cd work/zeek && zeek -r ../../evi/capture.pcap && ls
```

zeek 一跑完 `conn.log` / `dns.log` / `http.log` / `files.log` 全在，比一条条 tshark 快得多。

## 2. Zeek：一次跑完，日志随便查

```bash
mkdir -p work/zeek && cd work/zeek
zeek -r ../../evi/capture.pcap

ls *.log
# conn.log   每条连接（五元组、字节数、时长）
# dns.log    查询名 + 应答
# http.log   方法/URI/Host/UA/状态码
# tls.log    SNI、证书、JA3/JA4
# files.log  从流量里识别出的文件（含 md5/sha1/sha256）
# weird.log  异常行为

# DNS 查询了哪些域名
zeek-cut query < dns.log | sort -u
# 谁访问了哪个 Host
zeek-cut id.orig_h host uri < http.log | head
# 传了哪些文件（按大小排）
zeek-cut mime_type filename total_bytes md5 < files.log | sort -k3 -n | tail
# 最大的连接
zeek-cut id.orig_h id.resp_h id.resp_p orig_bytes resp_bytes < conn.log | sort -k4 -n | tail
```

`zeek-cut` 已装（`tools/bin/zeek-cut`）。万一没有，日志是 tab 分隔、`#` 开头是表头，直接切：

```bash
rg -v '^#' dns.log | cut -f9 | sort -u          # 第 9 列 = query
rg -v '^#' http.log | cut -f8,9 | head           # host, uri
```

**从 files.log 把文件抠出来**（zeek 只记录不落地）：

```bash
# 拿 md5 再去 tshark 导出对象里对
tshark -r evi/capture.pcap --export-objects http,work/http
md5sum work/http/*
```

## 3. tshark：精确到帧

```bash
# 域名
tshark -r evi/capture.pcap -Y dns -T fields -e dns.qry.name | sort -u
tshark -r evi/capture.pcap -Y 'tls.handshake.extensions_server_name' \
       -T fields -e tls.handshake.extensions_server_name | sort -u
# HTTP 请求
tshark -r evi/capture.pcap -Y http.request -T fields \
       -e frame.number -e ip.src -e http.host -e http.request.uri
# 会话矩阵
tshark -r evi/capture.pcap -q -z conv,tcp
tshark -r evi/capture.pcap -q -z endpoints,ip
# 时间范围
tshark -r evi/capture.pcap -T fields -e frame.time_epoch | sed -n '1p;$p'
```

**导出对象**（协议原生支持的最省事）：

```bash
mkdir -p work/http work/smb work/tftp
tshark -r evi/capture.pcap --export-objects http,work/http
tshark -r evi/capture.pcap --export-objects smb,work/smb
tshark -r evi/capture.pcap --export-objects tftp,work/tftp
file work/http/*        # 扩展名经常骗人，一定要 file 一下
```

**跟随流**：

```bash
tshark -r evi/capture.pcap -T fields -e tcp.stream | sort -un | head   # 先列流号
tshark -r evi/capture.pcap -q -z follow,tcp,ascii,0
tshark -r evi/capture.pcap -q -z follow,http,ascii,0
```

**非标准协议抠原始字节**：

```bash
tshark -r evi/capture.pcap -q -z follow,tcp,raw,3 | \
  sed '1,6d' | tr -d '\n\t ' | xxd -r -p > work/stream3.bin
```

## 4. tcpflow：每条流一个文件

比 `follow` 舒服的地方：一次全导，文件名就是 `源IP.端口-目的IP.端口`，直接 `rg` 全目录。

```bash
mkdir -p work/flows && tcpflow -r evi/capture.pcap -o work/flows
ls work/flows | head
rg -i 'flag|passwd|token' work/flows/          # 一把梭
cat work/flows/010.000.000.001.12345-010.000.000.002.00080
```

- `-o` 后面跟目录；不加就在当前目录
- 会顺手写一个 `report.xml`（DFXML），可以忽略
- **只认以太网帧**。裸 IP 的 pcap 会报 `unknown datalink type 228`，这种用 tshark 的 `follow` 代替
- 只还原 TCP，UDP 不管

## 5. Suricata：规则告警

自带的是协议事件规则（`tools/suricata/usr/share/suricata/rules/*.rules`），**攻击特征规则要自己写或下 ET Open**。

```bash
cat > work/local.rules <<'EOF'
alert http any any -> any any (msg:"flag 关键字"; content:"flag{"; nocase; sid:1000001; rev:1;)
alert tcp any any -> any any (msg:"可疑 UA"; content:"curl"; http_user_agent; sid:1000002; rev:1;)
alert dns any any -> any any (msg:"长域名(隧道)"; dns.query; pcre:"/^[a-z0-9]{40,}\./i"; sid:1000003; rev:1;)
EOF
suricata -r evi/capture.pcap -S work/local.rules -l work/suri
cat work/suri/fast.log
```

输出：
- `fast.log` 一行一条告警，最适合 `rg`
- `eve.json` 全量 JSON，`jq` 好使：`jq -c 'select(.event_type=="alert")' work/suri/eve.json`

想看协议元数据而不写规则，直接用 zeek，别绕 Suricata。

## 6. CyberChef：编码/加密套娃

```bash
echo 'SGVsbG8gQ3liZXJDaGVm' | cyberchef "From Base64"      # Hello CyberChef
cyberchef -l | rg -i 'aes|rot|xor|gzip'                     # 508 个操作，先搜
cyberchef -h "AES Decrypt"                                  # 看参数名和类型

# 链式：多个操作连着写，前一个的输出喂给后一个
cat work/blob | cyberchef "From Base64" "Gunzip" "From Hex"

# 带参数：xor 的 key
printf 'FLAG{x0r}' | cyberchef "XOR" --arg key=0x42 | cyberchef "XOR" --arg key=0x42

# 二进制进二进制出
cyberchef "Gunzip" -i work/embedded.gz -o work/plain
cyberchef "AES Decrypt" --arg key=hex:00112233... --arg iv=hex:0000000000000000 \
         --arg mode=CBC -i work/enc.bin -o work/plain
```

- **没有 `Magic`（自动识别）**：CyberChef 的 Node API 拒绝 flowControl 类操作，
  会报 `flowControl operations like Magic are not currently allowed`。
  自动识别只能靠 `file` / `strings` / `cyberchef -l | rg` 猜，然后手动接链
- `--arg` 是给**前一个操作**传参，可以连着写多个
- `hex:` 前缀 = 原始字节，否则是字符串；`true`/`false`/纯数字会自动转类型
- 结果不是合法 UTF-8 时原样输出字节，不会乱码

## 7. Scapy：造包 / 改包 / 非常规统计

```bash
python - <<'PY'
from scapy.all import rdpcap, IP, TCP
pk = rdpcap('evi/capture.pcap')
print(len(pk), pk[0].summary())
# 按源 IP 统计字节数
from collections import Counter
c = Counter()
for p in pk:
    if IP in p: c[p[IP].src] += len(p)
print(c.most_common(5))
PY
```

造包（做测试样本、验证规则）：

```bash
python - <<'PY'
from scapy.all import Ether, IP, TCP, wrpcap
p = Ether()/IP(src='10.0.0.1',dst='10.0.0.2')/TCP(sport=12345,dport=80,flags='PA',seq=1000)/b'GET / HTTP/1.1\r\n\r\n'
wrpcap('/tmp/x.pcap', [p])
PY
```

- 造出来的包只有一层 `IP()` 时链路类型是 LINKTYPE_IPV4，**tcpflow 不认**，套一层 `Ether()`
- `sendp`/`sr1` 要 root 且会真的发包，CTF 里基本用不到，只 `wrpcap` 就够

## 8. 凭证与敏感数据

```bash
tshark -r evi/capture.pcap -Y 'http.authorization or ftp.request.command or \
       smtp.req.parameter or pop.request.command or imap.request' \
       -T fields -e frame.number -e _ws.col.Info
tshark -r evi/capture.pcap -Y 'http.request.method=="POST"' \
       -T fields -e frame.number -e http.file_data
```

## 9. 特殊题型

**USB HID 键盘**（`usb.capdata` 每 8 字节是按键位图）：

```bash
tshark -r evi/usb.pcap -Y 'usb.capdata' -T fields -e usb.capdata
# 0x04..0x1d = a..z；左 Shift 是 bit0
```

**ICMP 隧道**：

```bash
tshark -r evi/tunnel.pcap -Y icmp -T fields -e data.data
```

**无线握手包**：用 `aircrack-ng` / `hcxtools`，不在本技能范围。

## 10. 大文件

```bash
editcap -c 100000 evi/big.pcap work/part.pcap      # 切片
editcap -A '2025-01-01 00:00:00' -B '2025-01-01 01:00:00' evi/big.pcap work/window.pcap
mergecap -w work/merged.pcap work/part*.pcap
tshark -r evi/big.pcap -Y 'http' -w work/http-only.pcap   # 先过滤再分析
```

## 11. 坑表

| 症状 | 原因 / 解法 |
|---|---|
| `-f` 没效果 | 读文件时 `-f` 是捕获过滤，用 `-Y` |
| tcpflow 报 `unknown datalink type 228` | 裸 IP pcap，改用 `tshark -z follow` |
| zeek 报 `can't find Zeek_.../__load__.zeek` | 包装脚本已设 `ZEEKPATH`，别直接调 `opt/zeek/bin/zeek` |
| zeek 日志没生成 | 它写当前目录，先 `cd work/zeek` |
| suricata 报 `reference-config` 打不开 | 包装脚本已带 `--set`，别绕过 `tools/bin/suricata` |
| suricata 一条告警都没有 | 默认规则集只有协议事件，攻击特征要 `-S` 自己写 |
| 导出对象目录空的 | 协议没走 HTTP/SMB/TFTP，改用 tcpflow 或 follow raw |
| pcapng 时间乱 | 多接口时钟不同，看 `frame.interface_id` |
| 中文文件名乱码 | 别用 `unzip`，用 `unpack`（7z） |

## 12. 没装的（P2，别浪费时间去试）

| 工具 | 为什么不装 | 替代 |
|---|---|---|
| RITA | v5 只有源码 tarball，运行要 MongoDB 7；Ubuntu 仓库没有 mongodb-org | zeek 的 `conn.log` + `zeek-cut` 排序，beacon 题很少见 |
| Arkime | capture 只是个写 pcap 的前端；viewer 要 Elasticsearch/OpenSearch | `tshark --export-objects` + `tcpflow` |
| Malcolm | 整套 docker-compose（ES + Logstash + Arkime + Zeek + Suricata） | 本仓库 v2 就是去 Docker 的，上述单机工具已覆盖 |

## 记录示例

```bash
fcase note pcap "HTTP GET 下载了可疑 exe" \
    --locator "frame=412, tcp.stream=7" --src evi/capture.pcap
fcase note pcap "DNS 查询 flag.example.com" \
    --locator "dns.log query=flag.example.com" --src evi/capture.pcap
fcase note pcap "Suricata 命中 flag 关键字" \
    --locator "work/suri/fast.log sid=1000001" --src evi/capture.pcap
```
