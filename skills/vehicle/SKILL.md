# 汽车 / CAN 总线取证（Vehicle / CAN）

> 目标：拿到一段 CAN 日志（或整车测量数据），**5 分钟内**说清楚「有哪些报文、车速多少、谁在发异常帧、flag 在哪」。
> 工具：`python-can` / `cantools` / `can-utils` / `udsoncan` / `asammdf` / `scapy.contrib.automotive`。
> `export PATH="$PWD/tools/bin:$PATH"` 之后直接用。

---

## 0. 先认检材（30 秒）

| 后缀 | 是什么 | 用什么读 |
|---|---|---|
| `.blf` | Vector Binary Logging（最正规的车厂日志） | `python-can` / `can_logconvert` |
| `.asc` | Vector ASCII Log（文本，能直接看） | `python-can` / `asc2log` |
| `.log` `.txt` | `candump -L` 的紧凑文本格式 | `log2asc` / `log2long` / `awk` |
| `.trc` | PEAK 格式 | `python-can`（`can.LogReader` 自动识别） |
| `.mf4` `.mdf` | MDF4 / MDF3 测量数据（Vector/INCA/ETAS 出） | `asammdf` |
| `.dbc` `.arxml` `.ldf` `.sym` | **报文数据库**（信号定义）——有它才能解出物理值 | `cantools` |
| `.pcap` | 里面套 socketcand / CAN-over-UDP | `tshark` + `scapy` |

```bash
file evi/*                    # 别信扩展名
head -5 evi/trace.asc         # 文本格式直接看头
cantools dump evi/x.dbc | head -30   # 有 DBC 先看定义了哪些信号
```

**关键判断**：**有没有 DBC**。
- 有 → `cantools decode` 直接出物理值（车速/转速/档位/车门），走 §2。
- 没有 → 只能靠 ID 频率 + 差分 + ASCII 猜，走 §1 的"无 DBC 路线"。

---

## 1. 五分钟出结果

```bash
L=evi/trace.blf

# ① 统一成能看的文本（BLF 二进制，先转 ASC 或 log）
can_logconvert $L work/trace.asc          # python-can，blf/asc/log/trc 互转
can_logconvert $L work/trace.log          # log 是 candump 格式，最适合 awk

# ② 有哪些 ID、各多少帧（异常 ID 一眼就出来）
awk '{print $3}' work/trace.log | sed 's/#.*//' | sort | uniq -c | sort -rn

# ③ 人眼可读的完整帧（带 ASCII 列，flag 常直接露在这）
log2long < work/trace.log | head -40

# ④ 有 DBC 就解码
cantools decode evi/x.dbc < work/trace.log | head -60

# ⑤ 找 flag
rg -a -i 'flag|ctf\{' work/trace.asc work/trace.log
strings -a -n 5 $L | rg -i 'flag\{'
```

**无 DBC 路线**（CTF 里很常见）：

```bash
# 每个 ID 的 payload 去重，看谁在变化、谁一直不变
python3 - <<'PY'
import re, collections
frames = collections.defaultdict(list)
for line in open("work/trace.log"):
    m = re.search(r"\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)", line)
    if m: frames[m.group(1).upper()].append(m.group(2).upper())
for cid, ds in sorted(frames.items()):
    uniq = sorted(set(ds))
    print(f"{cid:>4}  {len(ds):5d} 帧  {len(uniq):3d} 种  {uniq[:4]}")
PY
# 某个 ID 的字节逐个位置看变化（定位计数器/校验和/数据位）
```

---

## 2. cantools（DBC 解码）

```bash
cantools dump  evi/x.dbc                      # 全部报文+信号+位布局
cantools dump -m EngineData evi/x.dbc         # 只看某个报文
cantools dump --prune evi/x.dbc               # 枚举值缩名
cantools list  evi/x.dbc                      # 只列名字
cantools decode evi/x.dbc < work/trace.log    # 从 stdin 读 candump 帧
cantools decode -s evi/x.dbc < work/trace.log # 单行输出（好喂 grep）
cantools decode --prune evi/x.dbc < work/trace.log
cantools convert evi/x.dbc out.kcd            # DBC → KCD/ARXML/SYM...
cantools generate_c_source evi/x.dbc -o work/ # 生成 C 解析代码
```

Python 里解码（写脚本时最常用）：

```python
import can, cantools
db = cantools.database.load_file("evi/x.dbc")
for m in can.LogReader("evi/trace.blf"):          # blf/asc/log/trc 都吃
    try:
        sig = db.decode_message(m.arbitration_id, m.data, decode_choices=False)
    except KeyError:
        continue                                   # DBC 里没这个 ID
    print(f"{m.timestamp:9.3f} {m.arbitration_id:#05x} {sig}")
```

**手写一个最小 DBC**（题目只给日志、信号关系靠猜时，自己建库更快）：

```
VERSION ""
BO_ 291 EngineData: 8 ECU
 SG_ EngineSpeed : 0|16@1+ (0.25,0) [0|16383.75] "rpm" ECU
 SG_ VehicleSpeed : 16|8@1+ (1,0) [0|255] "km/h" ECU
 SG_ GearPosition : 24|4@1+ (1,0) [0|15] "" ECU
```
> `0|16@1+` = 起始位 0、长 16、小端(Intel `@1`)、无符号(`+`)；`(0.25,0)` = 精度/偏移。

---

## 3. can-utils（日志转换与统计）

```bash
log2asc  -I work/trace.log -O work/trace.asc vcan0   # log → ASC（注意是 -O，不是 -o）
asc2log  -I work/trace.asc -O work/back.log          # ASC → log
log2long < work/trace.log                            # 带 ASCII 列的长格式，最好读
canbusload vcan0                                     # 总线负载（要真接口）
candump -L vcan0 > work/live.log                     # 现场抓（要接口）
cansniffer vcan0                                     # 只显示变化的字节（要接口）
```

`canbusload` / `candump` / `cansniffer` 需要真实 CAN 口或 `vcan`（`sudo modprobe vcan && sudo ip link add dev vcan0 type vcan`）。
**做题基本只用 `log2asc` / `asc2log` / `log2long` 三个，都不需要接口。**

---

## 4. UDS / OBD-II 诊断报文

诊断帧固定走几个 ID：请求 `0x7E0`–`0x7E7`，响应 `0x7E8`–`0x7EF`（11 位）；29 位常见 `0x18DAxxxx`。

```bash
# 从日志里把诊断帧挑出来
rg ' vcan0 7E[0-9A-F]#' work/trace.log
```

**udsoncan**（解析 + NRC 错误码）：

```python
import udsoncan
from udsoncan import Response

# 直接解一条响应：62 F1 90 + VIN
r = Response.from_payload(bytes.fromhex("62F190") + b"LSVAA123456789012")
print(r.positive, r.service_data)          # True ...

# 负响应 7F 22 31 → 0x31 = RequestOutOfRange
neg = Response.from_payload(bytes.fromhex("7F2231"))
print(neg.code_name)                        # RequestOutOfRange
```

用 `Client` 发请求需要连接对象（`udsoncan.connections` 有 `SocketConnection`、`IsoTPSocketConnection`、`PythonIsoTpConnection`），做题时更常见的是**离线解析**，直接 `Response.from_payload()` 就够。

**Scapy 的汽车层**（组包/拆包，比 udsoncan 轻）：

```python
from scapy.contrib.automotive.uds import UDS, UDS_RDBI
from scapy.contrib.automotive.obd.obd import OBD, OBD_S01
from scapy.contrib.isotp import ISOTP
print(bytes(UDS(service=0x22)/UDS_RDBI(identifiers=[0xF190])).hex())   # 22f190
```

**常用 DID / OBD PID**

| 项 | 请求 | 说明 |
|---|---|---|
| VIN | `22 F1 90` | 17 位 ASCII，车架号 |
| 零件号 | `22 F1 87` | |
| ECU 序列号 | `22 F1 8C` | |
| 诊断会话 | `10 03` | 扩展会话（解锁前置） |
| 读故障码 | `19 02 FF` | DTC |
| 清故障码 | `14 FF FF FF` | |
| 安全访问 | `27 01` / `27 02 <key>` | seed/key，CTF 常考 |
| OBD 转速 | `01 0C` | 返回值 /4 = rpm |
| OBD 车速 | `01 0D` | km/h |
| OBD 冷却液温 | `01 05` | 值 − 40 = °C |

---

## 5. MDF / MF4（测量数据）

```bash
# 看结构（asammdf 没有 mdfinfo 命令，用 python 一行）
tools/venv-auto/bin/python -c "
import asammdf; m = asammdf.MDF('evi/data.mf4')
print(m.version); 
for g in m.groups: print(g.index, [c.name for c in g.channels][:8])
"
```

```python
import asammdf
m = asammdf.MDF("evi/data.mf4")
m.get("VehicleSpeed").samples          # 单信号
df = m.to_dataframe()                  # 全部 → DataFrame
m.export("csv", "work/out.csv")        # 注意 fmt 和 filename 是两个参数
```

**CAN 日志 → MF4**（把解出来的信号存成通用格式）：

```python
import can, cantools, numpy as np
from asammdf import MDF, Signal
db = cantools.database.load_file("evi/x.dbc")
ts, spd = [], []
for msg in can.LogReader("evi/trace.blf"):
    try: d = db.decode_message(msg.arbitration_id, msg.data)
    except KeyError: continue
    if "VehicleSpeed" in d: ts.append(msg.timestamp); spd.append(d["VehicleSpeed"])
mdf = MDF(version="4.10")
mdf.append([Signal(np.array(spd, dtype="float64"), np.array(ts), name="VehicleSpeed", unit="km/h")])
mdf.save("work/decoded.mf4", overwrite=True)
```

> `MDF.extract_bus_logging()` 只对**已经是 MF4 且含 bus logging** 的文件有效，不能直接吃 BLF。BLF → MF4 请走上面这段（asammdf 的 GUI 才能一键转，agent 用不了）。

---

## 6. 典型题目套路

| 题面 | 打法 |
|---|---|
| 「车速被篡改到多少」 | 有 DBC → `cantools decode` 找 `VehicleSpeed`；无 DBC → 找变化规律的字节，按 `x*scale` 试 |
| 「里程表回拨」 | 找单调递增的 3–4 字节计数器，看有没有**回跳** |
| 「谁在伪造报文」 | 同一 ID 出现两种 payload 模式 / 时间间隔异常 / 出现未注册 ID |
| 「车门什么时候开的」 | 位级差分：`DriverDoor` 位从 0→1 的时间戳 |
| 「flag 在哪」 | `log2long` 的 ASCII 列 / `strings` / payload 里找 `flag{`；也可能是**每帧一个字节**拼起来 |
| 「拼字节型 flag」 | 按时间排序取某 ID 的某个字节，`bytes(...).decode()` |
| 「UDS 解锁」 | 抓 `27 01` 的 seed，逆出 key（常见简单算法：取反/加常数/异或固定值），再 `27 02` |
| 「故障码」 | `19 02 FF` 的响应按 3 字节一组解 DTC |
| 「MDF 里找传感器」 | `asammdf` 列通道名 → `get(name).samples` → 找异常区间 |

---

## 7. 坑表（都真踩过）

| 现象 | 原因 / 解法 |
|---|---|
| `cantools decode trace.blf` 报参数错误 | `cantools decode` **只从 stdin 读 candump 文本**，不吃 BLF。先 `can_logconvert x.blf x.log` |
| `ASCWriter` 报 `a bytes-like object is required` | ASC 是文本格式，`open(fn, "w")`；BLF/LOG 才用 `"wb"` |
| `log2asc -o out.asc` 报 invalid option | can-utils 用**大写 `-O`**，且要显式给接口名：`log2asc -I in.log -O out.asc vcan0` |
| `asc2log` 说 `Setting locale to 'de_DE' failed` | 无害，只是日期解析退化成当前时间 |
| `log2long -I x.log` 没输出 | `log2long` **只读 stdin**：`log2long < x.log` |
| `MDF.export("out.csv")` 没生成文件 | 签名是 `export(fmt, filename)`：`export("csv", "out.csv")` |
| 导出的 CSV 变成好几个文件 | asammdf **一个通道组一个 CSV**，名字形如 `out.ChannelGroup_0_Python.csv` |
| `extract_bus_logging` 报错 / 没信号 | 它只处理含 bus logging 的 MF4，不能直接吃 BLF |
| `cantools decode` 一个信号都没解出来 | ID 对不上：`--frame-id-mask` 放宽匹配，或 DBC 是扩展帧（29 位）而日志是 11 位 |
| `candump` 报 `No such device` | 没有 CAN 口，离线分析不需要它，用 `log2asc` 等文本工具 |
| `pip install asammdf` 在 py3.14 上要编译半天/失败 | 用 `tools/venv-auto`（py3.12），别往 `tools/venv` 里塞 |
| `asc2log: command not found` | can-utils 装在 `tools/bin`，`bin/solve` 会自动加 PATH；手跑要先 `export PATH=$PWD/tools/bin:$PATH` |

---

## 8. 装了什么

```
python-can 4.6.1     BLF/ASC/LOG/TRC 读写 + can_logconvert/can_player/can_logger
cantools  45.2.0     DBC/ARXML/KCD 解析 + CLI(cantools decode/dump/generate_c_source)
udsoncan  1.26.1     UDS 服务与 NRC 解析（库，无 CLI）
asammdf   8.8.33     MDF3/MDF4 读写 + to_dataframe + cancompare/canconvert
can-utils 2023.03    30 个命令（deb 解包）：log2asc / asc2log / log2long / canbusload ...
scapy     2.8.0      contrib.automotive：UDS / OBD / DoIP / ISOTP / J1939
```

Python 侧全在 `tools/venv-auto`（py3.12）；`cantools` `can_logconvert` `canconvert` `cancompare` 已链到 `tools/bin/`。
