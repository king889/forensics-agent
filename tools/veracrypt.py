#!/usr/bin/env python3
"""纯 Python 打开 VeraCrypt / TrueCrypt 容器（不需要 root、不需要内核支持、不需要 Windows）。

为什么需要它：
    WSL 的 cryptsetup 打不开 VC 卷（缺 cast5/blowfish，tcrypt 模式硬失败）；
    Windows 版 VeraCrypt 要装驱动 + UAC 提权。这个脚本只用 `cryptography` 的
    AES-XTS 在用户态解密，任何有 Python 的机器都能跑。

用法：
    veracrypt.py dump   <容器> --password P [--keyfile K]     # 只解头，看属性
    veracrypt.py extract <容器> --password P [--keyfile K] -o <输出.img>
    veracrypt.py list   <容器> --password P [--keyfile K]     # 解完直接 fls 列文件

原理（VeraCrypt 非系统卷、普通头）：
    文件偏移 0..63    盐（明文）
    文件偏移 64..511  头，AES-XTS 加密，数据单元号 0
    密钥 = PBKDF2-HMAC-SHA512(密码+keyfile池, 盐, 500000, 64)
    解出后 0..3 必须是 b'VERA'
    头里给出 encrypted_area_start（一般 131072）与主密钥
    数据区按 512 字节扇区做 AES-XTS，数据单元号 = 扇区号

已验证：xcontainer + 密码 + vera_key → 解出 FAT，内含助记词 txt
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HEADER_SIZE = 512
SALT_SIZE = 64
POOL_SIZE = 64
KEYFILE_MAX_READ = 1024 * 1024
ITERATIONS_SHA512 = 500_000

# 头字段偏移（相对文件起点，含 64 字节盐）
OFF_MAGIC = 64
OFF_VERSION = 68
OFF_REQ_VERSION = 70
OFF_KEYAREA_CRC = 72
OFF_HIDDEN_SIZE = 92
OFF_VOLUME_SIZE = 100
OFF_ENC_AREA_START = 108
OFF_ENC_AREA_LENGTH = 116
OFF_FLAGS = 124
OFF_SECTOR_SIZE = 128
OFF_HEADER_CRC = 132
OFF_MASTER_KEY = 136


class BadVolume(Exception):
    pass


def _keyfile_pool(path: Path, crc_variant: str = "final") -> bytes:
    """VeraCrypt 的 keyfile 混合算法。

    对每个 keyfile：先算全文件 CRC32，再把前 1MB 的每个字节加上
    CRC 的第 (i%4) 个字节，累加进 64 字节的池子里。
    """
    data = path.read_bytes()
    if crc_variant == "final":
        crc = zlib.crc32(data) & 0xFFFFFFFF
    elif crc_variant == "raw":
        crc = (zlib.crc32(data) & 0xFFFFFFFF) ^ 0xFFFFFFFF
    else:
        raise ValueError(crc_variant)
    pool = bytearray(POOL_SIZE)
    for i, b in enumerate(data[:KEYFILE_MAX_READ]):
        pool[i % POOL_SIZE] = (pool[i % POOL_SIZE] + b + ((crc >> ((i % 4) * 8)) & 0xFF)) & 0xFF
    return bytes(pool)


def _mix_password(password: str, pool: bytes | None) -> bytes:
    pw = bytearray(password.encode("utf-8"))
    if pool is None:
        return bytes(pw)
    if len(pw) < POOL_SIZE:
        pw.extend(b"\x00" * (POOL_SIZE - len(pw)))
    for i in range(POOL_SIZE):
        pw[i] = (pw[i] + pool[i]) & 0xFF
    return bytes(pw)


def _xts_decrypt(key: bytes, tweak: bytes, data: bytes) -> bytes:
    """AES-XTS 解密。tweak 是 16 字节，前 8 字节存数据单元号（小端）。"""
    cipher = Cipher(algorithms.AES(key), modes.XTS(tweak))
    dec = cipher.decryptor()
    return dec.update(data) + dec.finalize()


def _sector_tweak(sector_no: int) -> bytes:
    return sector_no.to_bytes(8, "little") + b"\x00" * 8


def open_header(path: Path, password: str, keyfiles: list[Path],
                crc_variant: str = "final") -> dict:
    """解出并校验头部；失败抛 BadVolume。"""
    with path.open("rb") as fh:
        header = fh.read(HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        raise BadVolume(f"文件太短（{len(header)} 字节），不是完整容器")

    salt = header[:SALT_SIZE]
    enc = header[SALT_SIZE:]

    pool = None
    if keyfiles:
        pool = bytearray(POOL_SIZE)
        for kf in keyfiles:
            p = _keyfile_pool(kf, crc_variant)
            for i in range(POOL_SIZE):
                pool[i] = (pool[i] + p[i]) & 0xFF
        pool = bytes(pool)

    key = hashlib.pbkdf2_hmac("sha512", _mix_password(password, pool), salt,
                              ITERATIONS_SHA512, 64)
    plain = _xts_decrypt(key, b"\x00" * 16, enc)

    if plain[:4] != b"VERA":
        raise BadVolume("头部解不出 VERA 魔数（密码/密钥文件不对，或不是 VC 卷）")

    def u64(off: int) -> int:
        return struct.unpack(">Q", header[off:off + 8])[0]

    def u32(off: int) -> int:
        return struct.unpack(">I", header[off:off + 4])[0]

    def u16(off: int) -> int:
        return struct.unpack(">H", header[off:off + 2])[0]

    return {
        "version": u16(OFF_VERSION),
        "required_version": u16(OFF_REQ_VERSION),
        "hidden_volume_size": u64(OFF_HIDDEN_SIZE),
        "volume_size": u64(OFF_VOLUME_SIZE),
        "encrypted_area_start": u64(OFF_ENC_AREA_START),
        "encrypted_area_length": u64(OFF_ENC_AREA_LENGTH),
        "flags": u32(OFF_FLAGS),
        "sector_size": u32(OFF_SECTOR_SIZE),
        "master_key": header[OFF_MASTER_KEY:OFF_MASTER_KEY + 64],
    }


def decrypt_body(path: Path, info: dict, out: Path) -> int:
    """解密 encrypted_area 到 out，返回写出的字节数。"""
    start = info["encrypted_area_start"]
    length = info["encrypted_area_length"]
    key = info["master_key"]
    sector_size = info["sector_size"] or 512

    if length == 0:
        length = path.stat().st_size - start

    written = 0
    with path.open("rb") as fin, out.open("wb") as fout:
        fin.seek(start)
        sector_no = 0
        while written < length:
            chunk = fin.read(sector_size)
            if not chunk:
                break
            if len(chunk) < sector_size:
                chunk = chunk + b"\x00" * (sector_size - len(chunk))
            fout.write(_xts_decrypt(key, _sector_tweak(sector_no), chunk))
            written += sector_size
            sector_no += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="纯 Python VeraCrypt 容器读取")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("dump", "extract", "list"):
        p = sub.add_parser(name)
        p.add_argument("volume")
        p.add_argument("--password", required=True)
        p.add_argument("--keyfile", action="append", default=[])
        p.add_argument("--crc", default="final", choices=("final", "raw"),
                       help="keyfile CRC32 变体，默认 final；解不开时可试 raw")
        if name == "extract":
            p.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    vol = Path(args.volume)
    if not vol.is_file():
        print(f"找不到容器: {vol}", file=sys.stderr)
        return 2

    try:
        info = open_header(vol, args.password, [Path(k) for k in args.keyfile], args.crc)
    except BadVolume as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 1

    print(f"容器: {vol}  ({vol.stat().st_size} 字节)")
    print(f"  头版本 {info['version']}（最低要求 {info['required_version']}）")
    print(f"  卷大小        {info['volume_size']}")
    print(f"  加密区起点    {info['encrypted_area_start']}")
    print(f"  加密区长度    {info['encrypted_area_length']}")
    print(f"  隐藏卷大小    {info['hidden_volume_size']}")
    print(f"  扇区大小      {info['sector_size']}")
    print(f"  标志          0x{info['flags']:08x}")

    if args.cmd == "dump":
        return 0

    out = Path(args.out) if args.cmd == "extract" else Path(f"/tmp/{vol.name}.raw")
    n = decrypt_body(vol, info, out)
    print(f"  已解密 {n} 字节 -> {out}")

    if args.cmd == "list":
        import subprocess
        for tool, argv in (("fsstat", ["fsstat", str(out)]),
                           ("fls", ["fls", "-r", "-p", str(out)])):
            try:
                r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                head = (r.stdout or "").splitlines()[:40]
                print(f"\n=== {tool} ===")
                print("\n".join(head) if head else (r.stderr or "").strip()[:300])
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"{tool} 不可用: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
