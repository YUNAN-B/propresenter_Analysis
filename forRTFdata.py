"""
rtf_parser.py  –  ProPresenter XML parser
==========================================
Usage:
    python rtf_parser.py file.xml
    python rtf_parser.py --file file.xml
    python rtf_parser.py                        # interactive
    python rtf_parser.py --rtf "<base64string>"
"""

import base64, os, re, sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote


# ═══════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════

def _rgba_hex(s: str) -> str:
    p = s.strip().split()
    if len(p) < 3: return s
    r, g, b = [round(float(x) * 255) for x in p[:3]]
    a = float(p[3]) if len(p) == 4 else 1.0
    return "transparent" if a == 0.0 else f"#{r:02X}{g:02X}{b:02X}"

def _parse_shadow(s: str) -> dict:
    p = s.split("|")
    if len(p) != 3: return {"raw": s}
    ns = re.findall(r"[-\d.]+", p[2])
    return {"blur": float(p[0]),
            "color": _rgba_hex(p[1]),
            "offset": (round(float(ns[0]), 2), round(float(ns[1]), 2)) if len(ns) >= 2 else (0, 0)}

def _parse_pos(s: str) -> dict:
    n = re.findall(r"[-\d.]+", s)
    return {k: int(float(v)) for k, v in zip(["x","y","z","w","h"], n)}

def _vert(v: str) -> str:
    return {"0":"top","1":"middle","2":"bottom"}.get(v, v)

def _ts_sec(ts: str, scale: str = "90000") -> str:
    try: return f"{int(ts)/int(scale):.2f}s"
    except: return ts

def _video_source_full(url: str) -> str:
    """Return decoded full path from file:// URL."""
    return unquote(url.replace("file://", ""))

def _video_basename(url: str) -> str:
    return os.path.basename(_video_source_full(url))


# ═══════════════════════════════════════════════
# RTF parser
# ═══════════════════════════════════════════════

@dataclass
class FontInfo:
    id: int; name: str; family: str; charset: int

@dataclass
class ColorInfo:
    index: int; r: int; g: int; b: int
    def hex(self): return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

@dataclass
class TextRun:
    text: str; font_name: str; font_size_pt: Optional[float]; color_hex: str
    bold: bool = False; italic: bool = False; underline: bool = False

@dataclass
class RTFResult:
    codepage: int; colors: list; runs: list
    def plain(self): return "".join(r.text for r in self.runs)


def _dec_hex(pairs: list, cp: int) -> str:
    raw = bytes(int(h, 16) for h in pairs)
    try: return raw.decode(f"cp{cp}")
    except: pass
    out = []; i = 0
    while i < len(raw):
        if raw[i] > 0x7F and i + 1 < len(raw):
            try: out.append(raw[i:i+2].decode(f"cp{cp}")); i += 2; continue
            except: pass
        try: out.append(bytes([raw[i]]).decode("cp1252"))
        except: out.append(f"\\x{raw[i]:02x}")
        i += 1
    return "".join(out)

_TOKEN = re.compile(
    r"\\uc0\s?"
    r"|\\u(-?\d+) "
    r"|\\u(-?\d+)\??"
    r"|\\\'([0-9a-fA-F]{2})"
    r"|\\f(\d+)\s?"
    r"|\\fs(\d+)\s?"
    r"|\\cf(\d+)\s?"
    r"|\\strokec\d+\s?"
    r"|\\b0\s?|\\b\s?|\\i0\s?|\\i\s?|\\ulnone\s?|\\ul\s?"
    r"|\\[a-zA-Z*]+[-]?\d*\s?"
    r"|([^\\{}\n\r]+)"
    r"|[\n\r]+"
    , re.DOTALL
)

def parse_rtf(rtf: str) -> RTFResult:
    m = re.search(r"\\ansicpg(\d+)", rtf)
    cp = int(m.group(1)) if m else 1252

    fonts: dict = {}
    fm = re.search(r"\{\\fonttbl(.*?)\}", rtf, re.DOTALL)
    if fm:
        for f in re.finditer(r"\\f(\d+)\\(f\w+)(?:\\fcharset(\d+))?\s+([\w\-]+);", fm.group(1)):
            fid = int(f.group(1))
            fonts[fid] = FontInfo(fid, f.group(4), f.group(2), int(f.group(3) or 0))

    colors: list = []
    cm = re.search(r"\{\\colortbl(.*?)\}", rtf, re.DOTALL)
    if cm:
        for idx, entry in enumerate(cm.group(1).split(";")):
            r2 = re.search(r"\\red(\d+)\\green(\d+)\\blue(\d+)", entry)
            if r2: colors.append(ColorInfo(idx, int(r2.group(1)), int(r2.group(2)), int(r2.group(3))))
    cmap = {c.index: c.hex() for c in colors}

    body = re.sub(r"\{\\fonttbl.*?\}",              "", rtf, flags=re.DOTALL)
    body = re.sub(r"\{\\colortbl.*?\}",             "", body, flags=re.DOTALL)
    body = re.sub(r"\{\\\*\\expandedcolortbl.*?\}", "", body, flags=re.DOTALL)
    body = re.sub(r"\{\\rtf1.*?platform\d+",        "", body, flags=re.DOTALL)
    body = re.sub(r"\\pard[^\n]*\n",                "", body)
    body = re.sub(r"\\pardirnatural[^\n]*\n",        "", body)
    body = body.strip().lstrip("{").rstrip("}")

    runs: list = []; cur_fid = next(iter(fonts), None)
    cur_sz = cur_cidx = None; cur_b = cur_i = cur_u = False; hbuf: list = []

    def fname(): return fonts[cur_fid].name if cur_fid in fonts else "?"
    def fclr():  return cmap.get(cur_cidx, "?") if cur_cidx is not None else "?"

    def flush():
        nonlocal hbuf
        if hbuf: push(_dec_hex(hbuf, cp)); hbuf = []

    def push(text: str):
        if not text: return
        if (runs and runs[-1].font_name == fname() and runs[-1].font_size_pt == cur_sz
                and runs[-1].color_hex == fclr() and runs[-1].bold == cur_b
                and runs[-1].italic == cur_i and runs[-1].underline == cur_u):
            runs[-1].text += text
        else:
            runs.append(TextRun(text, fname(), cur_sz, fclr(), cur_b, cur_i, cur_u))

    for m2 in _TOKEN.finditer(body):
        f = m2.group(0)
        uni = m2.group(1) or m2.group(2)
        if uni is not None:
            flush(); cp2 = int(uni); push(chr(cp2 + 65536 if cp2 < 0 else cp2)); continue
        hx = m2.group(3)
        if hx is not None: hbuf.append(hx); continue
        else: flush()
        if m2.group(4) is not None: cur_fid  = int(m2.group(4)); continue
        if m2.group(5) is not None: cur_sz   = int(m2.group(5)) / 2.0; continue
        if m2.group(6) is not None: cur_cidx = int(m2.group(6)); continue
        if f.startswith(r"\b0"):   cur_b = False; continue
        if f.startswith(r"\b"):    cur_b = True;  continue
        if f.startswith(r"\i0"):   cur_i = False; continue
        if f.startswith(r"\i"):    cur_i = True;  continue
        if "ulnone" in f:          cur_u = False; continue
        if f.startswith(r"\ul"):   cur_u = True;  continue
        if set(f) <= {"\n", "\r"}: push("\n"); continue
        if m2.group(7):            push(m2.group(7)); continue
    flush()
    runs = [r for r in runs if r.text.strip()]
    return RTFResult(cp, colors, runs)

def parse_rtf_b64(b64: str) -> RTFResult:
    return parse_rtf(base64.b64decode(b64.strip()).decode("utf-8", errors="replace"))


# ═══════════════════════════════════════════════
# Output helpers
# ═══════════════════════════════════════════════

I  = "    "   # 4-space indent for layers
II = "      " # 6-space indent for layer details

def _content(text: str) -> str:
    return "{" + text.replace("\n", "\\n") + "}"

def _run_line(r: TextRun, indent: str = II) -> str:
    sz  = f"{r.font_size_pt}pt" if r.font_size_pt else "?"
    tag = f"[{r.font_name}|{sz}|{r.color_hex}"
    styles = [s for s, v in [("bold",r.bold),("italic",r.italic),("underline",r.underline)] if v]
    if styles: tag += "|" + ",".join(styles)
    tag += "]"
    return indent + tag + _content(r.text)

def _shadow_line(el, indent: str) -> Optional[str]:
    sn = el.find('shadow[@rvXMLIvarName="shadow"]')
    if sn is None: return None
    s = _parse_shadow(sn.text)
    return f"{indent}shadow      blur={s['blur']}  color={s['color']}  offset={s['offset']}"

def _stroke_lines(el, indent: str) -> list:
    sd = el.find('dictionary[@rvXMLIvarName="stroke"]')
    if sd is None: return []
    sc = sd.find('NSColor[@rvXMLDictionaryKey="RVShapeElementStrokeColorKey"]')
    sw = sd.find('NSNumber[@rvXMLDictionaryKey="RVShapeElementStrokeWidthKey"]')
    c = _rgba_hex(sc.text) if sc is not None else "?"
    w = sw.text if sw is not None else "?"
    return [f"{indent}strokeColor  {c}", f"{indent}strokeWidth  {w}"]

def _pos_line(el, indent: str) -> str:
    pn = el.find('RVRect3D[@rvXMLIvarName="position"]')
    if pn is None: return f"{indent}position     ?"
    p = _parse_pos(pn.text)
    return f"{indent}position     x={p['x']}  y={p['y']}  w={p['w']}  h={p['h']}"


# ═══════════════════════════════════════════════
# Layer formatters
# ═══════════════════════════════════════════════

def _fmt_text_layer(idx: int, el) -> list:
    lines = []
    attr  = el.attrib

    lines.append(f"{I}▸ layer {idx}  TextElement")
    lines.append(_pos_line(el, II))

    # concise single-line props
    rot  = float(attr.get("rotation","0"))
    props = (f"opacity={attr.get('opacity','?')}"
             f"  verticalAlignment={_vert(attr.get('verticalAlignment',''))}"
             f"  useAllCaps={attr.get('useAllCaps','?')}"
             f"  adjustsHeightToFit={attr.get('adjustsHeightToFit','?')}")
    if rot: props += f"  rotation={rot}"
    lines.append(f"{II}{props}")

    if attr.get("drawingShadow","false") == "true":
        s = _shadow_line(el, II)
        if s: lines.append(s)

    if attr.get("drawingStroke","false") == "true":
        lines.extend(_stroke_lines(el, II))

    if attr.get("fromTemplate","false") == "true":
        lines.append(f"{II}fromTemplate=true")

    rtf_node = el.find('NSString[@rvXMLIvarName="RTFData"]')
    if rtf_node is not None:
        rtf = parse_rtf_b64(rtf_node.text)
        if rtf.colors:
            color_str = "  ".join(f"cf{c.index}={c.hex()}" for c in rtf.colors)
            lines.append(f"{II}RTFColors    {color_str}")
        lines.append("")   # blank line before content
        if not rtf.runs:
            lines.append(f"{II}[empty]")
        else:
            for r in rtf.runs:
                lines.append(_run_line(r, II))

    return lines


def _fmt_shape_layer(idx: int, el) -> list:
    lines = []
    attr  = el.attrib

    lines.append(f"{I}▸ layer {idx}  ShapeElement")
    lines.append(_pos_line(el, II))

    rot = float(attr.get("rotation","0"))
    props = (f"drawingFill={attr.get('drawingFill','?')}"
             f"  fillColor={_rgba_hex(attr.get('fillColor','0 0 0 0'))}"
             f"  opacity={attr.get('opacity','?')}"
             f"  bezelRadius={attr.get('bezelRadius','0')}")
    if rot: props += f"  rotation={rot}"
    lines.append(f"{II}{props}")

    if attr.get("drawingShadow","false") == "true":
        s = _shadow_line(el, II)
        if s: lines.append(s)

    if attr.get("drawingStroke","false") == "true":
        lines.extend(_stroke_lines(el, II))

    if attr.get("fromTemplate","false") == "true":
        lines.append(f"{II}fromTemplate=true")

    return lines


def _fmt_video_cue(cue) -> list:
    if cue is None: return []
    vid = cue.find('RVVideoElement[@rvXMLIvarName="element"]')
    if vid is None: return []
    ca = cue.attrib; va = vid.attrib
    ts  = va.get("timeScale","90000")
    src = va.get("source","")

    lines = []
    lines.append(f"{I}▸ backgroundMediaCue")
    lines.append(f"{II}displayName  {ca.get('displayName','?')}")
    lines.append(f"{II}enabled      {ca.get('enabled','?')}")
    lines.append(f"{II}source       {_video_source_full(src)}")
    lines.append(f"{II}format       {va.get('format','?')}"
                 f"  naturalSize={va.get('naturalSize','?')}"
                 f"  frameRate={va.get('frameRate','?')}")
    lines.append(f"{II}duration     {_ts_sec(va.get('outPoint','0'),ts)}"
                 f"  inPoint={_ts_sec(va.get('inPoint','0'),ts)}"
                 f"  audioVolume={va.get('audioVolume','?')}")
    flip = []
    if va.get("flippedHorizontally","false") == "true": flip.append("H")
    if va.get("flippedVertically","false")   == "true": flip.append("V")
    if flip: lines.append(f"{II}flipped      {''.join(flip)}")
    return lines


# ═══════════════════════════════════════════════
# Slide formatter
# ═══════════════════════════════════════════════

def _fmt_slide(num: int, gname: str, slide) -> str:
    out  = []
    attr = slide.attrib

    # ── slide header ─────────────────────────
    hk = attr.get("hotKey","")
    lb = attr.get("label","")
    nt = attr.get("notes","")
    en = attr.get("enabled","true")
    bg = _rgba_hex(attr.get("backgroundColor","0 0 0 1"))

    out.append("")
    out.append("┄"*62)
    header = f"  slide #{num}  [{gname}]  backgroundColor={bg}"
    if hk: header += f"  hotKey={hk!r}"
    if lb: header += f"  label={lb!r}"
    if nt: header += f"  notes={nt!r}"
    if en != "true": header += "  ⚠ enabled=false"
    out.append(header)
    out.append("┄"*62)

    # background video
    cue = slide.find('RVMediaCue[@rvXMLIvarName="backgroundMediaCue"]')
    video_lines = _fmt_video_cue(cue)
    if video_lines:
        out.extend(video_lines)
        out.append("")

    # display elements
    elements = slide.find('array[@rvXMLIvarName="displayElements"]')
    if elements is None or len(elements) == 0:
        out.append(f"{I}(no displayElements)")
    else:
        for i, el in enumerate(elements):
            if   el.tag == "RVTextElement":  out.extend(_fmt_text_layer(i, el))
            elif el.tag == "RVShapeElement": out.extend(_fmt_shape_layer(i, el))
            else: out.append(f"{I}▸ layer {i}  {el.tag}  (unsupported)")
            out.append("")   # blank line between layers

    return "\n".join(out)


# ═══════════════════════════════════════════════
# Document parser
# ═══════════════════════════════════════════════

def parse_xml_file(xml_path: str):
    xml_path = os.path.expanduser(xml_path)
    if not os.path.isabs(xml_path):
        xml_path = os.path.join(os.getcwd(), xml_path)
    if not os.path.exists(xml_path):
        print(f"[error] file not found: {xml_path}"); sys.exit(1)

    with open(xml_path, "r", encoding="utf-8") as f:
        content = f.read()
    root = ET.fromstring(content)
    doc  = root.attrib

    # ── document header ───────────────────────
    print("═"*62)
    print("  ProPresenter Presentation")
    print("═"*62)
    print(f"  CCLISongTitle   {doc.get('CCLISongTitle','')}")
    print(f"  resolution      {doc.get('width','?')} × {doc.get('height','?')}"
          f"  backgroundColor={_rgba_hex(doc.get('backgroundColor','0 0 0 0'))}")
    print(f"  versionNumber   {doc.get('versionNumber','?')}"
          f"  buildNumber={doc.get('buildNumber','?')}")
    for k, ak in [("CCLIAuthor","CCLIAuthor"), ("CCLIPublisher","CCLIPublisher"),
                  ("CCLICopyrightYear","CCLICopyrightYear"), ("CCLISongNumber","CCLISongNumber")]:
        v = doc.get(ak,"")
        if v: print(f"  {k:<16}  {v}")

    groups = root.find('.//array[@rvXMLIvarName="groups"]')
    glist  = groups.findall("RVSlideGrouping")
    print(f"  groups          {len(glist)}")
    for g in glist:
        nm  = g.get("name","") or "(title)"
        col = _rgba_hex(g.get("color","0 0 0 0"))
        n   = len(g.find('array[@rvXMLIvarName="slides"]'))
        print(f"    • {nm:<16} {n:>2} slides   color={col}")
    print("═"*62)

    slide_num = 0
    for group in glist:
        gname  = group.get("name","") or "(title)"
        slides = group.find('array[@rvXMLIvarName="slides"]')
        for slide in slides:
            slide_num += 1
            print(_fmt_slide(slide_num, gname, slide))


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    if "--rtf" in args:
        rtf = parse_rtf_b64(args[args.index("--rtf")+1])
        for r in rtf.runs: print(_run_line(r, ""))
        return
    if "--file" in args:
        xml_path = args[args.index("--file")+1]
    elif args and not args[0].startswith("--"):
        xml_path = args[0]
    else:
        xml_path = input("Enter XML file path: ").strip()
        if not xml_path: print("[error] no path given"); sys.exit(1)
    parse_xml_file(xml_path)

if __name__ == "__main__":
    main()