---
name: crypto
description: 加密货币钱包与加密容器取证：VeraCrypt/TrueCrypt 容器、钱包地址、助记词、链上交易
---

# 加密货币 / 加密容器

CTF 里这条链通常是：**加密容器 → 里面的截图/文本 → 钱包地址 → 链上查交易**。
难点从来不是密码学，而是**密码从哪来**。

## 1. 识别加密容器

VeraCrypt / TrueCrypt 容器的特征（没有 magic，别指望 `file` 认出来）：

```bash
ls -l xcontainer            # 大小是 512 的整数倍
xxd xcontainer | head -2    # 前 64 字节是随机 salt，看不出任何东西
binwalk xcontainer          # 无结果
```

对比：7z/zip 有 `PK`、`7z¼¯'` 魔数；VeraCrypt 容器是纯随机。

**判断是不是 VC 容器**：文件大小 % 512 == 0，且开头无魔数，且同目录有
`VeraCrypt*.exe` / `.dmg` 之类的东西（出题人常把软件一起打包）。

## 2. 密码从哪来：跨检材联想，不要爆破

真实案例（本题）的密码是**钱包地址本身** —— 出题人把密码藏在链上公开信息里：

```
U 盘 → Sunny.zip（密码写在 WALLPAPER.JPG 上，用 vlook 读图）
     → xcontainer（VeraCrypt）
     → 密码 = 钱包地址（要从手机聊天/截图里先找到地址）
     → 容器内：一张虚拟货币截图（二维码）+ 一个助记词 txt
```

**做法**：
- 先把全案检材的线索过一遍（简报里的「其他检材的线索」）
- 密码候选：人名、日期、钱包地址、助记词、手机号、设备名
- 明确写进 `fcase deadend` 之前，至少试过这些组合

## 3. 打开容器

### 优先：本机 cryptsetup

```bash
# 只读探测（不挂载、不改动容器）
echo -n "$PASSWORD" | cryptsetup tcryptDump --veracrypt --key-file vera_key xcontainer

# 挂载（需要 root 权限，命令见 bin/vcopen 的输出）
cryptsetup tcryptOpen --veracrypt --key-file vera_key --readonly xcontainer vc
mount -o ro /dev/mapper/vc /mnt/vc && ls -la /mnt/vc
umount /mnt/vc && cryptsetup close vc
```

`bin/vcopen <容器> --password P --keyfile K` 会自动探测并给出该跑什么。

### ⚠️ WSL 上 cryptsetup 会失败（实测）

```
Required kernel crypto interface not available.
Ensure you have algif_skcipher kernel module loaded.
```

这个报错有误导性 —— 真正原因是 cryptsetup 的 tcrypt 模式会**依次试完所有
TrueCrypt/VC 密码组合**（aes / serpent / twofish / cast5 / des3 / blowfish…），
内核缺 cast5/blowfish 时它把 `-ENOENT` 当成**致命错误**而不是跳过。

实测环境：WSL2 内核 6.18.33.2-microsoft-standard-WSL2
- `algif_skcipher` 已加载 ✓
- `/proc/crypto` 里有 `xts(aes)` ✓
- 但缺 `cast5` / `blowfish` / `serpent` / `twofish` ✗ → tcryptDump 直接中止

**结论**：WSL 上不要浪费时间调 cryptsetup。要么换真 Linux，要么用下面的方案。

### 路线 B：WSL 调 Windows 的 VeraCrypt（需要装一次）

WSL interop 可用时（`/proc/sys/fs/binfmt_misc/WSLInterop` 显示 enabled），
可以直接调 Windows 程序。实测：

```bash
cd /mnt/c && cmd.exe /c "ver"          # 成功
tasklist.exe | grep -i vera            # 能看到 Windows 进程
```

**⚠️ 坑：`VeraCrypt Portable.exe` 不是 CLI。**
它是自解压 GUI 安装器，运行就是开界面，`/volume /letter` 这些参数一律不认
（试过：只起来一个 Console 进程，无输出，无挂载）。

**正确的 CLI 是装好之后的 `VeraCrypt.exe`：**

```bash
# 1. 装（Setup 通常和检材放在一起，比如 Sunny.zip 里的 "VeraCrypt Setup 1.25.9.exe"）
#    双击装完即可

# 2. 挂载（路径必须 Windows 格式，不能用 /mnt/d/...）
"/mnt/c/Program Files/VeraCrypt/VeraCrypt.exe" \
  /volume  "D:\path\xcontainer" \
  /letter  X \
  /password "密码" \
  /keyfile  "D:\path\vera_key" \
  /quit /silent

# 3. 读（挂成 X 盘，WSL 里就是 /mnt/x）
ls -la /mnt/x

# 4. 卸
"/mnt/c/Program Files/VeraCrypt/VeraCrypt.exe" /dismount X /quit /silent
```

限制：需要 UAC 提权（VeraCrypt 要装驱动），弹窗时人在机器前点一下即可。

### 备选：纯 Python 解密（无需 root、无需内核支持）

`cryptography` 提供 AES-XTS，可以在用户态解开 VeraCrypt 卷：

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
# VeraCrypt 头：前 64 字节 salt，后 448 字节 AES-XTS 密文
# KDF: PBKDF2-HMAC-SHA512, 500000 轮（非系统卷默认）
# 解出后前 4 字节应为 b'VERA'
```

要点：
- 有 keyfile 时，先把 keyfile 混进密码（VeraCrypt 的 keyfile pool 算法）
- 头解出来校验 `VERA` 魔数 → 密码对不对立刻知道
- 再用头里的 master key 按扇区（512B）AES-XTS 解密数据区
- 数据区通常是 FAT，解完直接 `fls -o 0` 或挂 loop 读

## 4. 容器里的东西怎么读

### 二维码

```bash
zbarimg -q 截图.png            # 已装，直接出内容
zbarimg --raw -q 截图.png      # 只要内容不要前缀
```

二维码里可能是钱包地址、网址、助记词。**别用 vlook 让视觉模型"读"二维码** ——
它会编。二维码必须用 zbarimg 这类确定性解码器。

### 助记词文件

题目常要求给文件的 **MD5**：

```bash
md5sum mnemonic.txt | awk '{print toupper($1)}'
```

注意题目常要求**大写**、无空格。

### 链上交易

钱包地址 + 交易哈希 → bscscan / etherscan 查：

- 存入记录数
- 支账地址（counterparty）
- 转账金额（注意 decimals，BEP-20 常见 18 位，本题 IQ Coin 是整数）
- 余额

**联网风险**：查询会把钱包地址发给第三方。CTF 无所谓，真实案件要先脱敏。

## 5. 常见坑

| 坑 | 说明 |
|---|---|
| 密码是地址/助记词 | 不要一上来就爆破，先跨检材找 |
| 钱包地址大小写 | EIP-55 校验和大小写有意义，照抄别转小写 |
| 金额小数位 | BEP-20 的 decimals 可能是 0/6/18，别自作主张除以 1e18 |
| 二维码 | 用 zbarimg，不要用视觉模型 |
| 容器大小 | 别把容器大小和里面文件系统大小搞混 |
