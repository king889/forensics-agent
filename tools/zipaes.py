#!/usr/bin/env python3
"""WinZip-AES 加密 zip 的密码校验器（字典攻击）。

为什么需要这个：
    fcrackzip / bkcrack 只支持老式 ZipCrypto。WinZip-AES（compression method 99）
    用 PBKDF2-HMAC-SHA1 派生密钥，两套工具都用不了。

原理（WinZip AES 规范）：
    keymat = PBKDF2-HMAC-SHA1(password, salt, 1000, keylen*2 + 2)
    keymat[0:keylen]            = AES 密钥
    keymat[keylen:2*keylen]     = HMAC-SHA1 认证密钥
    keymat[2*keylen:2*keylen+2] = 密码校验值
    salt 长度：AES-128=8 / AES-192=12 / AES-256=16 字节
    条目末尾还有 10 字节 HMAC-SHA1 认证码，覆盖整段密文

两段判定（很重要）：
    1. 快速筛：比对 2 字节校验值。误报率 1/65536，对千万级字典会产生几百个假阳性。
    2. 权威判：用派生密钥对整段密文算 HMAC-SHA1，和条目末尾 10 字节比对。
       只有第 2 步过了才算真密码 —— 曾经因为只用第 1 步，把假阳性 "antoque" 当成密码。

用法：
    zipaes.py <zip> <wordlist> [--workers N]
    zipaes.py evi/x.zip /tmp/rockyou.txt

退出码：0 找到，1 没找到，2 参数/格式错误。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import multiprocessing as mp
import os
import struct
import sys
import time
import zipfile

SIG_LOCAL = b"PK\x03\x04"
EXTRA_AES = 0x9901
SALT_LEN = {1: 8, 2: 12, 3: 16}  # 1=AES-128, 2=AES-192, 3=AES-256
KEY_LEN = {1: 16, 2: 24, 3: 32}
ITERATIONS = 1000
HMAC_LEN = 10


class AesEntry:
    """一个 WinZip-AES 条目的判定材料。"""

    __slots__ = ("salt", "verifier", "strength", "data_offset", "data_len", "mac")

    def __init__(self, salt, verifier, strength, data_offset, data_len, mac):
        self.salt = salt
        self.verifier = verifier
        self.strength = strength
        self.data_offset = data_offset
        self.data_len = data_len
        self.mac = mac

    @property
    def key_len(self) -> int:
        return KEY_LEN[self.strength]


def read_aes_entry(zip_path: str) -> AesEntry | None:
    """解析第一个 WinZip-AES 条目，取 salt / 校验值 / 密文位置 / HMAC。"""
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if i.compress_type == 99]
        if not infos:
            return None
        # 挑最小的条目：假阳性复核时要读全密文算 HMAC，越小越快
        info = min(infos, key=lambda i: i.compress_size)

        with open(zip_path, "rb") as fh:
            fh.seek(info.header_offset)
            header = fh.read(30)
            if len(header) < 30 or header[:4] != SIG_LOCAL:
                raise ValueError(f"本地文件头异常 @ offset {info.header_offset}")
            name_len, extra_len = struct.unpack("<HH", header[26:30])
            fh.seek(info.header_offset + 30 + name_len)
            extra = fh.read(extra_len)
            payload_offset = fh.tell()

            strength = None
            pos = 0
            while pos + 4 <= len(extra):
                field_id, field_len = struct.unpack("<HH", extra[pos:pos + 4])
                body = extra[pos + 4:pos + 4 + field_len]
                if field_id == EXTRA_AES and len(body) >= 7:
                    strength = body[4]
                pos += 4 + field_len

            if strength not in SALT_LEN:
                raise ValueError(f"没找到 0x9901 AES extra 字段（strength={strength}）")

            salt_len = SALT_LEN[strength]
            head = fh.read(salt_len + 2)
            salt, verifier = head[:salt_len], head[salt_len:salt_len + 2]
            if len(verifier) < 2:
                raise ValueError("加密载荷太短，读不到校验值")

            data_len = info.compress_size - salt_len - 2 - HMAC_LEN
            if data_len <= 0:
                raise ValueError("密文长度为负，条目结构异常")
            data_offset = payload_offset + salt_len + 2
            fh.seek(payload_offset + info.compress_size - HMAC_LEN)
            mac = fh.read(HMAC_LEN)
            if len(mac) < HMAC_LEN:
                raise ValueError("读不到条目末尾的 HMAC")

    return AesEntry(salt, verifier, strength, data_offset, data_len, mac)


def _derive(password: bytes, salt: bytes, key_len: int) -> tuple[bytes, bytes, bytes]:
    dklen = key_len * 2 + 2
    keymat = hashlib.pbkdf2_hmac("sha1", password, salt, ITERATIONS, dklen)
    return keymat[:key_len], keymat[key_len:2 * key_len], keymat[2 * key_len:]


def _fast_verifier(password: bytes, salt: bytes, key_len: int) -> bytes:
    """算出 keymat 末尾的 2 字节校验值。

    试过“只算第 4 块”的取巧：把块号拼到 salt 后面再让 C 实现只算 20 字节。
    这是错的 —— PBKDF2 会再把 INT(1) 拼到扩展后的 salt 末尾，
    算出来是 salt||INT(4)||INT(1)，不是原来的第 4 块。已验证会得到错值。
    也试过纯 Python 预计算 HMAC 填充，比 C 实现慢。
    所以就用全量 pbkdf2_hmac，AES-256 约 2.7 万次/秒/核。
    """
    dklen = key_len * 2 + 2
    return hashlib.pbkdf2_hmac("sha1", password, salt, ITERATIONS, dklen)[-2:]


def confirm(zip_path: str, entry: AesEntry, password: str) -> bool:
    """权威判定：用密码派生 HMAC 密钥，校验整段密文的认证码。"""
    pw = password.encode("utf-8")
    _, auth_key, _ = _derive(pw, entry.salt, entry.key_len)
    digest = hmac.new(auth_key, digestmod=hashlib.sha1)
    with open(zip_path, "rb") as fh:
        fh.seek(entry.data_offset)
        remaining = entry.data_len
        while remaining > 0:
            block = fh.read(min(1 << 20, remaining))
            if not block:
                return False
            digest.update(block)
            remaining -= len(block)
    return hmac.compare_digest(digest.digest()[:HMAC_LEN], entry.mac)


def _worker(task: tuple[str, int, int, bytes, bytes, int]) -> tuple[list[bytes], int]:
    """在 wordlist 的 [start, end) 字节区间里找密码。

    注意：撞上 2 字节假阳性后**不能提前 return**，否则这个分片剩下的全被跳过。
    曾经因为提前返回，rockyou 只覆盖了 57% 就报“未命中”。
    """
    path, start, end, salt, verifier, key_len = task
    tested = 0
    matches: list[bytes] = []
    with open(path, "rb") as fh:
        fh.seek(start)
        if start > 0:
            # 区间从字节偏移开始，第一行很可能是半截，丢掉
            fh.readline()
        while fh.tell() < end:
            line = fh.readline()
            if not line:
                break
            password = line.rstrip(b"\r\n")
            if not password:
                continue
            tested += 1
            if _fast_verifier(password, salt, key_len) == verifier:
                matches.append(password)
    return matches, tested


def _split(path: str, workers: int) -> list[tuple[str, int, int, bytes, bytes, int]]:
    """把 wordlist 按字节切成 tasks 个区间。"""
    size = os.path.getsize(path)
    n_tasks = max(workers * 8, workers)
    # 块最小 64KB：否则小词表会被切成每块几个字节，行全被截断
    step = max(65536, size // n_tasks)
    return [(path, s, min(s + step, size)) for s in range(0, size, step)]


def crack(zip_path: str, wordlist: str, workers: int) -> int:
    entry = read_aes_entry(zip_path)
    if entry is None:
        print("这不是 WinZip-AES 加密的 zip（没有 method 99 条目）", file=sys.stderr)
        return 2

    size = os.path.getsize(wordlist)
    print(
        f"AES-{entry.key_len * 8}  salt={len(entry.salt)}B  verifier={entry.verifier.hex()}  "
        f"wordlist={size / 1e6:.1f}MB  workers={workers}",
        file=sys.stderr,
    )

    tasks = [
        (path, start, end, entry.salt, entry.verifier, entry.key_len)
        for path, start, end in _split(wordlist, workers)
    ]

    started = time.time()
    candidates: list[bytes] = []
    tested = 0
    done = 0
    with mp.Pool(workers) as pool:
        for matches, n in pool.imap_unordered(_worker, tasks):
            tested += n
            done += 1
            candidates.extend(matches)
            # 进度打到 stderr，方便后台跑的时候 tail 日志
            pct = done * 100 // len(tasks)
            rate = tested / max(1e-9, time.time() - started)
            print(
                f"  进度 {pct:3d}%  已测 {tested:,}  {rate:,.0f} 条/秒  候选 {len(candidates)}",
                file=sys.stderr,
                flush=True,
            )

    elapsed = time.time() - started
    rate = tested / elapsed if elapsed > 0 else 0
    print(
        f"测试 {tested:,} 条 / {elapsed:.1f}s = {rate:,.0f} 条每秒；"
        f"2 字节命中 {len(candidates)} 个候选",
        file=sys.stderr,
    )

    for raw in candidates:
        password = raw.decode("utf-8", "replace")
        if confirm(zip_path, entry, password):
            print(password)
            return 0
        print(f"  假阳性，丢弃: {password}", file=sys.stderr)

    print("未命中", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="WinZip-AES 字典攻击（带 HMAC 复核）")
    ap.add_argument("zip")
    ap.add_argument("wordlist")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    try:
        return crack(args.zip, args.wordlist, args.workers)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
