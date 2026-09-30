#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
pro2txt.py · 獨立版：把「腳本所在資料夾」內所有 ProPresenter 檔轉成 txt
═══════════════════════════════════════════════════════════════════
用法：
    把這個檔案丟進放 .pro6 / .pro 檔的資料夾，然後執行
        python3 pro2txt.py
    會在同資料夾建立「轉出txt」資料夾，每個檔各產一個同名 .txt
    （含子資料夾，維持相對路徑；「轉出txt」本身會略過）。

    也可指定資料夾：python3 pro2txt.py <輸入資料夾> [輸出資料夾]

  • .pro6（ProPresenter 6，XML）與 .pro（ProPresenter 7，protobuf）都支援。
  • 單檔零依賴（只用 Python 標準庫）；解析邏輯取自 propresenter_Analysis
    專案的 app.py（RTF parser + 樣式邊界換行修正）與 pro7.py（protobuf
    解碼、cue_groups 顯示順序重建），行為與 App 一致。

輸出格式（歌詞友善）：
    [群組名]                ← 每個群組一行標頭（空名略過）
    第一張投影片的文字…      ← 每張 slide 的所有文字圖層，圖層間以換行相接
                            ← slide 之間空一行
"""

import os
import re
import sys
import base64
import xml.etree.ElementTree as ET

# ═══════════════════════════════════════════════════════════════
# §1  RTF → 明文（取自 app.py §2；省略逆寫用的 span 記錄）
# ═══════════════════════════════════════════════════════════════

_RTF_TOKEN = re.compile(
    r"\\uc0\s?"
    r"|\\u(-?\d+) "
    r"|\\u(-?\d+)\??"
    r"|\\\'([0-9a-fA-F]{2})"
    r"|\\\r?\n"
    r"|\\f(\d+)\s?"
    r"|\\fs(\d+)\s?"
    r"|\\cf(\d+)\s?"
    r"|\\strokec\d+\s?"
    r"|\\b0\s?|\\b\s?"
    r"|\\i0\s?|\\i\s?"
    r"|\\ulnone\s?|\\ul\s?"
    r"|\\[a-zA-Z*]+[-]?\d*\s?"
    r"|([^\\{}\n\r]+)"
    r"|[\n\r]+"
    r"|\\([{}\\])"
    , re.DOTALL
)

_LINEBREAK = re.compile(r"\\\r?\n")


def _dec_hex(pairs, cp):
    """一串 \'XX hex（cp 為碼頁，常見 950）→ 文字；逐位元組退回 cp1252 容錯。"""
    raw = bytes(int(h, 16) for h in pairs)
    try: return raw.decode(f"cp{cp}")
    except Exception: pass
    out = []; i = 0
    while i < len(raw):
        if raw[i] > 0x7F and i + 1 < len(raw):
            try: out.append(raw[i:i+2].decode(f"cp{cp}")); i += 2; continue
            except Exception: pass
        try:    out.append(bytes([raw[i]]).decode("cp1252"))
        except Exception: out.append(f"\\x{raw[i]:02x}")
        i += 1
    return "".join(out)


def _body_bounds(rtf):
    """(header_end, body_end)：正文範圍。含 header-only RTF（Pro7 空層）fallback。"""
    he = None
    for pat in (r"\\partightenfactor0", r"\\pardirnatural", r"\\pard\b"):
        m = re.search(pat, rtf)
        if m: he = m.end(); break
    if he is None:
        m = re.search(r"\\fs\d+", rtf)
        if m:
            he = m.start()
        else:
            he = 0
            for g in re.finditer(r"\{\\\*?\\?[a-zA-Z]+[^{}]*\}", rtf):
                he = g.end()
    while he < len(rtf) and rtf[he] in "\r\n\t ":
        he += 1
    stripped = rtf.rstrip()
    be = stripped.rfind("}")
    if be < he: be = len(stripped)
    return he, be


def parse_rtf_runs(rtf):
    """RTF → [(text, style_key), ...]（含純空白 run；key=(字體,字級,顏色,粗,斜,底)）。"""
    m = re.search(r"\\ansicpg(\d+)", rtf)
    cp = int(m.group(1)) if m else 1252
    fonts = {}
    fm = re.search(r"\{\\fonttbl(.*?)\}", rtf, re.DOTALL)
    if fm:
        for f in re.finditer(r"\\f(\d+)\\(f\w+)(?:\\fcharset(\d+))?\s+([\w\-]+);", fm.group(1)):
            fonts[int(f.group(1))] = f.group(4)
    cmap = {}
    cm = re.search(r"\{\\colortbl(.*?)\}", rtf, re.DOTALL)
    if cm:
        for idx, entry in enumerate(cm.group(1).split(";")):
            r2 = re.search(r"\\red(\d+)\\green(\d+)\\blue(\d+)", entry)
            if r2:
                cmap[idx] = "#{:02X}{:02X}{:02X}".format(*(int(r2.group(i)) for i in (1, 2, 3)))

    he, be = _body_bounds(rtf)
    seg = rtf[he:be]

    runs = []
    cur_fid = next(iter(fonts), None)
    cur_sz = cur_cidx = None
    cur_b = cur_i = cur_u = False
    hbuf = []

    def key():
        return (fonts.get(cur_fid, "?"), cur_sz,
                cmap.get(cur_cidx, "?") if cur_cidx is not None else "?",
                cur_b, cur_i, cur_u)

    def push(text):
        if not text: return
        k = key()
        if runs and runs[-1][1] == k:
            runs[-1][0] += text
        else:
            runs.append([text, k])

    def flush():
        if hbuf:
            push(_dec_hex(hbuf, cp)); hbuf.clear()

    for m2 in _RTF_TOKEN.finditer(seg):
        f = m2.group(0)
        uni = m2.group(1) or m2.group(2)
        if uni is not None:
            flush(); cp2 = int(uni); push(chr(cp2 + 65536 if cp2 < 0 else cp2)); continue
        if m2.group(3) is not None:
            hbuf.append(m2.group(3)); continue
        flush()
        if m2.group(4) is not None: cur_fid = int(m2.group(4)); continue
        if m2.group(5) is not None: cur_sz = int(m2.group(5)) / 2.0; continue
        if m2.group(6) is not None: cur_cidx = int(m2.group(6)); continue
        if f.startswith(r"\b0"): cur_b = False; continue
        if f.startswith("\\b"):  cur_b = True;  continue
        if f.startswith(r"\i0"): cur_i = False; continue
        if f.startswith("\\i"):  cur_i = True;  continue
        if "ulnone" in f:        cur_u = False; continue
        if f.startswith(r"\ul"): cur_u = True;  continue
        if _LINEBREAK.fullmatch(f): push("\n"); continue
        if set(f) <= {"\n", "\r"}: push("\n"); continue
        if m2.group(8) is not None: push(m2.group(8)); continue
        if m2.group(7): push(m2.group(7)); continue
    flush()
    return runs


def _drop_style_break_nl(runs):
    """合併各 run 為明文，並移除「換樣式時多插的那一個換行」（詳見 app.py 檔頭）。"""
    chars = [(ch, k) for t, k in runs for ch in t]
    out = []; i = 0; n = len(chars)
    while i < n:
        if chars[i][0] != "\n":
            out.append(chars[i][0]); i += 1; continue
        j = i
        while j < n and chars[j][0] == "\n": j += 1
        cnt = j - i
        prev = chars[i-1][1] if i > 0 else None
        nxt = chars[j][1] if j < n else None
        if prev is not None and nxt is not None and prev != nxt:
            cnt -= 1
        out.append("\n" * cnt); i = j
    return "".join(out)


def _fix_surrogates(s):
    """合併 UTF-16 代理對（RTF \\uNNNN 對 >U+FFFF 的字用代理對）；
    孤立代理以 U+FFFD 取代，確保可寫成 utf-8。"""
    if not any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        return s
    out = []; i = 0
    while i < len(s):
        o = ord(s[i])
        if 0xD800 <= o <= 0xDBFF and i + 1 < len(s) and 0xDC00 <= ord(s[i+1]) <= 0xDFFF:
            out.append(chr(0x10000 + ((o - 0xD800) << 10) + (ord(s[i+1]) - 0xDC00)))
            i += 2; continue
        out.append("\uFFFD" if 0xD800 <= o <= 0xDFFF else s[i])
        i += 1
    return "".join(out)


def rtf_to_text(rtf):
    return _drop_style_break_nl(parse_rtf_runs(rtf)).strip("\n")


# ═══════════════════════════════════════════════════════════════
# §2  Pro6（XML）→ [(群組名, [slide文字, ...]), ...]
# ═══════════════════════════════════════════════════════════════

def pro6_groups(xml_bytes):
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    gnode = root.find('.//array[@rvXMLIvarName="groups"]')
    result = []
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        slides = []
        snode = g.find('array[@rvXMLIvarName="slides"]')
        for sl in (snode if snode is not None else []):
            parts = []
            disp = sl.find('array[@rvXMLIvarName="displayElements"]')
            for el in (disp if disp is not None else []):
                if el.tag != "RVTextElement": continue
                rn = el.find('NSString[@rvXMLIvarName="RTFData"]')
                if rn is None or not (rn.text or "").strip(): continue
                try:
                    rtf = base64.b64decode(rn.text.strip()).decode("utf-8", errors="replace")
                    txt = rtf_to_text(rtf)
                except Exception:
                    continue
                if txt.strip(): parts.append(txt)
            slides.append("\n".join(parts))
        result.append(((g.get("name") or "").strip(), slides))
    return result


# ═══════════════════════════════════════════════════════════════
# §3  Pro7（protobuf）→ 同上模型（取自 pro7.py；只抽文字）
# ═══════════════════════════════════════════════════════════════

def _read_varint(b, i):
    r = 0; s = 0
    while True:
        if i >= len(b): raise ValueError("protobuf 結構損毀（varint 越界）")
        x = b[i]; i += 1
        r |= (x & 0x7F) << s
        if not x & 0x80: return r, i
        s += 7
        if s > 70: raise ValueError("protobuf 結構損毀（varint 過長）")


def _decode(buf):
    out = {}; i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        f, wt = tag >> 3, tag & 7
        if f == 0: raise ValueError("protobuf 結構損毀（field 0）")
        if wt == 0:   v, i = _read_varint(buf, i)
        elif wt == 1: v = buf[i:i+8]; i += 8
        elif wt == 5: v = buf[i:i+4]; i += 4
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            if i + ln > len(buf): raise ValueError("protobuf 結構損毀（長度越界）")
            v = buf[i:i+ln]; i += ln
        else:
            raise ValueError(f"protobuf 結構損毀（wiretype {wt}）")
        out.setdefault(f, []).append((wt, v))
    return out


def _first(msg, f):
    v = msg.get(f)
    return v[0] if v else None

def _sub(msg, f):
    v = _first(msg, f)
    return _decode(v[1]) if v and v[0] == 2 else {}

def _subs(msg, f):
    return [_decode(v) for wt, v in msg.get(f, []) if wt == 2]

def _str7(msg, f, default=""):
    v = _first(msg, f)
    if not v or v[0] != 2: return default
    try: return v[1].decode("utf-8")
    except UnicodeDecodeError: return default

def _bytes7(msg, f):
    v = _first(msg, f)
    return v[1] if v and v[0] == 2 else b""

def _varint7(msg, f, default=0):
    v = _first(msg, f)
    return v[1] if v and v[0] == 0 else default

def _uuid7(msg, f):
    return _str7(_sub(msg, f), 1).upper()


def is_pro7(raw, name=""):
    """XML（pro6）以 '<' 開頭；protobuf 開頭是 field 1 的 tag(0x0A)。"""
    if raw.lstrip()[:1] == b"<": return False
    if name.lower().endswith((".pro6", ".xml")): return False
    if name.lower().endswith(".pro"): return True
    return raw[:1] == b"\x0a"


def pro7_groups(data):
    """Pro7 .pro bytes → [(群組名, [slide文字, ...]), ...]。
    顯示順序＝cue_groups（field 12）＋各組 cue_identifiers；未入組的 cue
    依檔內順序附在最後（無名群組）——與 pro7.py / ProPresenter 一致。"""
    root = _decode(data)
    if 13 not in root and 3 not in root:
        raise ValueError("不是 ProPresenter 7 簡報檔（找不到 cues/name 欄位）")

    def cue_text(cue):
        pres = None
        for act in _subs(cue, 10):
            p = _sub(_sub(act, 23), 2)
            if p: pres = p; break
        if pres is None: return None          # 非投影片 cue（純媒體/音訊）
        base = _sub(pres, 1)
        parts = []
        for se in _subs(base, 1):
            el = _sub(se, 1)
            if _varint7(el, 16): continue     # hidden
            rtf = _bytes7(_sub(el, 13), 5)
            if not rtf.strip(): continue
            try:
                txt = rtf_to_text(rtf.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if txt.strip(): parts.append(txt)
        return "\n".join(parts)

    cue_by_uuid = {}; cue_order = []
    for cue in _subs(root, 13):
        cu = _uuid7(cue, 1)
        cue_by_uuid[cu] = cue
        cue_order.append(cu)

    groups = []; used = set()
    for cg in _subs(root, 12):
        gname = _str7(_sub(cg, 1), 2)
        slides = []
        for u in _subs(cg, 2):
            us = _str7(u, 1).upper()
            cue = cue_by_uuid.get(us)
            if cue is None: continue
            used.add(us)
            t = cue_text(cue)
            if t is not None: slides.append(t)
        if slides:
            groups.append((gname.strip(), slides))
    leftover = []
    for cu in cue_order:
        if cu in used: continue
        t = cue_text(cue_by_uuid[cu])
        if t is not None: leftover.append(t)
    if leftover:
        groups.append(("", leftover))
    return groups


# ═══════════════════════════════════════════════════════════════
# §4  組合輸出 ＋ 主程式
# ═══════════════════════════════════════════════════════════════

def groups_to_text(groups):
    out = []
    for gname, slides in groups:
        blocks = [t for t in slides if t.strip()]
        if not blocks: continue
        if gname: out.append(f"[{gname}]")
        out.append("\n\n".join(blocks))
        out.append("")
    return _fix_surrogates("\n".join(out).strip("\n") + "\n")


def convert_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    if is_pro7(raw, os.path.basename(path)):
        return groups_to_text(pro7_groups(raw))
    return groups_to_text(pro6_groups(raw))


OUT_NAME = "轉出txt"


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    src = argv[0] if argv else here
    dst = argv[1] if len(argv) > 1 else os.path.join(src, OUT_NAME)
    if not os.path.isdir(src):
        print(f"找不到輸入資料夾：{src}")
        return 1
    os.makedirs(dst, exist_ok=True)
    dst_abs = os.path.abspath(dst)

    targets = []
    for dirpath, dirs, files in os.walk(src):
        # 略過輸出資料夾與隱藏資料夾
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and os.path.abspath(os.path.join(dirpath, d)) != dst_abs]
        for name in sorted(files):
            if name.lower().endswith((".pro6", ".pro")) and not name.startswith("."):
                targets.append(os.path.join(dirpath, name))
    if not targets:
        print(f"{src} 內沒有 .pro6 / .pro 檔。")
        return 1

    ok = fail = 0
    for path in targets:
        rel = os.path.relpath(path, src)
        out_path = os.path.join(dst, os.path.splitext(rel)[0] + ".txt")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        try:
            text = convert_file(path)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            print(f"✗ {rel}: {e}")
            fail += 1
            continue
        print(f"✓ {rel}")
        ok += 1
    print(f"\n完成：{ok} 個成功" + (f"，{fail} 個失敗" if fail else "") + f"\n輸出資料夾：{dst}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
