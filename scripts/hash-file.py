#!/usr/bin/env python3
"""hash-file.py <文件...>  一次算 md5/sha1/sha256，大文件流式。"""
import hashlib, sys
for f in sys.argv[1:]:
    hs={k:hashlib.new(k) for k in ('md5','sha1','sha256')}
    with open(f,'rb') as fh:
        while True:
            b=fh.read(8<<20)
            if not b: break
            for h in hs.values(): h.update(b)
    print(f"{f}\t" + "\t".join(f"{k}={v.hexdigest()}" for k,v in hs.items()))
