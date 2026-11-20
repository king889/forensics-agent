---
name: disk
description: 分析磁盘镜像与分区（E01/dd/img/raw/bin）—— 分区表、文件系统、目录列举、按 inode 提取、已删除文件恢复、时间线。遇到磁盘镜像、U 盘取证、镜像挂载类题目时加载。
---

# 磁盘镜像分析

工具：Sleuth Kit 的 `mmls` `fsstat` `fls` `icat` `tsk_recover` `blkls` `mactime`，
配合 `file` `xxd` `strings`。TSK 能**直接读 E01**，不需要先转 dd。

```bash
ewfinfo evi/usb.E01          # 元数据：采集人、时间、软件版本、逻辑大小、扇区数
ewfexport evi/usb.E01 work/usb.raw --size 1G   # 需要 raw 时才导出（整盘很慢）
ewfverify evi/usb.E01        # 重算 md5/sha1 和镜像内记录比对
```

## 0. 铁律

**不要挂载镜像**（`mount -o loop` 会改镜像、会触发内核解析器）。
不要 boot 镜像。全部用 TSK 读字节。

## 1. 分区表

```bash
mmls evi/disk.img                    # DOS/GPT 分区表
mmls -b 4096 evi/disk.img            # 扇区是 4096 字节时（GPT + 大扇区）
mmls -t gpt evi/disk.img
mmls evi/usb.E01                     # E01 直接读
```

输出里 `Start` 列是**扇区号**，后面所有命令的 `-o` 都用这个值。

分区偏移换算成字节：`start × 扇区大小`。
例：`Start=614400`、扇区 512 → 偏移 `314572800`。

## 2. 文件系统

```bash
fsstat -o 614400 evi/disk.img | head -40     # 类型、簇大小、卷标、时间范围
```

常见结果：

| 输出 | 含义 |
|---|---|
| `NTFS` | 用 `fls`，注意 `$MFT`、`$UsnJrnl` |
| `FAT16/FAT32` | 无权限、无时间精度 |
| `exFAT` | 时间戳多且精确，恢复率高 |
| `Ext4` | 有 journal，可看删除记录 |
| `HFS+/APFS` | macOS |

## 3. 列目录

```bash
fls -o 614400 -r -p evi/disk.img > work/fls.txt   # 递归 + 完整路径
head -50 work/fls.txt
rg -i 'flag|secret|password' work/fls.txt
```

只列已删除的：

```bash
fls -o 614400 -r -d -p evi/disk.img
```

`fls` 每行开头的 `d/d` `r/r` 是「目录项类型/元数据状态」，
带 `*` 的是**已删除**。

## 4. 按 inode 提取文件

`fls -r -p` 每行最前面有 `r/r * 12345-128-1:` 这样的 inode 号（破折号前那段）。

```bash
icat -o 614400 evi/disk.img 12345 > work/extracted.bin
file work/extracted.bin
```

有 ADS（NTFS 备用数据流）时：`icat -o 614400 evi/disk.img 12345-128-2`

## 5. 批量恢复

```bash
# ① 文件系统还完整：按 inode 遍历
tsk_recover -o 614400 -e evi/disk.img work/recovered
# -e 只恢复已分配文件；去掉 -e 连删除的一起恢复

# ② 文件系统坏了 / 目录项没了：按签名雕刻
photorec /log /d work/carved /cmd evi/disk.img partition_none,search
```

`photorec` 是 TUI，**必须用 `/cmd` 才能非交互跑**，否则会停在分区选择界面。
分区表还在就换成 `partition_1,search`（编号看启动时的分区列表）。

```bash
photorec /log /d work/carved /cmd evi/disk.img partition_none,search fileopt,everything,jpg,png
# 只找特定类型，能快好几倍；fileopt,everything 是全部类型
```

输出在 `work/carved/recup_dir.1/f0002048.jpg` —— 文件名里的数字是**扇区号**，
乘 512 就是原始偏移，方便回到镜像里定位。目录已存在时 photorec 会新建
`recup_dir.1` 而不是覆盖，所以重跑不会丢上次结果。

`foremost` 是同类工具，用法更简单但不读文件系统结构：

```bash
foremost -t jpg,pdf,zip -i evi/disk.img -o work/foremost
```

## 6. 时间线

```bash
fls -o 614400 -r -m / evi/disk.img > work/body.txt
mactime -b work/body.txt -d -z UTC > work/timeline.csv
head -20 work/timeline.csv
```

按时间找"什么时候放进去的"这类题基本靠这个。

## 7. 全文搜索

```bash
blkls -A -o 614400 evi/disk.img | strings -n 6 | rg -i 'flag|ctf'
# -A 只搜未分配空间（找删除的痕迹）
```

或者直接：

```bash
strings -n 8 evi/disk.img | rg -i 'flag\{'
```

## 8. 常见题型

**U 盘里有多少个分区** → `mmls` 数非 Meta 行
**分区起始偏移** → `Start × 扇区大小`
**卷标** → `fsstat`
**删掉的文件** → `fls -d` + `icat`
**某文件创建时间** → `fsstat` / `fls -r -p` 的时间列 / `istat`

```bash
istat -o 614400 evi/disk.img 12345    # 单个 inode 的全部元数据
```

**隐藏分区** → `mmls` 里 `Unallocated` 区间，或手工扫：
`binwalk evi/disk.img | rg -i 'filesystem|partition'`

## 9. LVM / thin pool / BlueStore

服务器镜像常见三层：分区表 → LVM PV → LV（或 thin pool）→ 文件系统。
**别看到"分区里没有文件系统"就放弃**，往下挖一层。

```bash
# 1. 分区里是不是 LVM（看得到 LABELONE / LVM2 001）
strings -t d evi/disk.img | rg -m5 "LABELONE|LVM2 001"

# 2. 把 PV 段切出来（只读检材，产物写 work/）
dd if=evi/disk.img of=work/pv.img bs=512 skip=<start_lba> count=<len> conv=noerror,sync

# 3. 读元数据
pvs --config 'devices{scan=["./work/pv.img"]}' 2>/dev/null
thin_dump -m work/tmeta.bin > work/thin.xml
thin_ls work/tdata.bin
```

现成脚本（切段 + 解析一次做完）：

```bash
scripts/lvm-thin-dump.py evi/disk.img --partition-lba <start> -o work/lvm
```

| 现象 | 含义 |
|---|---|
| `thin_check` 通过但里面什么都没有 | 只说明元数据没坏，**不代表有数据** |
| `METADATA_FREE_BLOCKS=262113` | 元数据区**空闲**块数，不是数据块数，别当"有 26 万块数据" |
| LV 只有 `pve-root` / `pve-swap` | 拿到的是 PVE 宿主机系统盘；业务数据在别的物理盘或 Ceph 里 |
| `thin_ls` 的 `MAPPED_BLOCKS` 全 0 | thin volume 未分配，数据不在这里 |
| 分区带 `ceph_bluestore` 标签 | BlueStore OSD，**没有文件系统**，需要 `ceph-bluestore-tool`（root） |

BlueStore 里捞数据的兜底：按 ext4 超级块签名扫（超级块在 1024 字节偏移，`0x438` 处是 `53 ef`）：

```bash
python3 - <<'PY'
import mmap
f = open('evi/disk02.img', 'rb')
m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
hits, off = [], 0
while len(hits) < 20:
    i = m.find(b'\x53\xef', off)
    if i < 0:
        break
    if (i - 0x438) % 4096 == 0:
        hits.append(i - 0x438)      # 候选超级块位置
    off = i + 1
print(hits)
PY
```

找到候选后按 1 MiB 对齐切一段，`fsstat` 验证是不是 ext4，再 `fls -o`。

## 记录示例

```bash
fcase note disk "镜像有两个数据分区" \
    --locator "mmls: start=614400 (exFAT), start=6062080 (FAT16 hidden)" \
    --src evi/usb.E01
```

## 注意

- E01 是压缩的，随机读比 dd 慢；反复访问同一镜像时先
  `ewfexport` 或 `tsk_recover` 出来
- 30GB 级镜像先确认扇区大小（`mmls -b 4096`），否则分区表全是乱的
- `fls` 的 `-o` 是**扇区数**，不是字节数
- **没有分区表**的单卷镜像（整盘就是一个 NTFS/ext4）：`mmls` 会失败（rc=1），
  直接 `fsstat evi/disk.img` 从偏移 0 读，别反复调 `mmls`
- **大卷 `fls` 很慢**：28 万条目要 200 秒以上。别用默认超时，也别反复重跑；
  跑一次把结果存成清单，之后只 `rg` 清单
- **多人目录的检材**：`方俊郎/phone.E01` 和 `黄志远/phone.E01` 同名，
  索引/清单目录必须用**完整相对路径**命名，否则两套清单互相覆盖
- E01 分卷（`.E01` + `.E02`…）要整组给，只给第一卷才能拼回去
