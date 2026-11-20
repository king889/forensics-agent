---
name: mobile
description: 分析手机备份/导出（Android data 树、iOS 备份、聊天记录 app 数据库）—— 解包、定位 app 数据、读 sqlite、plist、通讯录/短信/微信/WhatsApp、加密库处理。遇到手机取证题或 mobile.zip 时加载。
---

# 手机数据取证

> 检材是 **APK / dex / so / 安卓分区镜像** 时，先看 `android` 技能（jadx、
> apktool、androguard、rizin、simg2img）。这个技能只管**已解出来的数据目录**。

## 0. 先解包到 work/

```bash
unpack -l evi/mobile.zip                 # 先看规模和结构
unpack --out work/mobile evi/mobile.zip  # 解到 work/mobile/
find work/mobile -maxdepth 3 -type d | head -40
```

手机导出动辄几百 MB / 几十万文件，**先看结构再看内容**：

```bash
du -sh work/mobile/*
find work/mobile -type f | wc -l
find work/mobile -type f -name '*.db' -o -name '*.sqlite*' | head -50
find work/mobile -type f -name '*.plist' | head -20
```

## 1. 判断是 Android 还是 iOS

| 特征 | 平台 |
|---|---|
| `data/data/<包名>/`、`/sdcard/`、`build.prop` | Android |
| `AppDomain-*/`、`Manifest.plist`、`Info.plist`、`3d0d7e5fb2ce288813306e4d4636395e047a3d28` | iOS 备份 |
| `com.apple.*` | iOS |

## 1.5 iOS 先跑 iLEAPP（能省掉大半手工）

iOS 提取目录/zip 到手，先整包解析一遍，1300+ 个 artifact 会落成**一张 SQLite**：

```bash
mkdir -p work/ileapp_<stem>
ileapp -t zip -i evi/CHAN_MH_mobile.zip -o work/ileapp_<stem>     # 直接吃 zip，不用解压
# 约 2 分钟，产出 work/ileapp_<stem>/iLEAPP_Output_*/_lava_artifacts.db
```

之后所有问题都用 sqlite 查，别翻 HTML：

```bash
DB=$(ls work/ileapp_<stem>/iLEAPP_Output_*/_lava_artifacts.db)
sqlite3 "$DB" ".tables"                                  # 103 张表，98 张非空
sqlite3 "$DB" "SELECT * FROM get_installed_apps LIMIT 20"
sqlite3 "$DB" "SELECT * FROM applewifiknownnetworks"
sqlite3 "$DB" "SELECT * FROM callhistory ORDER BY 1 DESC LIMIT 10"
```

常用表：`get_installed_apps` `applewifiknownnetworks` `applewifibsslist` `accountconfig`
`callhistory` `addressbook` `calendarevents` `user_settings` `mc_settings_events`
`walstringsdetails`（微信/WhatsApp 字符串）`tcc`（权限）`get_datausage`

`fcase index` 会自动把这个库的表名和行数写进 `meta/index/<检材>.json` 的 `lava` 段，
先看那里再决定查哪张表。

## 2. 常见数据库位置

**Android**

| 内容 | 路径 |
|---|---|
| 短信 | `data/data/com.android.providers.telephony/databases/mmssms.db` |
| 通话 | `.../providers.contacts/databases/calllog.db` |
| 通讯录 | `.../providers.contacts/databases/contacts2.db` |
| 日历 | `.../providers.calendar/databases/calendar.db` |
| 微信 | `data/data/com.tencent.mm/MicroMsg/<32位hash>/EnMicroMsg.db` |
| QQ | `data/data/com.tencent.mobileqq/databases/` |
| WhatsApp | `data/data/com.whatsapp/databases/msgstore.db` |
| 浏览器 | `data/data/com.android.chrome/app_chrome/Default/History` |
| 定位 | `data/data/com.google.android.gms/databases/` |

**iOS**

| 内容 | 路径 |
|---|---|
| 短信 | `HomeDomain/Library/SMS/sms.db` |
| 通讯录 | `HomeDomain/Library/AddressBook/AddressBook.sqlitedb` |
| 通话 | `HomeDomain/Library/CallHistoryDB/CallHistory.storedata` |
| WhatsApp | `AppDomain-com.whatsapp/Library/Media/...` / `ChatStorage.sqlite` |
| 微信 | `AppDomain-com.tencent.xin/Library/WechatPrivate/` |
| 照片 | `CameraRollDomain/Media/DCIM/` |
| 键盘缓存 | `HomeDomain/Library/Keyboard/*.sqlite` |

## 3. 读 sqlite

```bash
sqlite3 work/mobile/.../mmssms.db '.tables'
sqlite3 work/mobile/.../mmssms.db '.schema sms'
sqlite3 -header -column work/mobile/.../mmssms.db \
  'SELECT date,address,body FROM sms ORDER BY date DESC LIMIT 20'
```

`date` 常是 **毫秒时间戳**，转换：

```bash
sqlite3 ... "SELECT datetime(date/1000,'unixepoch') FROM sms LIMIT 5"
```

- iOS 的 `CoreData` 时间是 **2001-01-01 起的秒数**：`datetime(t+978307200,'unixepoch')`
- Android 的 `date` 是毫秒：`/1000`

想快速看所有表的大小：

```bash
for db in $(find work/mobile -name '*.db' -o -name '*.sqlite*'); do
  echo "== $db"
  sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table'" 2>/dev/null | head -10
done
```

## 4. 加密库（SQLCipher）

微信 `EnMicroMsg.db` 等打不开时：

```bash
sqlite3 db '.tables'
# Error: file is not a database   → 是 SQLCipher
```

Android 微信的 key 算法（老版本）：
`md5(IMEI + uin)[:7]`，uin 在 `shared_prefs/auth_info_key_prefs.xml` 或
`system_config_prefs.xml` 里。拿到 key 后：

```bash
sqlcipher db "PRAGMA key='xxxxxxx';" "SELECT count(*) FROM message;"
```

新版本用 `WCDB`，key 在 `com.tencent.mm_preferences.xml` 或需要从内存 dump。
如果题目没给 key，先找 `*.xml` 里的 `uin` / `imei`。

## 5. plist

```bash
python3 -c "import plistlib,sys,json;print(json.dumps(plistlib.load(open(sys.argv[1],'rb')),default=str,indent=2))" file.plist
```

## 6. 媒体与元数据

```bash
exiftool -a -u -g1 work/mobile/.../IMG_0001.jpg
exiftool -r -csv work/mobile/DCIM > work/exif.csv     # 批量
```

GPS、拍摄时间、设备型号常是题目要的。

## 7. 常见题型

| 问什么 | 怎么查 |
|---|---|
| 最后一条短信 / 谁发的 | `mmssms.db` / `sms.db` 按 date 排序 |
| 某联系人电话 | `contacts2.db` 的 `data` 表 + `mimetypes` |
| 装了什么 app | Android: `data/data/` 目录名；iOS: `Manifest.plist` 的 `Applications` |
| 某天做了什么 | 跨库按时间戳汇总 |
| 照片在哪拍的 | `exiftool` 的 GPS |
| 删掉的记录 | sqlite 的 `freelist` + `strings db \| rg` |

## 记录示例

```bash
fcase note mobile "微信数据库存在但为 SQLCipher 加密" \
    --locator "work/mobile/.../EnMicroMsg.db" --src evi/CHAN_MH_mobile.zip
```

## 注意

- 解包后的路径很长，先 `find ... > work/filelist.txt` 再 `rg` 查
- 大量小文件在 `/mnt/d` 上很慢，必要时 `cp -r` 到 `~/scratch/`
- 不要用 `unzip`（中文名乱码），用 `unpack`（内部是 `7z`）

## 踩过的坑（都是真实答错过的）

### App 版本号：查 app 自己的 shared.plist，不是 var/Info.plist

```bash
# 错：这是 App Store 的 iTunesMetadata，版本号少一位
#   var/Info.plist -> Applications.<bundleid>.iTunesMetadata.bundleShortVersionString
#      WhatsApp = 25.14.79

# 对：app 自己写的 SPClientVersion
#   var/mobile/Applications/group.net.whatsapp.WhatsApp.shared/
#       Library/Preferences/group.net.whatsapp.WhatsApp.shared.plist
#      SPClientVersion = 2.25.14.79   ← 这才是"参赛材料中的原文"
```

**注意**：这个 plist 是二进制格式，里面有 30 个越界 date 对象，
`plistlib.load()` 会直接抛 `InvalidFileException: Invalid file`。
必须先修正再解析，否则会误以为文件损坏而绕开它：

```python
import struct, plistlib
raw = bytearray(open(p, 'rb').read())
off_size, ref_size, num, top, offtab = struct.unpack('>6xBBQQQ', raw[-32:])
for i in range(num):                       # 把 0x33(date) 对象的 8 字节清零
    o = int.from_bytes(raw[offtab + i*off_size: offtab + (i+1)*off_size], 'big')
    if o < len(raw) and raw[o] == 0x33:
        raw[o+1:o+9] = struct.pack('>d', 0.0)
d = plistlib.loads(bytes(raw), fmt=plistlib.FMT_BINARY)
```

### 题干限定词不能漏

「有多少个图片文件曾经储存到 **iCloud**」≠「相册里有多少张图片」。

- 相册总数（`Photos.sqlite` `ZKIND=0`）= 36 → 错
- iCloud Drive（`var/mobile/Library/Mobile Documents/`）里的图片 = 2 → 对

看到"曾经/只/全部/首次/最后"这类限定词，先把它拆成一个独立的过滤条件再查，
不要先跑一个宽查询然后把结果当答案。

### Photos.sqlite 常见口径

| 问法 | 查询 |
|---|---|
| 图片总数 | `SELECT count(*) FROM ZASSET WHERE ZKIND=0` |
| 截图张数 | `ZKINDSUBTYPE=10`（或文件名 `.PNG`） |
| 视频 | `ZKIND=1` |
| 某 App 存进来的 | `ZADDITIONALASSETATTRIBUTES.ZIMPORTEDBYBUNDLEIDENTIFIER` |

### App「安装时间」= 当前版本数据目录的创建时间，不是容器根目录

iOS 备份里 `Manifest.db` 的 MBFile 记录带 `Birth`，但同一个 App 有多个候选时间，
容器根目录的 Birth 会被备份恢复/迁移重置，**不等于安装时间**。

正确口径（以 Instagram 为例，实测对上标准答案）：

```python
# 1. 版本号来源：App 自己记的 build 号
plistlib.load(open('.../Documents/version_history.plist','rb'))   # ['722575504']

# 2. 该 build 对应的数据目录（Meta 系 App 的命名规则）
#    Documents/locales/<版本>_<build>/   ->  376.1.0.27.82_722575504

# 3. 这个目录的 Birth 就是安装时间
#    2025-04-26 11:50:47 HKT   ← 标准答案
```

对照实测（同一台 LEUNG 手机）：

| 时间 | 含义 | 是不是答案 |
|---|---|---|
| 2025-04-09 17:21:26 | 容器根 `/` 的 Birth | ❌ 容器创建时间 |
| 2025-04-09 17:21:37 | 插件容器 Birth | ❌ |
| **2025-04-26 11:50:47** | **当前 build 的数据目录 Birth** | ✅ 安装时间 |
| 2025-04-08 08:26:29 | 4 个 locale 配置文件的 Birth | ❌ 资源文件自带时间 |

**注意**：不要用"最早的 Birth"来猜安装时间 —— 微信的某个资源文件 Birth 是
`2011-11-16`，完全不可靠。

其他 App 没有 `version_history.plist` 时，退而求其次看它的
`Documents/<版本号>` / `Library/Application Support/<bundleid>/` 目录 Birth，
并在 evidence 里写明"用的是哪个目录的 Birth"。
