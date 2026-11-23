"""Repair a file whose UTF-8 text was read as Windows-1252 and re-saved as UTF-8 (Get-Content / Set-Content in Windows PowerShell 5.1)."""
import sys


def undo(ch):
    try:
        return ch.encode("cp1252")
    except UnicodeEncodeError:
        return ch.encode("latin-1")          # the five bytes cp1252 leaves undefined came through as C1 control characters


for path in sys.argv[1:]:
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    bad = sum(text.count(m) for m in ("Â£", "Ã—", "âˆ’", "Â±", "â€", "Ã—"))
    mid = text.count("﻿")
    if bad:
        fixed = b"".join(undo(c) for c in text).decode("utf-8")
        open(path, "wb").write(fixed.encode("utf-8"))
        print(path, "repaired:", bad, "garbled sequences; BOM was", bom)
    else:
        if bom or mid:
            open(path, "wb").write(text.replace("﻿", "").encode("utf-8"))
        print(path, "no garbling found; BOM", bom, "stray BOMs", mid)
