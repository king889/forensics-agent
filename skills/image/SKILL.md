---
name: image
description: 分析图片与文件元数据 —— EXIF/GPS、隐写（zsteg/steghide/binwalk）、文件头修复、拼接图、strings 找 flag。遇到 jpg/png/gif/bmp 检材或"图片里有隐藏信息"类题目时加载。
---

# 图片与元数据

## 1. 元数据优先（最便宜的线索）

```bash
exiftool -a -u -g1 evi/photo.jpg          # 全部，包括未知标签
exiftool -csv -r work/mobile/DCIM > work/exif.csv
```

重点看：`GPS Position`、`Create Date`、`Modify Date`、`Make`/`Model`、
`Software`、`Comment`、`XP Comment`、`User Comment`。

```bash
file evi/photo.jpg          # 真实类型（扩展名可能是假的）
identify -verbose evi/photo.jpg | head -40    # ImageMagick
```

## 2. 文件头/尾检查

```bash
xxd evi/photo.jpg | head -5
xxd evi/photo.jpg | tail -5
```

| 类型 | 头 | 尾 |
|---|---|---|
| JPEG | `FF D8 FF` | `FF D9` |
| PNG | `89 50 4E 47` | `49 45 4E 44 AE 42 60 82` |
| GIF | `47 49 46 38` | `3B` |

尾部有大量数据 → 图后面追加了东西：

```bash
# 找 JPEG 结束符之后的内容
python3 - <<'PY'
d = open('evi/photo.jpg','rb').read()
i = d.rfind(b'\xff\xd9')
print('file size', len(d), 'jpeg ends at', i+2, 'appended', len(d)-i-2)
open('work/appended.bin','wb').write(d[i+2:])
PY
file work/appended.bin
```

## 3. 隐写

```bash
binwalk evi/photo.png                     # 嵌了什么
binwalk -e -C work/bw evi/photo.png
zsteg -a evi/photo.png                    # PNG LSB
steghide info evi/photo.jpg               # 先看有没有
steghide extract -sf evi/photo.jpg -p ''  # 空密码常见
```

`zsteg` / `steghide` 没装的话：

```bash
gem install zsteg        # 需要 ruby
sudo apt install steghide
```

PNG 尺寸被改（高度/宽度藏信息）：

```bash
pngcheck -v evi/photo.png
```

## 4. strings（找 flag 最快）

```bash
strings -n 6 evi/photo.jpg | rg -i 'flag|ctf|\{'
strings -n 6 evi/photo.png | head -40
```

## 5. 拼接 / 分片图

多张图按顺序拼（常见于"碎片"题）：

```bash
montage work/part_*.png -tile 10x -geometry +0+0 work/montage.png
```

或按 EXIF 里的 `ImageNumber` 排序再拼。

## 6. 二维码 / 条码

```bash
zbarimg evi/qr.png
```

## 7. 常见题型

| 问什么 | 怎么查 |
|---|---|
| 在哪拍的 | `exiftool` 的 GPS Position |
| 什么时候 | `Create Date` / `DateTimeOriginal` |
| 用什么拍的 | `Make` `Model` |
| 被什么软件改过 | `Software` |
| 藏了文件 | `binwalk` / 尾部追加 |
| 藏了文字 | `zsteg -a` / `steghide` / LSB |
| 图里有 flag | `strings \| rg` |

## 记录示例

```bash
fcase note image "照片拍摄于 2025-09-29 17:18，设备 iPhone 14" \
    --locator "exiftool: DateTimeOriginal / Model" --src evi/IQ_Coin_type.jpg
```

## 注意

- `exiftool` 默认**不改文件**；要改必须显式 `-overwrite_original`，取证时绝不要加
- 修改过的图片 EXIF 常被清空，此时看文件头和 `strings`
- 微信/QQ 转发的图片会被重新压缩，EXIF 基本没了
