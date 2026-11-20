---
name: android
description: Android 取证。APK 反编译（jadx/apktool）、加固识别、敏感字符串、native so 逆向、sparse 镜像转换、应用 SQLite/WAL/加密库、protobuf、ALEAPP 全盘解析。检材是 apk/dex/so/img/安卓数据目录时用。
---

# Android 取证

所有工具都在 `tools/bin`（`bin/ask` 已加进 PATH）。不确定能不能用先跑
`tools/doctor.sh`，它会真的执行每个工具，而不是只看在不在。

## 0. 先认检材

| 拿到什么 | 去哪节 | 一句话 |
|---|---|---|
| `*.apk` | §2 | 就是个 zip，先 `unpack -l` |
| `classes*.dex` | §2.4 | dex2jar / jadx 直读 |
| `lib*/lib*.so` | §2.5 | rizin 看导入表、字符串 |
| `*.img`（安卓分区） | §3.1 | 多半是 sparse，先 simg2img |
| `/data` 整棵树 / zip | §4.1 | ALEAPP 一把梭 |
| `*.db` / `*.sqlite` | §4.2 | sqlite3 `-readonly` |
| `*.db-wal` | §4.3 | 里面常常有删除的消息 |
| 打不开的 db | §4.4 | 可能 SQLCipher |
| `*.pb` / 无后缀二进制 | §4.5 | bbpb 猜结构 |
| 一堆 `*.ldb` / `*.log` | §4.6 | LevelDB |

## 2. APK

### 2.1 先摸骨架（不用 java）

```bash
unpack -l app.apk                              # 文件数、大小、是否加密
apkid app.apk                                  # 加固/壳/编译器 —— 第一个该跑的
apkleaks -f app.apk -o work/leaks.txt          # URL / API key / token
androguard apkid app.apk                       # 包名 + versionCode（JSON）
androguard sign app.apk --hash sha256          # 签名证书指纹
```

`apkid` 报 `jiagu` / `bangcle` / `ijiami` / `tencent` 就是加固了：smali 是壳，
真 dex 一般在 `assets/` 里，别浪费时间读 smali。

### 2.2 反编译

```bash
apktool d -f -o work/apk/app app.apk           # smali + 资源 + 可读 Manifest
jadx -d work/jadx --show-bad-code app.apk      # Java（更好读）
```

大 APK jadx 很慢，先限制范围：

```bash
jadx -d work/jadx --classes com.target.app     # 只看某个包
jadx --single-class com.target.app.Login -d work/one app.apk
```

### 2.3 找线索

```bash
rg -n -i 'https?://|api[_-]?key|secret|token|password|aes|decrypt' work/jadx/sources | head -60
rg -n -i 'AES|DES|RSA|Cipher|getInstance' work/apk/app/smali | head -30
```

APK 里的硬编码密钥最常出现在 `strings.xml`、`BuildConfig`、native so。

### 2.4 dex

```bash
dex2jar work/apk/app/classes.dex -o work/classes.jar    # 给 jd-gui 用
rizin -A -q -c 'afl' work/apk/app/classes.dex | head    # 只看方法列表
```

### 2.5 native so —— 先用 rizin，要读 C 才上 Ghidra

**第一层：rizin，秒级**

```bash
SO=work/apk/app/lib/arm64-v8a/libnative.so
rizin -A -q -c 'afl' "$SO" | head -40              # 函数列表
rz-bin -zz "$SO" | rg -i 'key|secret|http|flag'    # 字符串
rizin -A -q -c 'iz' "$SO" | head -30               # 带地址的字符串
rizin -A -q -c 'pdf @ sym.Java_com_app_Native_decrypt' "$SO"   # 单个函数反汇编
rizin -A -q -c 'axt @ str.FLAG' "$SO"              # 谁引用了这个字符串
```

大部分题目到这一层就够：找字符串 → `axt` 找引用 → `pdf` 看那一个函数。

**第二层：Ghidra，要可读 C 代码**

```bash
SO=work/apk/app/lib/arm64-v8a/libnative.so
mkdir -p work/gh
# 只反编译名字里含 Native 的函数（推荐）
ghidra-headless work/gh p -import "$SO" \
    -postScript DecompileToC.java work/decompiled.c Java_com_app_Native -deleteProject
rg -n 'strcmp|memcmp|"FLAG|aes|decrypt' work/decompiled.c
```

参数是 `过滤:上限`，默认上限 200 个函数：

```bash
... -postScript DecompileToC.java out.c Java_com_app_Native:30   # 最多 30 个
... -postScript DecompileToC.java out.c :50                      # 不看名字，前 50 个
... -postScript DecompileToC.java out.c ALL:0                    # 真全量，很慢
```

**不给过滤会直接拒绝** —— 一个 11MB 的 so 有 1.8 万个函数，全量反编译要 10 分钟。
带过滤通常 **6–20 秒**。

墙钟上限默认 300s，可覆盖：`GHIDRA_TIMEOUT=900 ghidra-headless ...`（`0` = 不限）。

## 3. 镜像

### 3.1 Android sparse image

`file` 显示 `Android sparse image` 就先转 raw，TSK 不认 sparse：

```bash
file evi/system.img
simg2img evi/system.img work/system.raw
mmls work/system.raw
fls -r -o <分区起始扇区> work/system.raw | head -40
```

### 3.2 E01 / 加密卷

```bash
ewfinfo evi/disk.E01                 # 元数据、是否压缩、逻辑大小
mmls evi/disk.E01                    # TSK 直接读 E01
```

## 4. 应用数据

### 4.1 ALEAPP（最快出结果）

输入是**解开的目录**，不是 zip：

```bash
unpack evi/data.zip                       # → work/unpack/data/
aleapp -t fs -i work/unpack/data -o work/aleapp
ls work/aleapp                            # *.html + *.xlsx
```

`-t` 按输入形态选：`fs`（目录）/`tar`/`zip`/`gz`/`raw`。

### 4.2 SQLite

**先拷到 work/ 再打开**，`-readonly` 只是保险：

```bash
cp evi/msg.db work/
sqlite3 -readonly work/msg.db '.tables'
sqlite3 -readonly work/msg.db '.schema messages'
sqlite3 -readonly work/msg.db 'select datetime(timestamp/1000,"unixepoch") as t,body from messages order by t desc limit 20'
```

安卓时间戳几乎都是 **毫秒 UTC**，`/1000` 再 `unixepoch`。

### 4.3 WAL / 删除记录

`-wal` 里有还没合并的记录，常常就是"删掉的消息"：

```bash
cp evi/msg.db evi/msg.db-wal evi/msg.db-shm work/    # 三个一起拷，缺一不可
sqlite_dissect work/msg.db -d work/sd -e             # 完整解析 + 导出
rg -a 'keyword' work/msg.db-wal                      # 粗暴但有效
```

### 4.4 加密库（SQLCipher）

```bash
sqlcipher work/enc.db "PRAGMA key='PASSWORD'; .tables"
sqlcipher work/enc.db "PRAGMA key='PASSWORD'; select * from msg limit 5"
```

密码错会打 `Error: 密码错或不是 SQLCipher 库`（退出码 1）。密码来源：`strings`、
shared_prefs、native so、日志、`build.gradle`。

**不要用普通 `sqlite3` 打开加密库** —— 它可能把文件头写坏。先 `cp` 到 work/。

### 4.5 protobuf

没有 `.proto` 也能看个大概：

```bash
bbpb < work/data.pb
bbpb -e -it json < work/data.pb        # 输入是 json 时反编码
```

有 `.proto` 就用 `protoc --decode_raw < data.pb`。

### 4.6 LevelDB

```bash
ldb-dump work/app/databases/leveldb/          # 全部记录（含删除的）
ldb-dump work/app/databases/leveldb/ --deleted   # 只看已删除的
ldb-dump work/app/databases/leveldb/ --grep flag
ldb-dump work/app/databases/leveldb/ --json > work/ldb.json
```

`ldb-dump` 是纯 Python 实现（`ccl_chromium_reader`），不依赖 leveldb 库，
能读 `.ldb`、`.log`(WAL)、snappy 压缩块，**还会把已删除但仍残留在
`.ldb` 里的记录标成 `DEL` 输出** —— 这是 `rg -a` 做不到的。

输出每行：`状态  序号  来源文件  键  值`，来源文件能区分是落盘的 `.ldb`
还是还没合并的 WAL。

## 5. 时间线

```bash
log2timeline.py --storage-file work/t.plaso work/unpack/data
psort.py -o work/timeline.csv work/t.plaso
psort.py -o work/timeline.csv work/t.plaso 'date > "2025-01-01"'
```

ALEAPP 的 xlsx 里也自带时间线，先看它更快。

## 6. 坑

| 现象 | 原因 / 解法 |
|---|---|
| smali 全是壳的代码 | `apkid` 报加固了，真 dex 在 `assets/`，用 `unpack` 找 |
| `resources.arsc` 打不开 | 二进制格式，用 `apktool` 或 `androguard arsc app.apk -o out.txt` |
| sqlite3 报 `database is locked` | 别开 `-wal` 单文件，三个文件一起拷 |
| `sqlite3` 打开加密库后文件损坏 | 已经坏了，重新 `cp` 原件，改用 `sqlcipher` |
| jadx 卡死 | `--classes` 限制包名，或换 `apktool` 看 smali |
| 时间对不上 | 安卓是 UTC 毫秒；先确认时区再下结论 |
| `simg2img` 说 not sparse | 已经是 raw，直接 `mmls` |
| `aleapp` 报输入错误 | `-t` 要和输入形态一致（目录=fs，zip=zip） |
| `ghidra-headless` 拒绝全量反编译 | 正常，加函数名过滤或 `:50` 上限 |
| Ghidra 跑了好几分钟 | 没给过滤，正在反编译上万个函数；Ctrl-C 后加过滤重跑 |
| `-scriptPath` 报 usage 退出 | 必须放在项目位置/名称**之后**，wrapper 已处理 |
| `sqlcipher` 报 not a database | 密码错，或者这压根不是 SQLCipher 库 |
