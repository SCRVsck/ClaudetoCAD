# -*- coding: utf-8 -*-
"""从 RTF 里抽纯文本（中文按 GBK 合并连续 \\'xx 转义）。"""
import re
import sys


def rtf_text(path):
    raw = open(path, "rb").read()

    # 丢弃图片等二进制组 {\pict ...}
    raw = re.sub(rb"\{\\\*?\\pict.*?\}", b"", raw, flags=re.S)
    s = raw.decode("latin-1")

    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            m = re.match(r"\\'([0-9a-fA-F]{2})", s[i:])
            if m:
                # 连续 \'xx 攒起来一次性按 GBK 解码（汉字是两字节）
                buf = bytearray()
                j = i
                while True:
                    m2 = re.match(r"\\'([0-9a-fA-F]{2})", s[j:])
                    if not m2:
                        break
                    buf.append(int(m2.group(1), 16))
                    j += len(m2.group(0))
                out.append(buf.decode("gbk", "replace"))
                i = j
                continue
            m = re.match(r"\\u(-?\d+)\s?\??", s[i:])
            if m:
                cp = int(m.group(1))
                if cp < 0:
                    cp += 65536
                out.append(chr(cp))
                i += len(m.group(0))
                continue
            m = re.match(r"\\(par|line|pard)\b\s?", s[i:])
            if m:
                out.append("\n")
                i += len(m.group(0))
                continue
            m = re.match(r"\\[a-zA-Z]+-?\d*\s?", s[i:])
            if m:
                i += len(m.group(0))
                continue
            i += 1
            continue
        if ch in "{}":
            i += 1
            continue
        out.append(ch)
        i += 1

    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l.strip() for l in text.splitlines()]
    return "\n".join(l for l in lines if l)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(rtf_text(sys.argv[1]))
