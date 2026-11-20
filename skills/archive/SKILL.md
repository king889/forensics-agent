---
name: archive
description: 处理压缩包与嵌套归档（zip/7z/rar/tar/gz）—— 列举、解包到 work、递归展开、带密码、文件名乱码、路径穿越风险、binwalk 固件提取。遇到 .zip/.7z/.rar 检材时加载。
---

# 压缩包

## 0. 用 `unpack`，不要裸 `7z x`

```bash
unpack -l evi/sample.zip          # 先看：文件数、解压后大小、是否加密
unpack evi/sample.zip             # 解到 work/unpack/sample/
unpack -p 'PASSWORD' evi/x.zip    # 加密包
```

`unpack` 做的事：只往 `work/` 写、查 `../` 穿越、限制解压后大小（20G）、
文件数（20 万）、自动展开嵌套（3 层）、加密包直接报错而不是卡住等输入。

**只有 `unpack` 报「格式不支持」时才退回 `7z`**，且必须显式 `-owork/...`：

```bash
7z x -y -owork/unpack/x evi/weird.cab
```

## 1. 看内容

```bash
unpack -l evi/sample.zip               # 推荐
7z l -slt evi/sample.zip | head -60    # 需要更细的技术细节时
```

重点：文件数、解压后总大小、`Encrypted = +`、时间戳、文件名。

## 3. 嵌套包

`unpack` **默认自动展开 3 层**，不用手写循环。需要更深：

```bash
unpack --depth 5 evi/outer.zip
```

想看它展开了什么，注意输出里的 `↳ 嵌套:` 行。

## 4. 密码

`unpack` 遇到加密包会直接说「这是加密包」并退出，不会卡住。

```bash
unpack -p 'PASSWORD' evi/locked.zip
```

先确认真的加密了：`unpack -l` 或 `7z l -slt` 看 `Encrypted = +`。

找密码的方向：题目描述、同目录的 `readme.txt`、文件名、图片 EXIF、
`evi/` 里的其他文件。**不要暴力破解**，除非题目明说要（`john` + `zip2john`）：

```bash
zip2john evi/locked.zip > work/hash.txt
john --wordlist=/usr/share/wordlists/rockyou.txt work/hash.txt
```

## 5. 路径穿越检查

`unpack` 解压**之前**就会检查，有穿越路径直接拒绝并列出前 10 条。
手工看的话：

```bash
7z l evi/sample.zip | rg '\.\./|^/|:\\'
```

## 6. 固件 / 磁盘镜像类

```bash
binwalk evi/firmware.bin                       # 看嵌了什么
binwalk -e --run-as=root evi/firmware.bin -C work/bw   # 提取（输出到 work）
```

`binwalk -e` 提取出来的东西在 `_firmware.bin.extracted/`，注意指到 `work/` 下。

squashfs / cramfs / jffs2：

```bash
unsquashfs -d work/rootfs work/bw/_firmware.bin.extracted/0.squashfs
```

## 7. 常见题型

| 问什么 | 怎么查 |
|---|---|
| 包里几个文件 | `7z l` 最后一行 |
| 最大文件 | `7z l -slt \| rg '^Size'` 排序 |
| 创建时间 | `7z l` 的 Date 列 |
| 隐藏文件 | `7z l -slt` 看 `Attributes`，或解包后 `ls -la` |
| 嵌套几层 | 递归展开后数层数 |
| 有密码 | 试题目给的，再看 `readme` |

## 记录示例

```bash
fcase note archive "压缩包内 2 个 JPG，时间戳 2025-09-29 17:18/17:24" \
    --locator "7z l: IQ_Coin_Transactions_1.jpg (734518B), IQ_Coin_type.jpg (89918B)" \
    --src evi/IQ_Coin_Type_Transactions.zip
```

## 注意

- `7z l` 的时间是**本地时区**解释的，实际存的是 DOS 时间，跨时区题要注意
- `.tar.gz` 分两步：先 `tar xf`，或 `7z x` 直接支持
- 大压缩包解出来几十万文件时，先 `7z l | wc -l` 估算规模
