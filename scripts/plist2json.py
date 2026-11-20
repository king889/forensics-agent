#!/usr/bin/env python3
"""plist2json.py <plist> [-o out.json]  支持 XML/二进制，越界 date 自动清零。"""
import argparse, json, plistlib, struct, sys
ap=argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("-o")
a=ap.parse_args()
raw=open(a.src,'rb').read()
def load(b):
    try: return plistlib.loads(b)
    except Exception:
        b=bytearray(b)
        if b[:8]==b'bplist00' and len(b)>32:
            off_size,ref_size,num,top,offtab=struct.unpack('>6xBBQQQ', bytes(b[-32:]))
            for i in range(num):
                s=offtab+i*off_size
                if s+off_size<=len(b):
                    o=int.from_bytes(bytes(b[s:s+off_size]),'big')
                    if o<len(b) and b[o]==0x33: b[o+1:o+9]=struct.pack('>d',0.0)
        return plistlib.loads(bytes(b))
d=load(raw)
def enc(o):
    if isinstance(o,bytes): return o.hex()
    if isinstance(o,__import__('datetime').datetime): return o.isoformat()
    raise TypeError
txt=json.dumps(d, ensure_ascii=False, indent=1, default=enc)
if a.o: open(a.o,'w',encoding='utf-8').write(txt); print(f"-> {a.o}")
else: print(txt)
