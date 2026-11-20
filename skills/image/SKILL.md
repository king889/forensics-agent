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

## 8. 打乱图块还原（拼图）

题面给「500 张 30×41 的图块，打乱顺序，拼回去读出密码」这类。

**先算，别急着拼**：

```bash
identify evi/tiles/*.png | head -3        # 确认块尺寸一致
ls evi/tiles | wc -l                      # 块数
# 网格 = 总块数分解；图块不是正方形时网格也可能不是整数倍
```

判定与做法：

1. **网格**：`W×H` 使 `W*H == 块数`；常见 21×21、20×25。多出来的纯白块是填充。
2. **块尺寸非正方形**（如 30×41）时，横向和纵向边缘都要单独算差异。
3. **匹配**：对每对相邻块算接缝像素差（右边缘 vs 左边缘、下 vs 上），
   取最小者生长成二维网格。
4. **贪心会卡死**：纯色/渐变背景上接缝差没有区分度，长到一半无候选。
   需要全局优化——逐行匈牙利匹配、模拟退火，或先定四角再按行推进。
5. **验证**：拼好的图要么能 OCR 出文字，要么与原图整体结构吻合；
   只靠"接缝差最小"不够，最后一定要目视或 OCR 确认。

现成脚本（边缘匹配 + 二维生长，做粗排）：

```bash
scripts/image-jigsaw.py evi/tiles -o work/jigsaw.png --grid 21x21
```

脚本对纯色背景会退化，结果只能当初始布局，别直接当答案。

## 记录示例

```bash
fcase note image "照片拍摄于 2025-09-29 17:18，设备 iPhone 14" \
    --locator "exiftool: DateTimeOriginal / Model" --src evi/IQ_Coin_type.jpg
```

## 注意

- `exiftool` 默认**不改文件**；要改必须显式 `-overwrite_original`，取证时绝不要加
- 修改过的图片 EXIF 常被清空，此时看文件头和 `strings`
- 微信/QQ 转发的图片会被重新压缩，EXIF 基本没了
