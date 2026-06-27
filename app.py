r"""
ProParse · 投影片解析 · Streamlit App
═══════════════════════════════════════════════════════════════════
批次檢視 / 編輯 ProPresenter 6（.pro6）檔，特別為雙語歌詞設計。
線上版 https://proparse.streamlit.app/ ；單一檔，無外部後端。

── 術語（ProPresenter / pro6 結構；程式裡到處都是）───────────────────
  pro6 / .pro6 ...... ProPresenter 6 的簡報檔，本質就是一份 XML（utf-8）。
  document .......... 根節點 RVPresentationDocument，帶標題/解析度/CCLI 等屬性。
  group（群組）...... RVSlideGrouping，有 name、color；把投影片分段（主歌/副歌…）。
                      撰寫頁的「段落類型」就是設這個（見 _GROUP_PRESETS）。
  slide（投影片）.... RVDisplaySlide，有 hotKey、label、背景 cue、displayElements。
  displayElements ... slide 底下的「圖層陣列」。
  圖層（layer）...... displayElements 的子元素：RVTextElement（文字，最常動）、
                      RVImageElement / RVVideoElement / RVShapeElement / RVBezierPathElement。
  position .......... RVRect3D，字串「{x y z w h}」。
  RTFData ........... 文字圖層的內文 = base64 編碼的 RTF（解析見 §2 parse_rtf）。
  run（段）.......... 一個文字圖層內「同一種樣式」的連續片段（字體/字級/顏色/粗斜底）；
                      一層可有多個 run。撰寫頁以「整層」為單位編輯，parse / 模板仍以 run 為單位。

所有編輯只動三個維度：圖層（displayElements 子元素）、位置（RVRect3D）、明文（RTFData）。

── 四個分頁（UI 在 §7）＋程式分區 ──────────────────────────────────
  1. 解析 — 唯讀檢視整份結構（§3 把每張排版成文字）。
  2. 模板 — 對全部投影片套一個動作（§TEMPLATES 清單 → §7 dispatch；分類見 _TPL_CAT）。
  3. 撰寫 — 逐「圖層」編輯明文（一層一個多行框，顯示已移除「換樣式多出來的換行」、
            見下方不變量）；存檔時整層套「首字樣式」（第一段的字體/字級/顏色，同層多樣式
            會統一、靜默不提示）；另可設群組/熱鍵、刪投影片。
  4. 創造 — 從純文字產生新的 .pro6。
  分區：§1 工具 · §2 RTF parser · §3 解析頁排版 · §4 RTF 轉換 · §5 結構化解析 ·
        §TEMPLATES · §6 XML 逆寫 · §7 UI。

── 核心不變量（踩坑換來的，動程式碼前務必先讀）─────────────────────
• 不整份 ET round-trip：ET.tostring 會把 <x></x> 折成 <x/>，原始 pro6 從不用自閉合
  標籤、ProPresenter 可能讀不回。→ _xml_to_bytes() 序列化後一律展開回 <x></x>，無損。
• 明文逆寫＝定點字串替換：parse_rtf(keep_empty=True) 記每個 run 文字 token 在原 rtf 的
  絕對 span，只替換被動到的片段、保留 RTF header 與控制字 → 無改動的 byte 完全不變。
• \uc0 陷阱：RTF \uNNNN 後要跳過 \uc 個替代字元（pro6 預設 \uc1）；_encode_run_text()
  一旦用到 \uNNNN 就前置 \uc0，否則 ProPresenter 會吃掉下一個字（I've→I'e）。
• run 邊界一定接換行：同層相鄰 run（樣式改變處）之間一定有換行（實測 100%）；
  parse_rtf 的 span 與 §6 的整層改寫都依賴這點。
• 那個邊界換行是 ProPresenter 的「段落標記」、多出來的：實測若樣式邊界本來就要換行，
  檔案會有兩個換行（一個原本要的、一個段落多的）。→ _drop_style_break_nl() 在「顯示整層
  /合併/套樣式」時，把樣式邊界的連續換行數扣一個（1→0 接成同行、2→1 留一次換行）、
  同樣式換行全保留。撰寫頁顯示、合併段落/雙排、套樣式都走它，避免單行被穿插斷開。
  （注意：這只動「呈現/合併出的明文」，不影響上一條的逐 byte 定點逆寫。）
• 拼音 = opencc(繁→簡) + pypinyin：先轉簡體才命中詞組字典、多音字才準。
• 創造的 .pro6 必須補齊一堆必要屬性/子元素（見 _text_element），否則 ProPresenter 會
  deserialize 失敗 / NSPathStore nil。tests 有守這個結構。

── 其他要知道的 ────────────────────────────────────────────────────
• 快取：_doc_summary（側邊欄用）回純資料、可 @st.cache_data；_parse_xml 含 TextRun
  dataclass 無法穩定 pickle，故不快取（每次重解析，夠快）。
• 卡住自救：工具列設 minimal（藏掉內建 Clear cache），故側邊欄有「🔄 重設」(_soft_reset)
  清全域快取＋暫態旗標；_commit_change 存檔前先驗證 XML 合法，壞檔不入狀態。
• 上傳識別碼 _fk 用「原始檔長度」，必須在 _normalize_preset_groups 之前算（見該處註解）。
• 匯出時自動修復重複 UUID（_dedup_uuids）。

▶ 新增/調整模板：§TEMPLATES 加 {name,desc,action} → §7 dispatch 加 elif → _TPL_CAT 加
  分類；處理函式放 §6（吃 xml_bytes、回 (new_bytes, n)）。測試在 tests/（pytest），
  合成 fixture 由 tests/make_fixtures.py 產生、無版權內容。
"""

import base64
import copy
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import unquote

import streamlit as st


# ═══════════════════════════════════════════════════════════════
# §1  UTILITIES
# ═══════════════════════════════════════════════════════════════

def _rgba_hex(s: str) -> str:
    """ProPresenter 顏色「r g b a」(0~1) → #RRGGBB；a=0 視為 transparent。"""
    p = s.strip().split()
    if len(p) < 3: return s
    r, g, b = [round(float(x) * 255) for x in p[:3]]
    a = float(p[3]) if len(p) == 4 else 1.0
    return "transparent" if a == 0.0 else f"#{r:02X}{g:02X}{b:02X}"

def _parse_pos(s: str) -> dict:
    """RVRect3D 位置「{x y z w h}」→ {x,y,z,w,h}（整數）。"""
    n = re.findall(r"[-\d.]+", s)
    return {k: int(float(v)) for k, v in zip(["x","y","z","w","h"], n)}

def _vert(v: str) -> str:
    return {"0":"top","1":"middle","2":"bottom"}.get(v, v)

def _parse_shadow(s: str) -> dict:
    p = s.split("|")
    if len(p) != 3: return {"raw": s}
    ns = re.findall(r"[-\d.]+", p[2])
    return {
        "blur":   float(p[0]),
        "color":  _rgba_hex(p[1]),
        "offset": (round(float(ns[0]),2), round(float(ns[1]),2)) if len(ns)>=2 else (0,0),
    }

def _ts_sec(ts: str, scale: str = "90000") -> str:
    try:    return f"{int(ts)/int(scale):.2f}s"
    except: return ts

def _video_path(url: str) -> str:
    return unquote(url.replace("file://",""))

def _expand_self_closing(xml: str) -> str:
    """ProPresenter 從不用自閉合標籤；把 ET 產生的 <x/> 展開回 <x></x>，
    使原始檔可逐字節無損 round-trip（已實測）。"""
    return re.sub(r"<([^<>]+?) />",
                  lambda m: f"<{m.group(1)}></{m.group(1).split()[0]}>", xml)

def _xml_to_bytes(root, orig_str: str) -> bytes:
    """ET 樹 → bytes，並展開自閉合標籤、補回 xml 宣告，確保 pro6 相容（見檔頭不變量）。"""
    new_xml = ET.tostring(root, encoding="unicode", xml_declaration=False)
    new_xml = _expand_self_closing(new_xml)
    if orig_str.startswith("<?xml"):
        decl = orig_str[:orig_str.index("?>")+2]
        new_xml = decl + "\n" + new_xml
    return new_xml.encode("utf-8")

def _load_root(xml_bytes):
    """bytes → (root, orig_str)，只 decode 一次。write-back 函式共用，
    orig_str 供 _xml_to_bytes 補回 xml 宣告。"""
    s = xml_bytes.decode("utf-8")
    return ET.fromstring(s), s

def _get_layer_el(xml_bytes, gi, si, li):
    """Convenience: parse XML, return (root, orig_str, layer_element)."""
    orig_str = xml_bytes.decode("utf-8")
    root = ET.fromstring(orig_str)
    g    = root.find('.//array[@rvXMLIvarName="groups"]').findall("RVSlideGrouping")[gi]
    slide = list(g.find('array[@rvXMLIvarName="slides"]'))[si]
    disp  = slide.find('array[@rvXMLIvarName="displayElements"]')
    el    = list(disp if disp is not None else [])[li]
    return root, orig_str, el

def _rtf_node(el):
    """取得圖層元素的 <NSString rvXMLIvarName="RTFData"> 節點（無則 None）。"""
    return el.find('NSString[@rvXMLIvarName="RTFData"]')

def _decode_rtf(node) -> Optional[str]:
    """RTFData 節點的 base64 → RTF 字串（失敗回 None）。"""
    if node is None: return None
    try:
        return base64.b64decode(
            node.text.replace("\n","").replace("\r","").replace(" ","")
        ).decode("utf-8", errors="replace")
    except: return None

def _encode_rtf(node, rtf: str):
    """RTF 字串 → base64 寫回 RTFData 節點。"""
    node.text = base64.b64encode(rtf.encode("utf-8")).decode("ascii")


# ═══════════════════════════════════════════════════════════════
# §2  RTF PARSER
# ═══════════════════════════════════════════════════════════════

@dataclass
class FontInfo:
    id: int; name: str; family: str; charset: int

@dataclass
class ColorInfo:
    index: int; r: int; g: int; b: int
    def hex(self): return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

@dataclass
class TextRun:
    text: str
    font_name: str
    font_size_pt: Optional[float]
    color_hex: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    # 寫入用：此 run 各文字 token 在原 rtf 字串中的絕對 (start,end) 區段
    text_token_spans: list = field(default_factory=list)

@dataclass
class RTFResult:
    codepage: int
    colors: list
    runs: list
    def plain(self): return "".join(r.text for r in self.runs)

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
    r"|\\([{}\\])"             # group 8：跳脫的字面 { } \
    , re.DOTALL
)

def _dec_hex(pairs, cp):
    """一串 \\'XX hex（cp 為碼頁，常見 950）→ 文字；逐位元組退回 cp1252 容錯。"""
    raw = bytes(int(h,16) for h in pairs)
    try: return raw.decode(f"cp{cp}")
    except: pass
    out=[]; i=0
    while i < len(raw):
        if raw[i]>0x7F and i+1<len(raw):
            try: out.append(raw[i:i+2].decode(f"cp{cp}")); i+=2; continue
            except: pass
        try:    out.append(bytes([raw[i]]).decode("cp1252"))
        except: out.append(f"\\x{raw[i]:02x}")
        i+=1
    return "".join(out)

def _body_bounds(rtf: str) -> tuple:
    """回傳 (header_end, body_end)：正文（inline 控制字 + 文字）在 rtf 中的範圍。
    header（fonttbl/colortbl/\\pard…）與尾端 } 以外皆 verbatim 保留。"""
    he = None
    for pat in (r"\\partightenfactor0", r"\\pardirnatural", r"\\pard\b"):
        m = re.search(pat, rtf)
        if m: he = m.end(); break
    if he is None:
        m = re.search(r"\\fs\d+", rtf)
        he = m.start() if m else 0
    while he < len(rtf) and rtf[he] in "\r\n\t ":
        he += 1
    stripped = rtf.rstrip()
    be = stripped.rfind("}")
    if be < he: be = len(stripped)
    return he, be

_LINEBREAK = re.compile(r"\\\r?\n")

def parse_rtf(rtf: str, keep_empty: bool = False) -> RTFResult:
    """把 RTF 解析成 TextRun 串列（font/size/color/style + 文字）。
    每個 run 記錄文字 token 在原 rtf 的絕對 span（text_token_spans），供逆寫定點替換。
    keep_empty=False 會濾掉純空白 run（顯示用）；逆寫時用 True 取完整位置序列。"""
    m  = re.search(r"\\ansicpg(\d+)", rtf)
    cp = int(m.group(1)) if m else 1252
    fonts: dict = {}
    fm = re.search(r"\{\\fonttbl(.*?)\}", rtf, re.DOTALL)
    if fm:
        for f in re.finditer(r"\\f(\d+)\\(f\w+)(?:\\fcharset(\d+))?\s+([\w\-]+);", fm.group(1)):
            fid = int(f.group(1))
            fonts[fid] = FontInfo(fid, f.group(4), f.group(2), int(f.group(3) or 0))
    colors=[]
    cm = re.search(r"\{\\colortbl(.*?)\}", rtf, re.DOTALL)
    if cm:
        for idx, entry in enumerate(cm.group(1).split(";")):
            r2 = re.search(r"\\red(\d+)\\green(\d+)\\blue(\d+)", entry)
            if r2: colors.append(ColorInfo(idx,int(r2.group(1)),int(r2.group(2)),int(r2.group(3))))
    cmap = {c.index: c.hex() for c in colors}

    he, be = _body_bounds(rtf)
    seg = rtf[he:be]

    runs=[]; cur_fid=next(iter(fonts),None)
    cur_sz=cur_cidx=None; cur_b=cur_i=cur_u=False
    hbuf=[]; hbuf_start=[None]
    def fname(): return fonts[cur_fid].name if cur_fid in fonts else "?"
    def fclr():  return cmap.get(cur_cidx,"?") if cur_cidx is not None else "?"
    def style_match(r):
        return (r.font_name==fname() and r.font_size_pt==cur_sz and r.color_hex==fclr()
                and r.bold==cur_b and r.italic==cur_i and r.underline==cur_u)
    def push(text, span):
        if not text: return
        if runs and style_match(runs[-1]):
            runs[-1].text+=text
            runs[-1].text_token_spans.append(span)
        else:
            runs.append(TextRun(text,fname(),cur_sz,fclr(),cur_b,cur_i,cur_u,
                                text_token_spans=[span]))
    def flush(end):
        if hbuf:
            push(_dec_hex(hbuf,cp), (hbuf_start[0], end))
            hbuf.clear(); hbuf_start[0]=None
    for m2 in _RTF_TOKEN.finditer(seg):
        a, b = he+m2.start(), he+m2.end()
        f=m2.group(0)
        uni=m2.group(1) or m2.group(2)
        if uni is not None:
            flush(a); cp2=int(uni); push(chr(cp2+65536 if cp2<0 else cp2),(a,b)); continue
        hx=m2.group(3)
        if hx is not None:
            if hbuf_start[0] is None: hbuf_start[0]=a
            hbuf.append(hx); continue
        flush(a)
        if m2.group(4) is not None: cur_fid =int(m2.group(4)); continue
        if m2.group(5) is not None: cur_sz  =int(m2.group(5))/2.0; continue
        if m2.group(6) is not None: cur_cidx=int(m2.group(6)); continue
        if f.startswith(r"\b0"):  cur_b=False; continue
        if f.startswith(r"\b"):   cur_b=True;  continue
        if f.startswith(r"\i0"):  cur_i=False; continue
        if f.startswith(r"\i"):   cur_i=True;  continue
        if "ulnone" in f:         cur_u=False; continue
        if f.startswith(r"\ul"):  cur_u=True;  continue
        if _LINEBREAK.fullmatch(f): push("\n",(a,b)); continue   # \ + 換行
        if set(f)<={"\n","\r"}:   push("\n",(a,b)); continue
        if m2.group(8) is not None: push(m2.group(8),(a,b)); continue  # 跳脫的 { } \
        if m2.group(7):           push(m2.group(7),(a,b)); continue
    flush(be)
    return RTFResult(cp, colors, runs if keep_empty else [r for r in runs if r.text.strip()])

def parse_rtf_b64(b64: str) -> RTFResult:
    """RTFData base64 字串 → 直接 parse_rtf（顯示路徑用，不取 span）。"""
    return parse_rtf(base64.b64decode(b64.strip()).decode("utf-8",errors="replace"))

def _style_key(r):
    """run 的樣式指紋（字體/字級/顏色/粗斜底）；測試用的精簡 stub 缺欄位時以 None 補。"""
    g=lambda k: getattr(r,k,None)
    return (g("font_name"),g("font_size_pt"),g("color_hex"),g("bold"),g("italic"),g("underline"))

def _drop_style_break_nl(runs) -> str:
    """合併各段為純明文，並移除「換樣式時多插的那一個換行」。

    ProPresenter 在樣式切換處會多放一個換行（段落標記）；實測：若樣式邊界本來就要
    換行，檔案會有兩個換行（一個原本要的、一個段落多出來的）。故規則為——
      • 樣式邊界（前後兩字樣式不同）上的連續換行，數量一律減一：
        1 個（純樣式切換）→ 接成同一行；2 個 → 留 1 個（使用者真的要的那次換行）。
      • 同樣式之間的換行全部保留（本來就要的斷行；含空行/段落分隔）。
    傳入完整 run 串列（keep_empty=True，含純空白 run）才不會漏掉交界換行。"""
    chars=[(ch,_style_key(r)) for r in runs for ch in r.text]
    out=[]; i=0; n=len(chars)
    while i<n:
        if chars[i][0]!="\n":
            out.append(chars[i][0]); i+=1; continue
        j=i
        while j<n and chars[j][0]=="\n": j+=1     # 連續換行群組 [i,j)
        cnt=j-i
        prev=chars[i-1][1] if i>0 else None       # 群組前一個字的樣式
        nxt =chars[j][1]   if j<n else None       # 群組後一個字的樣式
        if prev is not None and nxt is not None and prev!=nxt:
            cnt-=1                                # 扣掉樣式切換多出來的段落換行
        out.append("\n"*cnt); i=j
    return "".join(out)


# ═══════════════════════════════════════════════════════════════
# §3  RTF DISPLAY  (解析 tab)
# ═══════════════════════════════════════════════════════════════

_I  = "    "
_II = "      "

def _content(t): return "{" + t.replace("\n","\\n") + "}"
def _T(a, k): return a.get(k, "false") == "true"            # 屬性是否為 "true"
def _rot(a):                                                # 旋轉後綴（0 則空）
    r=float(a.get("rotation","0")); return f"  rotation={r}" if r else ""
def _flip(a):                                               # 翻轉標記 H/V
    return "".join(c for c,k in [("H","flippedHorizontally"),("V","flippedVertically")] if _T(a,k))

def _run_line(r, indent=_II):
    sz  = f"{r.font_size_pt}pt" if r.font_size_pt else "?"
    tag = f"[{r.font_name}|{sz}|{r.color_hex}"
    styles=[s for s,v in [("bold",r.bold),("italic",r.italic),("underline",r.underline)] if v]
    if styles: tag+="|"+",".join(styles)
    return indent+tag+"]"+_content(r.text)

def _fmt_pos_line(el):
    pn=el.find('RVRect3D[@rvXMLIvarName="position"]')
    if pn is None: return None
    p=_parse_pos(pn.text)
    return f"{_II}position     x={p['x']}  y={p['y']}  w={p['w']}  h={p['h']}"

def _layer_head(idx, kind, a):
    name=a.get("displayName","")
    h=f"{_I}▸ layer {idx}  {kind}"
    if name and name!=kind: h+=f"  '{name}'"
    return h

def _head_pos(idx, kind, el):
    """三種圖層共用的開頭：標頭 + 位置行。"""
    lines=[_layer_head(idx,kind,el.attrib)]
    pl=_fmt_pos_line(el)
    if pl: lines.append(pl)
    return lines

def _fmt_decorations(el, a):
    """共用：shadow / stroke / fromTemplate / locked。"""
    lines=[]
    if _T(a,"drawingShadow"):
        sn=el.find('shadow[@rvXMLIvarName="shadow"]')
        if sn is not None:
            s=_parse_shadow(sn.text)
            lines.append(f"{_II}shadow       blur={s['blur']}  color={s['color']}  offset={s['offset']}")
    if _T(a,"drawingStroke"):
        sd=el.find('dictionary[@rvXMLIvarName="stroke"]')
        if sd is not None:
            sc=sd.find('NSColor[@rvXMLDictionaryKey="RVShapeElementStrokeColorKey"]')
            sw=sd.find('NSNumber[@rvXMLDictionaryKey="RVShapeElementStrokeWidthKey"]')
            lines.append(f"{_II}strokeColor  {_rgba_hex(sc.text) if sc is not None else '?'}")
            lines.append(f"{_II}strokeWidth  {sw.text if sw is not None else '?'}")
    if _T(a,"fromTemplate"): lines.append(f"{_II}fromTemplate=true")
    if _T(a,"locked"):       lines.append(f"{_II}locked=true")
    return lines

def _fmt_text_layer(idx, el):
    a=el.attrib; lines=_head_pos(idx,"TextElement",el)
    props=(f"opacity={a.get('opacity','?')}  verticalAlignment={_vert(a.get('verticalAlignment',''))}"
           f"  useAllCaps={a.get('useAllCaps','?')}  adjustsHeightToFit={a.get('adjustsHeightToFit','?')}"+_rot(a))
    dd=a.get("displayDelay","0")
    if dd not in ("0","0.000000",""): props+=f"  displayDelay={dd}"
    lines.append(f"{_II}{props}")
    if _T(a,"drawingFill"):
        lines.append(f"{_II}fill         {_rgba_hex(a.get('fillColor','0 0 0 0'))}")
    if _T(a,"drawLineBackground"):
        lines.append(f"{_II}lineBg       type={a.get('lineBackgroundType','?')}"
                     f"  color={_rgba_hex(a.get('fillColor','0 0 0 0'))}  vOffset={a.get('lineFillVerticalOffset','0')}")
    lines+=_fmt_decorations(el,a)
    rn=el.find('NSString[@rvXMLIvarName="RTFData"]')
    if rn is not None:
        rtf=parse_rtf_b64(rn.text)
        if rtf.colors:
            lines.append(f"{_II}RTFColors    "+"  ".join(f"cf{c.index}={c.hex()}" for c in rtf.colors))
        lines.append("")
        lines+=[_run_line(r,_II) for r in rtf.runs] or [f"{_II}[empty]"]
    return lines

def _fmt_shape_layer(idx, el):
    a=el.attrib; lines=_head_pos(idx,"ShapeElement",el)
    lines.append(f"{_II}drawingFill={a.get('drawingFill','?')}  fillColor={_rgba_hex(a.get('fillColor','0 0 0 0'))}"
                 f"  opacity={a.get('opacity','?')}  bezelRadius={a.get('bezelRadius','0')}"+_rot(a))
    lines+=_fmt_decorations(el,a)
    return lines

def _fmt_image_layer(idx, el):
    a=el.attrib; lines=_head_pos(idx,"ImageElement",el)
    lines.append(f"{_II}source       {_video_path(a.get('source',''))}")
    props=(f"format={a.get('format','?')}  opacity={a.get('opacity','?')}"
           f"  scaleBehavior={a.get('scaleBehavior','?')}  scaleSize={a.get('scaleSize','?')}"+_rot(a))
    if (fp:=_flip(a)): props+=f"  flipped={fp}"
    lines.append(f"{_II}{props}")
    if _T(a,"drawingFill"):
        lines.append(f"{_II}fill         {_rgba_hex(a.get('fillColor','0 0 0 0'))}")
    lines+=_fmt_decorations(el,a)
    return lines

def _fmt_video_layer(idx, el):
    a=el.attrib; lines=_head_pos(idx,"VideoElement",el); ts=a.get("timeScale","90000")
    lines+=[f"{_II}source       {_video_path(a.get('source',''))}",
            f"{_II}format       {a.get('format','?')}  naturalSize={a.get('naturalSize','?')}  frameRate={a.get('frameRate','?')}",
            f"{_II}duration     out={_ts_sec(a.get('outPoint','0'),ts)}  in={_ts_sec(a.get('inPoint','0'),ts)}  audioVolume={a.get('audioVolume','?')}",
            f"{_II}playback     behavior={a.get('playbackBehavior','?')}  rate={a.get('playRate','?')}  scaleBehavior={a.get('scaleBehavior','?')}"+_rot(a)]
    if (fp:=_flip(a)): lines.append(f"{_II}flipped      {fp}")
    lines+=_fmt_decorations(el,a)
    return lines

def _fmt_bezier_layer(idx, el):
    a=el.attrib; lines=_head_pos(idx,"BezierPathElement",el)
    shape=[s for s,k in [("circle","isCircle"),("rect","isRectangle"),("closed","shouldClose")] if _T(a,k)]
    lines.append(f"{_II}drawingFill={a.get('drawingFill','?')}  fillColor={_rgba_hex(a.get('fillColor','0 0 0 0'))}"
                 f"  opacity={a.get('opacity','?')}  feather={a.get('feather','0')}"
                 +(f"  shape={','.join(shape)}" if shape else "")+_rot(a))
    pts=el.find('array[@rvXMLIvarName="points"]')
    if pts is not None: lines.append(f"{_II}points       {len(pts)} 個節點")
    lines+=_fmt_decorations(el,a)
    return lines

def _fmt_generic_layer(idx, el):
    """未特別支援的元素：至少印出標頭、位置與幾個共通屬性。"""
    a=el.attrib; lines=_head_pos(idx, el.tag.replace("RV",""), el)
    common=[f"{k}={a[k]}" for k in ("opacity","source","format","drawingFill","fillColor") if a.get(k)]
    if common: lines.append(f"{_II}{'  '.join(common)}")
    lines+=_fmt_decorations(el,a)
    return lines

def _fmt_slide_code(num, gname, slide_el):
    """把一張投影片排版成解析頁的唯讀文字（標頭 + 轉場/計時 + 背景 cue + 各圖層）。"""
    a=slide_el.attrib; out=[]
    hk=a.get("hotKey",""); lb=a.get("label",""); nt=a.get("notes",""); en=a.get("enabled","true")
    bg=_rgba_hex(a.get("backgroundColor","0 0 0 1"))
    h=f"  slide #{num}  [{gname}]  backgroundColor={bg}"
    if hk: h+=f"  hotKey={hk!r}"
    if lb: h+=f"  label={lb!r}"
    if nt: h+=f"  notes={nt!r}"
    hl=_rgba_hex(a.get("highlightColor","0 0 0 0"))
    if hl!="transparent": h+=f"  highlight={hl}"
    if en!="true": h+="  enabled=false"
    out+=["┄"*62, h, "┄"*62]
    # 轉場（transitionObject）：type=-1 代表沿用全域/無，不顯示
    tr=slide_el.find('RVTransition[@rvXMLIvarName="transitionObject"]')
    if tr is not None and tr.get("transitionType","-1") not in ("-1",""):
        ta=tr.attrib
        out.append(f"{_I}▸ transition  type={ta.get('transitionType')}  duration={ta.get('transitionDuration','?')}"
                   f"  direction={ta.get('transitionDirection','?')}")
        if _T(ta,"motionEnabled"):
            out.append(f"{_II}motion       duration={ta.get('motionDuration','?')}  speed={ta.get('motionSpeed','?')}")
    # 計時器 cue
    cues=slide_el.find('array[@rvXMLIvarName="cues"]')
    for c in (cues if cues is not None else []):
        if c.tag=="RVSlideTimerCue":
            ca=c.attrib
            out.append(f"{_I}▸ timerCue    {ca.get('displayName','?')!r}  action={ca.get('actionType','?')}"
                       f"  duration={ca.get('duration','?')}  delay={ca.get('delayTime','?')}"
                       f"  loop={ca.get('loopToBeginning','?')}  enabled={ca.get('enabled','?')}")
    cue=slide_el.find('RVMediaCue[@rvXMLIvarName="backgroundMediaCue"]')
    if cue is not None:
        ca=cue.attrib
        vid=cue.find('RVVideoElement[@rvXMLIvarName="element"]')
        img=cue.find('RVImageElement[@rvXMLIvarName="element"]')
        if vid is not None:
            va=vid.attrib; ts=va.get("timeScale","90000")
            out+=[f"{_I}▸ backgroundMediaCue (video)",
                  f"{_II}displayName  {ca.get('displayName','?')}  enabled={ca.get('enabled','?')}",
                  f"{_II}source       {_video_path(va.get('source',''))}",
                  f"{_II}format       {va.get('format','?')}  naturalSize={va.get('naturalSize','?')}  frameRate={va.get('frameRate','?')}",
                  f"{_II}duration     out={_ts_sec(va.get('outPoint','0'),ts)}  in={_ts_sec(va.get('inPoint','0'),ts)}  end={_ts_sec(va.get('endPoint','0'),ts)}  audioVolume={va.get('audioVolume','?')}",
                  f"{_II}playback     behavior={va.get('playbackBehavior','?')}  rate={va.get('playRate','?')}  scaleBehavior={va.get('scaleBehavior','?')}"]
            flip=[]
            if va.get("flippedHorizontally","false")=="true": flip.append("H")
            if va.get("flippedVertically","false")=="true":   flip.append("V")
            if flip: out.append(f"{_II}flipped      {''.join(flip)}")
            out.append("")
        elif img is not None:
            ia=img.attrib
            out+=[f"{_I}▸ backgroundMediaCue (image)",
                  f"{_II}displayName  {ca.get('displayName','?')}  enabled={ca.get('enabled','?')}",
                  f"{_II}source       {_video_path(ia.get('source',''))}",
                  f"{_II}format       {ia.get('format','?')}  scaleBehavior={ia.get('scaleBehavior','?')}  scaleSize={ia.get('scaleSize','?')}",
                  ""]
    elements=slide_el.find('array[@rvXMLIvarName="displayElements"]')
    if elements is None or len(elements)==0:
        out.append(f"{_I}(no displayElements)")
    else:
        for i,el in enumerate(elements):
            if   el.tag=="RVTextElement":       out.extend(_fmt_text_layer(i,el))
            elif el.tag=="RVShapeElement":      out.extend(_fmt_shape_layer(i,el))
            elif el.tag=="RVImageElement":      out.extend(_fmt_image_layer(i,el))
            elif el.tag=="RVVideoElement":      out.extend(_fmt_video_layer(i,el))
            elif el.tag=="RVBezierPathElement": out.extend(_fmt_bezier_layer(i,el))
            else: out.extend(_fmt_generic_layer(i,el))
            out.append("")
    return "\n".join(out)

@st.cache_data(show_spinner=False)
def _build_parse_display(xml_bytes):
    """解析頁主體：回傳 [(group名, 顏色, [(slide編號, 文字)...])...]。以 bytes 為 key 快取。"""
    root=ET.fromstring(xml_bytes.decode("utf-8"))
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    result=[]; snum=0
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        gname=g.get("name","") or "(title)"
        gcolor=_rgba_hex(g.get("color","0 0 0 0"))
        slides=[]
        snode=g.find('array[@rvXMLIvarName="slides"]')
        for sl in (snode if snode is not None else []):
            snum+=1; slides.append((snum,_fmt_slide_code(snum,gname,sl)))
        result.append((gname,gcolor,slides))
    return result


# ═══════════════════════════════════════════════════════════════
# §4  RTF TRANSFORM ENGINE
# ═══════════════════════════════════════════════════════════════

def _encode_uni(text: str) -> str:
    """每字元→\\uNNNN （繁簡轉換的「就地換字」用）。明文整段重編請用 _encode_run_text。"""
    return "".join(f"\\u{ord(c)} " for c in text)

def _encode_run_text(s: str) -> str:
    """把明文編碼成 RTF 正文片段：換行→\\+LF；ASCII 字面值；{ } \\ 跳脫；
    非 ASCII →\\uNNNN （signed 16-bit，>U+FFFF 用 surrogate pair）。"""
    out=[]; has_uni=False
    for c in s:
        if c in "\r\n":
            out.append("\\\n"); continue
        if c in "{}\\":
            out.append("\\"+c); continue
        o=ord(c)
        if 0x20<=o<0x7F:
            out.append(c)
        elif o<=0xFFFF:
            out.append(f"\\u{o-65536 if o>32767 else o} "); has_uni=True
        else:
            o2=o-0x10000
            hi=0xD800+(o2>>10); lo=0xDC00+(o2&0x3FF)
            out.append(f"\\u{hi-65536} \\u{lo-65536} "); has_uni=True
    # 若用到 \uNNNN：前置 \uc0 使「跳過替代字元數=0」，避免落在 \uc1 區域時吃掉下一個字
    return ("\\uc0 "+"".join(out)) if has_uni else "".join(out)

def transform_rtf_text(rtf: str, fn: Callable[[str],str]) -> str:
    """對 RTF 內的文字（\\uNNNN 與 \\'XX hex token）逐段套字元轉換 fn（繁簡用）。
    就地替換 token，保留所在的 \\uc 上下文，不碰換行與控制字。"""
    def repl_uni(m):
        cp=int(m.group(1)); cp=cp+65536 if cp<0 else cp
        ch=chr(cp); cv=fn(ch)
        return m.group(0) if cv==ch else _encode_uni(cv)
    result=re.sub(r"\\u(-?\d+) ",repl_uni,rtf)
    def repl_hex(m):
        pairs=re.findall(r"[0-9a-fA-F]{2}",m.group(0))
        raw=bytes(int(h,16) for h in pairs)
        try: text=raw.decode("cp950")
        except: return m.group(0)
        cv=fn(text)
        if cv==text: return m.group(0)
        try:    return "".join(f"\\'{b:02x}" for b in cv.encode("cp950"))
        except: return _encode_uni(cv)
    return re.sub(r"(?:\\\'[0-9a-fA-F]{2})+",repl_hex,result)

def apply_rtf_transform_to_xml(xml_str: str, rtf_fn: Callable) -> tuple:
    """對 XML 內每個 RTFData base64 套 rtf_fn（解碼→改→編回），只動有變的節點。
    定點字串替換、不整份 ET 序列化。回傳 (new_xml, n_changed, errs)。"""
    pat=re.compile(
        r'(<NSString[^>]*rvXMLIvarName="RTFData"[^>]*>)([A-Za-z0-9+/=\r\n\s]+)(</NSString>)',
        re.DOTALL)
    n=0; errs=[]; idx=0
    def repl(m):
        nonlocal n,idx; ci=idx; idx+=1
        b64=m.group(2).replace("\n","").replace("\r","").replace(" ","")
        try:
            old=base64.b64decode(b64).decode("utf-8",errors="replace")
            new=rtf_fn(old)
            if new==old: return m.group(0)
            nonlocal n; n+=1
            return m.group(1)+base64.b64encode(new.encode("utf-8")).decode("ascii")+m.group(3)
        except Exception as e: errs.append((ci,e)); return m.group(0)
    return pat.sub(repl,xml_str), n, errs

@st.cache_resource
def _get_opencc(config: str="t2s"):
    """取得 opencc 轉換器（config: t2s 繁→簡、s2t 簡→繁）；未安裝回 None。快取。"""
    try:
        import opencc
        return opencc.OpenCC(config)
    except ImportError: return None

def tc_to_sc(text: str) -> str:
    """繁體 → 簡體（單一字串）。"""
    cc=_get_opencc("t2s")
    if cc is None: raise RuntimeError("opencc not installed.")
    return cc.convert(text)

def sc_to_tc(text: str) -> str:
    """簡體 → 繁體（單一字串）。
    opencc 會把敬語「祢」誤轉成「禰」，這裡還原回「祢」（此用途下「禰」幾乎都是誤轉）。"""
    cc=_get_opencc("s2t")
    if cc is None: raise RuntimeError("opencc not installed.")
    return cc.convert(text).replace("禰", "祢")


# ── 拼音引擎：opencc(繁→簡) + pypinyin（先轉簡體才能命中詞組字典，多音字準）──

@st.cache_resource
def _get_pinyin_engine():
    """回傳 (fn(text, tone) -> 拼音, 引擎名)；fn 逐行處理、保留換行。"""
    try:
        import opencc
        from pypinyin import pinyin, Style
        cc=opencc.OpenCC("t2s")
        def fn(text, tone=True):
            style=Style.TONE if tone else Style.NORMAL
            lines=[]
            for ln in text.split("\n"):
                syl=pinyin(cc.convert(ln), style=style)
                lines.append(" ".join(y[0] for y in syl))
            return "\n".join(lines)
        return fn, "pypinyin"
    except Exception:
        return None, None


# ═══════════════════════════════════════════════════════════════
# §5  XML PARSING  (structured data for template / text tabs)
# ═══════════════════════════════════════════════════════════════

def _parse_xml(xml_bytes: bytes):
    """把整份 XML 拆成結構化資料 (doc_meta, groups)，供模板/撰寫頁使用。
    groups[].slides[].layers[] 帶 type/pos/runs。
    不快取：回傳含 TextRun dataclass，st.cache_data 需 pickle 而無法穩定序列化
    （fragment-only 重跑時首次寫入快取會丟 UnserializableReturnValueError）；解析夠快，
    每次重新解析即可。側邊欄要的純資料另走可快取的 _doc_summary。"""
    root=ET.fromstring(xml_bytes.decode("utf-8")); doc=root.attrib
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    doc_meta={
        "title":   doc.get("CCLISongTitle",""),
        "res":     f"{doc.get('width','?')} × {doc.get('height','?')}",
        "width":   int(doc.get("width",1920)),
        "height":  int(doc.get("height",1080)),
        "author":  doc.get("CCLIAuthor",""),
        "publisher": doc.get("CCLIPublisher",""),
    }
    groups=[]; snum=0
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        slides=[]
        snode=g.find('array[@rvXMLIvarName="slides"]')
        for sl in (snode if snode is not None else []):
            snum+=1; sa=sl.attrib; layers=[]
            dnode=sl.find('array[@rvXMLIvarName="displayElements"]')
            for li,el in enumerate(dnode if dnode is not None else []):
                pn=el.find('RVRect3D[@rvXMLIvarName="position"]')
                pos=_parse_pos(pn.text) if pn is not None else dict(x=0,y=0,z=0,w=0,h=0)
                runs=[]; full=""
                if el.tag=="RVTextElement":
                    rn=el.find('NSString[@rvXMLIvarName="RTFData"]')
                    if rn is not None:
                        try:
                            rtf=base64.b64decode(rn.text.strip()).decode("utf-8",errors="replace")
                            runs=parse_rtf(rtf).runs                              # 顯示/逐段轉換用（濾空白段）
                            full=_drop_style_break_nl(parse_rtf(rtf, keep_empty=True).runs)  # 撰寫頁整層文字
                        except: pass
                layers.append(dict(idx=li, type=el.tag, pos=pos, runs=runs, full=full))
            slides.append(dict(
                num=snum, label=sa.get("label",""), hotKey=sa.get("hotKey",""),
                bg=_rgba_hex(sa.get("backgroundColor","0 0 0 1")), layers=layers))
        groups.append(dict(
            name=g.get("name","") or "(title)",
            color=_rgba_hex(g.get("color","0 0 0 0")),
            slides=slides))
    return doc_meta, groups


@st.cache_data(show_spinner=False)
def _doc_summary(xml_bytes: bytes):
    """側邊欄專用的輕量摘要：只取文件 meta + 各群組名稱/slide 數/顏色，
    不解碼任何 RTF。回傳純 dict/str，故可 @st.cache_data 快取
    （不同於 _parse_xml 含 TextRun dataclass 無法穩定 pickle）。
    每次 rerun 側邊欄都要重畫，避免在此做整份 RTF 解析的高頻浪費。"""
    root=ET.fromstring(xml_bytes.decode("utf-8")); doc=root.attrib
    meta={
        "title":     doc.get("CCLISongTitle",""),
        "res":       f"{doc.get('width','?')} × {doc.get('height','?')}",
        "author":    doc.get("CCLIAuthor",""),
        "publisher": doc.get("CCLIPublisher",""),
    }
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    groups=[]
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        snode=g.find('array[@rvXMLIvarName="slides"]')
        groups.append({
            "name":  g.get("name","") or "(title)",
            "n":     len(snode) if snode is not None else 0,
            "color": _rgba_hex(g.get("color","0 0 0 0")),
        })
    return meta, groups


# ═══════════════════════════════════════════════════════════════
# §TEMPLATES  ← 模板清單（每個 dict：name 顯示名、desc 說明、action 動作鍵）
# ═══════════════════════════════════════════════════════════════
# action 對應的處理函式見 §6/§7 的 dispatch；分類見 §7 的 _TPL_CAT。

TEMPLATES: list[dict] = [
    {"name": "清除空圖層",
     "desc": "刪掉內容為空（或還是 'Double-click to edit' 預設字）的文字圖層",
     "action": "prune_empty"},
    {"name": "整理空格",
     "desc": "刪頭尾的空白、合併文字中間的連續空白",
     "action": "tidy"},
    {"name": "清除無圖層投影片",
     "desc": "刪掉完全沒有圖層的空白投影片",
     "action": "prune_slides"},
    {"name": "繁簡轉換",
     "desc": "預設繁→簡，勾選相反",
     "action": "tc2sc"},
    {"name": "拼音標註",
     "desc": "用首圖層的拼音覆蓋第二圖層內容",
     "action": "pinyin"},
    {"name": "反轉圖層順序",
     "desc": "把圖層順序鏡像顛倒",
     "action": "reverse_layers"},
    {"name": "依換行拆分圖層",
     "desc": "把一個圖層裡的每一行都拆成獨立的圖層（後拆的依序略往下放）",
     "action": "split_lines"},
    {"name": "依圖層拆分投影片",
     "desc": "把一張投影片裡的多個文字圖層，各自分成獨立的投影片（滿版置中）",
     "action": "layers_to_slides"},
    {"name": "全部投影片加圖層",
     "desc": "每張投影片都加一個新的文字圖層（以既有文字層為範本）",
     "action": "add_layer"},
    {"name": "只保留前幾個圖層",
     "desc": "每張投影片只留前 N 個圖層（N 可輸入），後面的都刪掉",
     "action": "keep_first"},
    {"name": "刪除每張最後一個圖層",
     "desc": "把每張投影片最後一個圖層刪掉",
     "action": "del_last"},
    {"name": "合併圖層段落",
     "desc": "把同一圖層內因樣式不同而切開的段落併成單一樣式，並移除換樣式時多出來的換行",
     "action": "merge_runs"},
    {"name": "合併雙排",
     "desc": "投影片兩兩合併成上下兩行（前張在上、後張在下，逐圖層；圖層數取多），張數約減半",
     "action": "merge_rows"},
]


# ═══════════════════════════════════════════════════════════════
# §6  XML WRITE-BACK
# ═══════════════════════════════════════════════════════════════

_PLACEHOLDER_TEXTS = {"double-click to edit", "double click to edit"}

def _iter_slides(root):
    """走訪所有投影片，產生 (slide_element, displayElements_array_或_None)。"""
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        snode=g.find('array[@rvXMLIvarName="slides"]')
        for sl in (snode if snode is not None else []):
            yield sl, sl.find('array[@rvXMLIvarName="displayElements"]')

def _prune_empty_layers(xml_bytes: bytes) -> tuple:
    """刪除所有「無內文」或內文為 'Double-click to edit' 的文字圖層。
    回傳 (new_bytes, n_removed)。"""
    root, orig = _load_root(xml_bytes)
    removed=0
    for sl, elems in _iter_slides(root):
        if elems is None: continue
        for el in list(elems):
            if el.tag!="RVTextElement": continue
            rtf=_decode_rtf(_rtf_node(el))
            plain="" if rtf is None else parse_rtf(rtf).plain()
            norm=plain.strip()
            if norm=="" or norm.lower() in _PLACEHOLDER_TEXTS:
                elems.remove(el); removed+=1
    return _xml_to_bytes(root,orig), removed

def _rewrite_rtf_runs(rtf: str, real_texts: list):
    """以「每個非空 run 的新文字（已是真實文字，"" 表示刪該段）」改寫 rtf 正文，
    保留 header 與所有控制字。回傳新 rtf；段數不符回傳 None；無變動回傳原 rtf。"""
    nonempty=[r for r in parse_rtf(rtf, keep_empty=True).runs if r.text.strip()]
    if len(real_texts)!=len(nonempty): return None
    edits=[]   # (start, end, replacement) 絕對偏移，互不重疊
    for run,real in zip(nonempty, real_texts):
        if real==run.text: continue
        spans=run.text_token_spans
        if not spans: continue
        if real.strip()=="":                         # 清空 → 刪整段（含其 \+LF）
            for s,e in spans: edits.append((s,e,""))
        else:
            edits.append((spans[0][0],spans[0][1],_encode_run_text(real)))
            for s,e in spans[1:]: edits.append((s,e,""))
    if not edits: return rtf
    edits.sort()
    out=[]; cur=0
    for s,e,rep in edits:
        out.append(rtf[cur:s]); out.append(rep); cur=e
    out.append(rtf[cur:])
    return "".join(out)

def _apply_text_runs(xml_bytes: bytes, gi, si, li, run_texts: list) -> tuple:
    """改寫單一 RTFData 節點的各段明文（撰寫頁存檔用）。"""
    root,orig,el=_get_layer_el(xml_bytes,gi,si,li)
    rn=_rtf_node(el)
    rtf=_decode_rtf(rn)
    if rtf is None: return xml_bytes,"此圖層無 RTFData"
    reals=[t.replace("\\n","\n").replace("\r\n","\n").replace("\r","\n") for t in run_texts]
    nonempty=[r for r in parse_rtf(rtf, keep_empty=True).runs if r.text.strip()]
    if len(reals)!=len(nonempty):
        return xml_bytes,f"段數不符 (原{len(nonempty)}段,輸入{len(reals)}段)"
    new_rtf=_rewrite_rtf_runs(rtf, reals)
    if new_rtf is None or new_rtf==rtf: return xml_bytes,None
    _encode_rtf(rn,new_rtf)
    return _xml_to_bytes(root,orig), None


def _runs_to_lines(runs) -> list:
    """把非空 runs 依 \\n 切成行；回傳 [(line_text, owner_run_index), ...]，只保留有內容的行。
    （已知性質：同一行內樣式不變，故每行屬於單一 run。）"""
    lines=[]; buf=[]; owner=[None]
    def flush():
        if owner[0] is not None and "".join(buf).strip():
            lines.append(("".join(buf), owner[0]))
        buf.clear(); owner[0]=None
    for ri,run in enumerate(runs):
        for ch in run.text:
            if ch=="\n": flush()
            else:
                buf.append(ch)
                if owner[0] is None: owner[0]=ri
    flush()
    return lines

def _shift_pos_y(pn, dy: int):
    """把 position 節點的 y 加上 dy（其餘 x/z/w/h 不變）。"""
    nums=re.findall(r"[-\d.]+", pn.text)
    if len(nums)<5: return
    x,y,z,w,h=nums[:5]
    pn.text=f"{{{x} {int(float(y))+dy} {z} {w} {h}}}"

def _split_layer_lines(xml_bytes: bytes) -> tuple:
    """在文字圖層的換行處拆分：第 0 行留原圖層，其餘各行複製成新圖層放到後面，
    位置依序略低（每行下移 原高/行數）。回傳 (new_bytes, n_new_layers)。"""
    root, orig = _load_root(xml_bytes)
    n_new=0
    for sl, elems in _iter_slides(root):
        if elems is None: continue
        for el in list(elems):
            if el.tag!="RVTextElement": continue
            rtf=_decode_rtf(_rtf_node(el))
            if rtf is None: continue
            nonempty=[r for r in parse_rtf(rtf, keep_empty=True).runs if r.text.strip()]
            lines=_runs_to_lines(nonempty)
            if len(lines)<=1: continue
            nruns=len(nonempty)
            pn=el.find('RVRect3D[@rvXMLIvarName="position"]')
            hnums=re.findall(r"[-\d.]+", pn.text) if pn is not None else []
            h=int(float(hnums[4])) if len(hnums)>=5 else 0
            step=max(1, round(h/len(lines))) if h>0 else 60
            template=copy.deepcopy(el)
            for i,(ltext,owner) in enumerate(lines):
                new_texts=[""]*nruns; new_texts[owner]=ltext
                new_rtf=_rewrite_rtf_runs(rtf, new_texts)
                if new_rtf is None: continue
                if i==0:
                    target=el
                else:
                    target=copy.deepcopy(template)
                    target.set("UUID", str(uuid.uuid4()).upper())
                _encode_rtf(_rtf_node(target), new_rtf)
                if i>0:
                    tp=target.find('RVRect3D[@rvXMLIvarName="position"]')
                    if tp is not None: _shift_pos_y(tp, i*step)
                    elems.insert(list(elems).index(el)+i, target)
                    n_new+=1
    return _xml_to_bytes(root,orig), n_new

def _split_layers_to_slides(xml_bytes: bytes) -> tuple:
    """把一張投影片裡的多個文字圖層，各自拆成獨立投影片（每張保留背景等非文字圖層
    ＋一個文字圖層，並把該文字圖層改為全幅 1920×1080 置中）。只有一個文字圖層的
    投影片不動。回傳 (new_bytes, n_new_slides)。"""
    root, orig = _load_root(xml_bytes)
    n_new=0
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        snode=g.find('array[@rvXMLIvarName="slides"]')
        if snode is None: continue
        for sl in list(snode):
            de=sl.find('array[@rvXMLIvarName="displayElements"]')
            if de is None: continue
            m=sum(1 for e in de if e.tag=="RVTextElement")
            if m<=1: continue
            idx=list(snode).index(sl)
            for i in range(m):
                ns=copy.deepcopy(sl)
                for e in ns.iter():                       # 重給所有 UUID
                    if "UUID" in e.attrib: e.set("UUID", str(uuid.uuid4()).upper())
                nde=ns.find('array[@rvXMLIvarName="displayElements"]')
                ti=0
                for te in [e for e in nde if e.tag=="RVTextElement"]:
                    if ti==i:                             # 保留第 i 個文字層 → 全幅置中
                        pn=te.find('RVRect3D[@rvXMLIvarName="position"]')
                        if pn is not None: pn.text="{0 0 0 1920 1080}"
                        te.set("verticalAlignment","1")
                    else:
                        nde.remove(te)                    # 移除其餘文字層
                    ti+=1
                snode.insert(idx+i, ns)
            snode.remove(sl)
            n_new+=m-1
    return _xml_to_bytes(root,orig), n_new


def _set_el_text(el, new_plain: str) -> bool:
    """把單一文字元素的內文換成 new_plain（單一樣式＝原第一段的字體/字級/顏色），
    保留 RTF header 與第一段樣式控制字。改動回傳 True。"""
    rn=_rtf_node(el)
    rtf=_decode_rtf(rn)
    if rtf is None: return False
    spans=[s for r in parse_rtf(rtf, keep_empty=True).runs for s in r.text_token_spans]
    enc=_encode_run_text(new_plain)
    if spans:
        start=spans[0][0]; end=spans[-1][1]
        new_rtf=rtf[:start]+enc+rtf[end:]
    else:                                  # 原本無內文
        if not new_plain: return False     # 空層 + 空字 → 不動（避免存出多餘空格）
        he,be=_body_bounds(rtf)            # 附加在正文末（} 之前）
        sep="" if (be>he and rtf[be-1] in " \n") else " "
        new_rtf=rtf[:be]+sep+enc+rtf[be:]
    if new_rtf==rtf: return False
    _encode_rtf(rn,new_rtf)
    return True

def _set_layer_text(xml_bytes: bytes, gi, si, li, new_plain: str) -> tuple:
    """供拼音生成：把整個圖層內文換成 new_plain（單一樣式）。"""
    root,orig,el=_get_layer_el(xml_bytes,gi,si,li)
    if _rtf_node(el) is None: return xml_bytes,"此圖層無 RTFData"
    if not _set_el_text(el, new_plain): return xml_bytes,None
    return _xml_to_bytes(root,orig), None


def _reverse_layers(xml_bytes: bytes) -> tuple:
    """將每張投影片的圖層（displayElements）順序前後顛倒。回傳 (new_bytes, n_slides)。"""
    root, orig = _load_root(xml_bytes); n=0
    for sl, elems in _iter_slides(root):
        if elems is None or len(elems)<2: continue
        kids=list(elems)
        for k in kids: elems.remove(k)
        for k in reversed(kids): elems.append(k)
        n+=1
    return _xml_to_bytes(root,orig), n

def _keep_first_layers(xml_bytes: bytes, keep: int) -> tuple:
    """只保留每張前 keep 個圖層，刪掉其餘。回傳 (new_bytes, n_slides_changed)。"""
    root, orig = _load_root(xml_bytes); n=0
    for sl, elems in _iter_slides(root):
        if elems is None: continue
        kids=list(elems)
        if len(kids)<=keep: continue
        for ch in kids[keep:]: elems.remove(ch)
        n+=1
    return _xml_to_bytes(root,orig), n

def _del_last_layer(xml_bytes: bytes) -> tuple:
    """刪除每張投影片的最後一個圖層。回傳 (new_bytes, n_slides_changed)。"""
    root, orig = _load_root(xml_bytes); n=0
    for sl, elems in _iter_slides(root):
        if elems is None or len(elems)==0: continue
        elems.remove(list(elems)[-1]); n+=1
    return _xml_to_bytes(root,orig), n

def _merge_runs_plain(runs) -> str:
    """把多個 run 合併成單一樣式的明文：先移除「換樣式時多插的換行」（見
    _drop_style_break_nl——樣式邊界的換行扣一個、同樣式換行全保留），再去掉各行行首尾
    殘留的水平空白（半/全形、tab、NBSP、零寬等）。傳入完整 run 串列（含純空白 run）。
    例（樣式不同）：「紅」＋「\\n藍」→「紅藍」；同樣式「第一行\\n第二行」→「第一行\\n第二行」。"""
    out=[]
    for line in _drop_style_break_nl(runs).split("\n"):
        a=0; b=len(line)
        while a<b and _is_ws(line[a]):   a+=1      # 去行首水平空白
        while b>a and _is_ws(line[b-1]): b-=1      # 去行尾水平空白
        out.append(line[a:b])
    return "\n".join(out)

def _merge_layer_runs(xml_bytes: bytes) -> tuple:
    """把每個文字圖層內因格式不同而切開的多個 run，合併成單一樣式（取首個 run 的
    字體/字級/顏色），保留全部文字與行結構（見 _merge_runs_plain）。
    回傳 (new_bytes, n_layers_changed)。"""
    root, orig = _load_root(xml_bytes); n=0
    for sl, elems in _iter_slides(root):
        if elems is None: continue
        for el in elems:
            if el.tag!="RVTextElement": continue
            rtf=_decode_rtf(_rtf_node(el))
            if rtf is None: continue
            allruns=parse_rtf(rtf, keep_empty=True).runs
            if sum(1 for r in allruns if r.text.strip())<=1: continue  # 單段（或更少）不動
            if _set_el_text(el, _merge_runs_plain(allruns)): n+=1      # 以首段樣式重寫整層
    return _xml_to_bytes(root,orig), n

def _merge_pair_into_first(A, B):
    """把 B 投影片併入 A：逐「文字圖層」(同 index) 把 B 的文字接到 A 之下（A 上行、B 下行），
    用 A 的樣式與位置（往下擠）；只有 B 有的圖層則整層複製進 A（只有一行）。"""
    a_de=A.find('array[@rvXMLIvarName="displayElements"]')
    b_de=B.find('array[@rvXMLIvarName="displayElements"]')
    a_text=[e for e in (a_de if a_de is not None else []) if e.tag=="RVTextElement"]
    b_text=[e for e in (b_de if b_de is not None else []) if e.tag=="RVTextElement"]
    for i in range(max(len(a_text), len(b_text))):
        if i<len(a_text) and i<len(b_text):              # 兩邊都有 → A 上、B 下，用 A 的樣式
            _set_el_text(a_text[i], _el_plain(a_text[i])+"\n"+_el_plain(b_text[i]))
        elif i>=len(a_text):                             # 只有 B 有 → 整層複製進 A（單行）
            if a_de is None:
                a_de=ET.SubElement(A, "array"); a_de.set("rvXMLIvarName","displayElements")
            nb=copy.deepcopy(b_text[i]); nb.set("UUID", _new_uuid()); a_de.append(nb)
        # 只有 A 有的圖層 → 不動（維持單行）

def _merge_double_rows(xml_bytes: bytes) -> tuple:
    """把投影片依文件順序兩兩配對合併成「上下雙排」：前張在上行、後張在下行（逐圖層、
    同 index；圖層數取多），合併後用前張的樣式與位置。張數約除二，奇數最後一張保留原樣。
    回傳 (new_bytes, n_pairs)。"""
    root, orig = _load_root(xml_bytes)
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    seq=[]   # (slides_array, slide_element) 依文件順序
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        sarr=g.find('array[@rvXMLIvarName="slides"]')
        for sl in (list(sarr) if sarr is not None else []):
            seq.append((sarr, sl))
    n=0
    for k in range(0, len(seq)-1, 2):                    # (0,1)(2,3)… 落單的最後一張不處理
        (_, A), (b_arr, B) = seq[k], seq[k+1]
        _merge_pair_into_first(A, B)
        b_arr.remove(B); n+=1
    for g in list(gnode.findall("RVSlideGrouping") if gnode is not None else []):
        sarr=g.find('array[@rvXMLIvarName="slides"]')    # 移除因此變空的群組
        if sarr is not None and len(list(sarr))==0: gnode.remove(g)
    return _xml_to_bytes(root, orig), n

def _apply_tc2sc(xml_bytes: bytes, reverse: bool=False) -> tuple:
    """全文繁↔簡。reverse=False 繁→簡；True 簡→繁。回傳 (new_bytes, n_nodes, errs)。"""
    conv=sc_to_tc if reverse else tc_to_sc
    xml_str=xml_bytes.decode("utf-8")
    out,n,errs=apply_rtf_transform_to_xml(
        xml_str, lambda rtf: transform_rtf_text(rtf, conv))
    return out.encode("utf-8"), n, errs

def _dedup_uuids(xml_bytes: bytes) -> tuple:
    """確保所有元素的 UUID 不重複：保留首次出現者，重複者改為全新 UUID。
    回傳 (new_bytes, n_fixed)。"""
    root, orig = _load_root(xml_bytes)
    seen=set(); n=0
    for el in root.iter():
        u=el.get("UUID")
        if u is None: continue
        if u in seen:
            nu=str(uuid.uuid4()).upper()
            el.set("UUID", nu); seen.add(nu); n+=1
        else:
            seen.add(u)
    return _xml_to_bytes(root,orig), n

def _add_layer_all(xml_bytes: bytes, text: str="-") -> tuple:
    """為每張投影片新增一個文字圖層（預設文字 text）。以文件中既有文字圖層為範本複製，
    各自給新 UUID。回傳 (new_bytes, n_added)。"""
    root, orig = _load_root(xml_bytes)
    template=None
    for el in root.iter("RVTextElement"):
        if _rtf_node(el) is not None: template=el; break
    if template is None: return xml_bytes, 0
    template=copy.deepcopy(template)
    _set_el_text(template, text)
    n=0
    for sl, elems in _iter_slides(root):
        if elems is None:
            elems=ET.SubElement(sl, "array"); elems.set("rvXMLIvarName","displayElements")
        new_el=copy.deepcopy(template)
        new_el.set("UUID", str(uuid.uuid4()).upper())
        elems.append(new_el); n+=1
    return _xml_to_bytes(root,orig), n

def _text_slide_targets(root) -> list:
    """依文件順序回傳所有「有文字圖層」的投影片：[(displayElements, [文字圖層…])…]。"""
    out=[]
    for sl, elems in _iter_slides(root):
        if elems is None: continue
        tl=[e for e in elems if e.tag=="RVTextElement"]
        if tl: out.append((elems, tl))
    return out

def _bulk_fill_lines(xml_bytes: bytes, lines: list, layer_idx: int) -> tuple:
    """把 lines（每頁一行，依文件順序）填進每張有文字圖層的投影片：
      • layer_idx ≤ 該張文字層數 → 覆蓋第 layer_idx 個文字圖層的內文；
      • layer_idx 超過該張層數 → 在最後新增一個文字圖層（複製該張末層為範本）放這行。
    以「首字樣式」單一樣式寫入。行數需等於目標頁數。回傳 (new_bytes, n, err)。"""
    root, orig = _load_root(xml_bytes)
    targets=_text_slide_targets(root)
    if len(lines)!=len(targets):
        return xml_bytes, 0, f"行數（{len(lines)}）需等於可填頁數（{len(targets)}）"
    n=0
    for (elems, tl), line in zip(targets, lines):
        if layer_idx<=len(tl):
            if _set_el_text(tl[layer_idx-1], line): n+=1
        else:                                    # 超過現有層數 → 末端新增一層
            new_el=copy.deepcopy(tl[-1]); new_el.set("UUID", _new_uuid())
            _set_el_text(new_el, line); elems.append(new_el); n+=1
    return _xml_to_bytes(root,orig), n, None

def _wrap_title_marks(xml_bytes: bytes) -> tuple:
    """把首頁（第一張有文字圖層的投影片）第一個文字圖層的內文左右加上書名號《》。
    已是《…》則不動（不重複包）。回傳 (new_bytes, n)。"""
    root, orig = _load_root(xml_bytes)
    targets=_text_slide_targets(root)
    if not targets: return xml_bytes, 0
    el=targets[0][1][0]                          # 首頁首圖層
    plain=_el_plain(el).strip()
    if not plain or (plain.startswith("《") and plain.endswith("》")):
        return xml_bytes, 0
    if not _set_el_text(el, "《"+plain+"》"): return xml_bytes, 0
    return _xml_to_bytes(root,orig), 1

def _apply_pinyin(xml_bytes: bytes, mi_to_ni: bool=True, keep_breaks: bool=False) -> tuple:
    """每張第一層中文→拼音（不含聲調）寫入第二層。回傳 (new_bytes, n, engine)。
    mi_to_ni=True：把敬語「祢」拼音由 mi 改 ni。keep_breaks：是否跟隨中文換行斷句。"""
    pyfn, engine = _get_pinyin_engine()
    if pyfn is None: return xml_bytes, 0, None
    xb=xml_bytes; _,gs=_parse_xml(xb); cnt=0
    for gi,g in enumerate(gs):
        for si,slide in enumerate(g["slides"]):
            tl=[l for l in slide["layers"] if l["type"]=="RVTextElement"]
            if len(tl)<2: continue
            src="".join(r.text for r in tl[0]["runs"])
            if not src.strip(): continue
            if mi_to_ni: src=src.replace("祢","你").replace("袮","你")
            py=pyfn(src, False)
            if not keep_breaks: py=" ".join(py.split())   # 不斷句→併成單行
            nb,err=_set_layer_text(xb, gi, si, tl[1]["idx"], py)
            if err is None and nb is not xb: xb=nb; cnt+=1
    return xb, cnt, engine

def _pinyin_has_multiline(xml_bytes: bytes) -> bool:
    """是否有「第一層中文含換行」的投影片（拼音可能需要決定要不要斷句）。"""
    _,gs=_parse_xml(xml_bytes)
    for g in gs:
        for s in g["slides"]:
            tl=[l for l in s["layers"] if l["type"]=="RVTextElement"]
            if len(tl)<2: continue
            src="".join(r.text for r in tl[0]["runs"]).strip()
            if src and "\n" in src: return True
    return False


def _el_plain(el) -> str:
    """文字元素的純明文：解碼 RTFData → 合併各段、移除樣式切換多出來的換行
    （見 _drop_style_break_nl）。供合併雙排 / 套樣式取「使用者真正的版面」。"""
    rtf=_decode_rtf(_rtf_node(el))
    return "" if rtf is None else _drop_style_break_nl(parse_rtf(rtf, keep_empty=True).runs)

# 所有「空白」：半/全形空格、tab、各種 Unicode 空白（NBSP、thin/en/em、narrow NBSP、
# figure space…）與零寬空白等一律視為空白；但 \n/\r 留作行邊界，不算。用 regex 一網打盡。
_WS_RE = re.compile(r"[^\S\n\r]|[\u200b\u2060\ufeff]")
def _is_ws(ch): return _WS_RE.fullmatch(ch) is not None

def _drop_single_nl(chars) -> list:
    """把「單換行」（前後兩行都有內容）換成一個半形空格，使被軟換行拆開的句子接回；
    「空行」（換行相鄰至少一邊是空／全空白行）保留，維持段落分隔。
    chars 為 [(字元, run索引)…]，回傳同格式（換行字元帶其原 run 索引）。"""
    lines=[[]]; seps=[]                 # seps[k]=第 k 個換行（在 lines[k]、lines[k+1] 之間）的 run 索引
    for ch,ri in chars:
        if ch=="\n": seps.append(ri); lines.append([])
        else: lines[-1].append((ch,ri))
    def blank(line): return all(_is_ws(c) for c,_ in line)   # 空或全空白＝空行
    out=[]
    for k in range(len(lines)):
        out.extend(lines[k])
        if k<len(seps):
            if blank(lines[k]) or blank(lines[k+1]):
                out.append(("\n", seps[k]))      # 段落分隔 → 保留換行
            else:
                out.append((" ", seps[k]))       # 單換行 → 換成一個空格（後續會併掉多餘空白）
    return out

def _tidy_runs(runs, drop_nl: bool=False) -> list:
    """整理空格：
      ① 每行頭尾的空白清乾淨（含換行旁的空格）；
      ② 字中間一連串空白（半/全形/tab/nbsp 等）併成一個半形空格；
      ③ 換行（行結構）保留、空行保留。
    drop_nl=True：先把「單換行」換成空格（空行保留），再做上述整理。"""
    chars=[(ch,ri) for ri,run in enumerate(runs) for ch in run.text]
    if drop_nl: chars=_drop_single_nl(chars)
    # ① 連續空白（非換行）併成單一半形空格
    out=[]; i=0; n=len(chars)
    while i<n:
        ch,ri=chars[i]
        if _is_ws(ch):
            out.append((" ",ri))
            while i<n and _is_ws(chars[i][0]): i+=1
        else:
            out.append((ch,ri)); i+=1
    # ② 去掉每行頭尾的空格：行邊界＝換行，整段最前/最後也視為行首/行尾
    m=len(out)
    buf=[""]*len(runs)
    for k,(ch,ri) in enumerate(out):
        if ch==" ":
            prev = out[k-1][0] if k>0   else "\n"
            nxt  = out[k+1][0] if k<m-1 else "\n"
            if prev=="\n" or nxt=="\n": continue   # 行首／行尾的空格 → 丟掉
        buf[ri]+=ch
    return buf

def _apply_runs_fn(xml_bytes: bytes, fn) -> tuple:
    """對每個文字圖層套用 fn(runs)->新各段文字，保留各段樣式。回傳 (new_bytes, n_layers)。"""
    xb=xml_bytes; _,gs=_parse_xml(xb); cnt=0
    for gi,g in enumerate(gs):
        for si,slide in enumerate(g["slides"]):
            for layer in slide["layers"]:
                if layer["type"]!="RVTextElement" or not layer["runs"]: continue
                new=fn(layer["runs"])
                if all(nt==r.text for nt,r in zip(new, layer["runs"])): continue
                nb,err=_apply_text_runs(xb, gi, si, layer["idx"], new)
                if err is None and nb is not xb: xb=nb; cnt+=1
    return xb, cnt

def _apply_tidy(xml_bytes: bytes, drop_nl: bool=False) -> tuple:
    """全檔套用「整理空白」（行為見 _tidy_runs）。drop_nl=True 連單換行一起刪。
    回傳 (new_bytes, n_layers)。"""
    return _apply_runs_fn(xml_bytes, lambda runs: _tidy_runs(runs, drop_nl))

def _delete_empty_slides(xml_bytes: bytes, keep_bg: bool=True) -> tuple:
    """刪除沒有任何圖層（displayElements 為空或不存在）的投影片。
    keep_bg=True 時，保留「只有背景影片/圖片」的投影片。回傳 (new_bytes, n)。"""
    root, orig = _load_root(xml_bytes); n=0
    gnode=root.find('.//array[@rvXMLIvarName="groups"]')
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        snode=g.find('array[@rvXMLIvarName="slides"]')
        if snode is None: continue
        for sl in list(snode):
            elems=sl.find('array[@rvXMLIvarName="displayElements"]')
            if elems is not None and len(elems)>0: continue
            if keep_bg:
                cue=sl.find('RVMediaCue[@rvXMLIvarName="backgroundMediaCue"]')
                if cue is not None and cue.find('*[@rvXMLIvarName="element"]') is not None:
                    continue   # 有背景元素 → 保留
            snode.remove(sl); n+=1
    return _xml_to_bytes(root,orig), n


# ── 創造：從純文字產生新的 .pro6 ────────────────────────────────
def _new_uuid():
    return str(uuid.uuid4()).upper()

def _rtf_doc(body, font="Helvetica", fs=160):
    """組一份單色（白）置中 RTF 文件；body 為 _encode_run_text 的輸出。"""
    return ("{\\rtf1\\ansi\\ansicpg950\\cocoartf2580\n"
            "\\cocoatextscaling0\\cocoaplatform0{\\fonttbl\\f0\\fnil\\fcharset0 "+font+";}\n"
            "{\\colortbl;\\red255\\green255\\blue255;}\n"
            "{\\*\\expandedcolortbl;;}\n"
            "\\pard\\tx560\\pardirnatural\\qc\\partightenfactor0\n"
            "\\f0\\fs"+str(fs)+" \\cf1 "+body+"}")

def _split_text_blocks(text):
    """依空行（可含空白）切段，去掉前後空白段。回傳段落字串清單。"""
    blocks=re.split(r"\n[^\S\n]*\n+", text.strip("\n"))
    return [b.strip("\n") for b in blocks if b.strip()]

def _split_lines_ne(text):
    """切成「非空行」清單（去前後空白），供雙排逐行配對用。"""
    return [l.strip() for l in text.split("\n") if l.strip()]

# 創造用固定樣式：[PingFangTC-Medium|65.0pt|#FFFFFF]，位置全幅置中
_CREATE_FONT = "PingFangTC-Medium"
_CREATE_FS   = 130                       # 65.0pt（fs = pt × 2）

def _text_element(plain, x, y, w, h):
    """完整的 RVTextElement（補齊所有 ProPresenter 必要屬性與 shadow/stroke 子元素，
    否則 ProPresenter 會 deserialize 失敗 / NSPathStore nil）。
    樣式 [PingFangTC-Medium|65.0pt|#FFFFFF]、水平＋垂直置中。"""
    b64=base64.b64encode(_rtf_doc(_encode_run_text(plain),_CREATE_FONT,_CREATE_FS).encode("utf-8")).decode("ascii")
    return (f'<RVTextElement UUID="{_new_uuid()}" additionalLineFillHeight="0.000000" '
            'adjustsHeightToFit="false" bezelRadius="0.000000" displayDelay="0.000000" '
            'displayName="TextElement" drawLineBackground="false" drawingFill="false" '
            'drawingShadow="false" drawingStroke="false" fillColor="0 0 0 0" '
            'fromTemplate="false" lineBackgroundType="0" lineFillVerticalOffset="0.000000" '
            'locked="false" opacity="1.000000" persistent="false" revealType="0" '
            'rotation="0.000000" source="" textSourceRemoveLineReturnsOption="false" '
            'typeID="0" useAllCaps="false" verticalAlignment="1">'   # 1=垂直置中
            f'<RVRect3D rvXMLIvarName="position">{{{x} {y} 0 {w} {h}}}</RVRect3D>'
            '<shadow rvXMLIvarName="shadow">0.000000|0 0 0 0|{4, -4}</shadow>'
            '<dictionary rvXMLIvarName="stroke">'
            '<NSColor rvXMLDictionaryKey="RVShapeElementStrokeColorKey">0 0 0 0</NSColor>'
            '<NSNumber hint="integer" rvXMLDictionaryKey="RVShapeElementStrokeWidthKey">0</NSNumber>'
            '</dictionary>'
            f'<NSString rvXMLIvarName="RTFData">{b64}</NSString>'
            '</RVTextElement>')

def _slide_element(elements):
    return (f'<RVDisplaySlide UUID="{_new_uuid()}" backgroundColor="0 0 0 1" '
            'chordChartPath="" drawingBackgroundColor="false" enabled="true" '
            'highlightColor="0 0 0 0" hotKey="" label="" notes="" socialItemCount="1">'
            '<array rvXMLIvarName="cues"></array>'
            f'<array rvXMLIvarName="displayElements">{"".join(elements)}</array>'
            '</RVDisplaySlide>')

def _doc_wrapper(slides):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<RVPresentationDocument CCLIArtistCredits="" CCLIAuthor="" CCLICopyrightYear="" '
            'CCLIDisplay="" CCLIPublisher="" CCLISongNumber="" CCLISongTitle="" '
            'backgroundColor="0 0 0 1" buildNumber="100991749" category="Lyrics" '
            'chordChartPath="" docType="0" drawingBackgroundColor="false" height="1080" '
            'lastDateUsed="" notes="" os="2" resourcesDirectory="" selectedArrangementID="" '
            f'usedCount="0" uuid="{_new_uuid()}" versionNumber="600" width="1920">'
            '<RVTimeline duration="0.000000" loop="false" playBackRate="0.000000" '
            'rvXMLIvarName="timeline" selectedMediaTrackIndex="0" timeOffset="0.000000">'
            '<array rvXMLIvarName="timeCues"></array><array rvXMLIvarName="mediaTracks"></array>'
            '</RVTimeline>'
            '<array rvXMLIvarName="groups">'
            f'<RVSlideGrouping name="" color="0 0 0 0" uuid="{_new_uuid()}">'
            f'<array rvXMLIvarName="slides">{"".join(slides)}</array>'
            '</RVSlideGrouping>'
            '</array>'
            '<array rvXMLIvarName="arrangements"></array>'
            '</RVPresentationDocument>').encode("utf-8")

def _split_pages(text, page_by):
    """換頁：'換行'＝每一行一頁；'空行'＝空行分段一頁。回傳每頁的文字。"""
    if page_by == "換行":
        return [s for s in (ln.strip() for ln in text.split("\n")) if s]
    return _split_text_blocks(text)

def _split_layers(page, layer_by):
    """同一頁內換圖層：'換行'＝每行一個圖層；'空行'＝空行分段一個圖層（段內換行保留）。"""
    if layer_by == "換行":
        return [s for s in (ln.strip() for ln in page.split("\n")) if s]
    return _split_text_blocks(page) or [page]

def _build_pro6_structured(text, page_by="空行", layer_by="換行"):
    """可組態：先依 page_by 分頁，每頁再依 layer_by 分圖層；位置 1920×1080，
    多圖層在垂直方向均分成帶、各自置中。回傳 .pro6 bytes。"""
    slides=[]
    for page in _split_pages(text, page_by):
        lts=_split_layers(page, layer_by)
        if not lts: continue
        m=len(lts); h=1080//m
        els=[_text_element(lt, 0, i*h, 1920, h) for i,lt in enumerate(lts)]
        slides.append(_slide_element(els))
    return _doc_wrapper(slides)

def _name_from_text(text):
    """取首個非空行作為預設檔名（去掉檔名不合法字元、截斷 40 字）。"""
    for ln in text.split("\n"):
        s=re.sub(r'[\\/:*?"<>|\t]', "", ln).strip()
        if s: return s[:40]
    return "未命名"

def _build_pro6_bilingual(top_text, bot_text):
    """雙排：左右逐行配對，每張 slide ＝上排(左欄第i行)＋下排(右欄第i行)兩個圖層
    （各佔上下半幅、置中）。以兩欄非空行數的較小者為準。回傳 .pro6 bytes。"""
    slides=[_slide_element([_text_element(t,0,0,1920,540),
                            _text_element(b,0,540,1920,540)])
            for t,b in zip(_split_lines_ne(top_text), _split_lines_ne(bot_text))]
    return _doc_wrapper(slides)


# ── 樣式：從參考檔（styles.json）套用排版到每一張 ───────────────
def _load_styles():
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles.json")
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

_STYLES = _load_styles()

def _apply_style(xml_bytes, style_name):
    """把某樣式（參考檔的一張）的排版套到每一張：逐個文字圖層換成該樣式的元素範本，
    再把原文字注入回去——保留文字，換掉字體/字級/顏色/位置/對齊/陰影。
    回傳 (new_bytes, n_layers)。樣式層數 < 該張文字層數時，多出來的層維持原樣。"""
    layers=_STYLES.get(style_name)
    if not layers: return xml_bytes, 0
    root, orig = _load_root(xml_bytes)
    n=0
    for sl, elems in _iter_slides(root):
        if elems is None: continue
        ti=[i for i,e in enumerate(elems) if e.tag=="RVTextElement"]
        for k,ei in enumerate(ti):
            if k>=len(layers): break
            plain=_el_plain(elems[ei])           # 原文字（純明文，含換行）
            tmpl=ET.fromstring(layers[k])        # 樣式元素（內文已清空）
            tmpl.set("UUID", _new_uuid())
            _set_el_text(tmpl, plain)            # 注入原文字
            elems[ei]=tmpl
            n+=1
    return _xml_to_bytes(root,orig), n


# ── 撰寫頁：段落類型（group）與熱鍵（hotKey）────────────────────
# 段落類型＝名稱 ↔ 顏色綁定。色碼之後可調整；要加類型在這裡加一項即可。
_GROUP_PRESETS = [
    ("標題",       "#8E44AD"),   # 標題・紫（套用時首頁首圖層自動加書名號《》）
    ("Verse",      "#3B6FD4"),   # 主歌・藍
    ("Chorus",     "#D0021B"),   # 副歌・紅
    ("Pre-Chorus", "#F5C518"),   # 黃
    ("Bridge",     "#FFFFFF"),   # 白
    ("Verse 2",    "#2E8B57"),   # 綠
]
_GROUP_COLOR = dict(_GROUP_PRESETS)
# 撰寫頁 UI 用的彩色圓點（對應綁定色，標在類型名稱前面）
_GROUP_EMOJI = {"標題":"🟣", "Verse":"🔵", "Chorus":"🔴", "Pre-Chorus":"🟡",
                "Bridge":"⚪", "Verse 2":"🟢"}

def _hex_rgba(hx: str, a: float = 1.0) -> str:
    """#RRGGBB → ProPresenter 顏色字串「r g b a」(各 0~1，6 位小數)。"""
    hx = hx.lstrip("#")
    r, g, b = (int(hx[i:i+2], 16) / 255 for i in (0, 2, 4))
    return f"{r:.6f} {g:.6f} {b:.6f} {a:.6f}"

def _iter_slides_global(root):
    """依文件順序產生 (group_element, group_index, slide_index_in_group, slide_element, global_num)。
    global_num 從 1 起，與 _parse_xml 的 slide['num'] 一致。"""
    gnode = root.find('.//array[@rvXMLIvarName="groups"]')
    n = 0
    for gi, g in enumerate(gnode.findall("RVSlideGrouping") if gnode is not None else []):
        sarr = g.find('array[@rvXMLIvarName="slides"]')
        for si, s in enumerate(sarr if sarr is not None else []):
            n += 1
            yield g, gi, si, s, n

def _merge_adjacent_groups(gnode):
    """合併相鄰且 name+color 完全相同的群組（把後者的 slides 併入前者後刪除後者）。"""
    prev = None
    for g in list(gnode.findall("RVSlideGrouping")):
        if (prev is not None and g.get("name") == prev.get("name")
                and g.get("color") == prev.get("color")):
            ps = prev.find('array[@rvXMLIvarName="slides"]')
            gs = g.find('array[@rvXMLIvarName="slides"]')
            for s in list(gs if gs is not None else []): ps.append(s)
            gnode.remove(g)
        else:
            prev = g

def _set_group_fill(xml_bytes: bytes, num: int, name: str, color_hex: str) -> tuple:
    """設定第 num 張的段落類型：把「該張往後、同一組的連續範圍」整段歸到新類型
    （遇到下一個不同群組就停＝原群組的尾端）。第一張即整組改名換色；否則把該組從
    這張切開、後段移進新群組。最後合併相鄰同類型。回傳 (new_bytes, err)。"""
    root, orig = _load_root(xml_bytes)
    target = next((t for t in _iter_slides_global(root) if t[4] == num), None)
    if target is None: return xml_bytes, "找不到投影片"
    grouping, _gi, si, _s, _ = target
    color = _hex_rgba(color_hex)
    gnode = root.find('.//array[@rvXMLIvarName="groups"]')
    sarr = grouping.find('array[@rvXMLIvarName="slides"]')
    slides = list(sarr if sarr is not None else [])
    if si == 0:                                  # 整組就是這個範圍 → 直接改名換色
        grouping.set("name", name); grouping.set("color", color)
    else:                                        # 從第 si 張切開，後段移進新群組
        moved = slides[si:]
        for s in moved: sarr.remove(s)
        newg = ET.Element("RVSlideGrouping")
        newg.set("name", name); newg.set("color", color); newg.set("uuid", _new_uuid())
        narr = ET.SubElement(newg, "array"); narr.set("rvXMLIvarName", "slides")
        for s in moved: narr.append(s)
        gnode.insert(list(gnode).index(grouping) + 1, newg)
    _merge_adjacent_groups(gnode)
    return _xml_to_bytes(root, orig), None

def _hotkey_owner(xml_bytes: bytes, key: str, exclude: int = -1):
    """回傳目前使用熱鍵 key 的投影片 global_num（排除 exclude）；無則 None。"""
    if not key: return None
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    for _g, _gi, _si, s, n in _iter_slides_global(root):
        if n != exclude and s.get("hotKey", "") == key:
            return n
    return None

def _set_slide_hotkey(xml_bytes: bytes, num: int, key: str) -> tuple:
    """設定第 num 張的熱鍵為 key（空字串＝清除）。為保唯一，會先把同一個鍵從其他
    投影片清掉（覆蓋／替代舊的）。回傳 (new_bytes, err)。"""
    root, orig = _load_root(xml_bytes)
    target = None
    for _g, _gi, _si, s, n in _iter_slides_global(root):
        if key and n != num and s.get("hotKey", "") == key:
            s.set("hotKey", "")                  # 移除舊持有者（唯一性）
        if n == num: target = s
    if target is None: return xml_bytes, "找不到投影片"
    target.set("hotKey", key)
    return _xml_to_bytes(root, orig), None

def _normalize_preset_groups(xml_bytes: bytes) -> bytes:
    """匯入時用：群組名稱若已是預設類型（Verse/Chorus…），把它的顏色設成綁定色，
    讓匯入檔的群組直接對齊預設狀態。沒有相符的群組則原樣回傳（byte 不變）。"""
    root, orig = _load_root(xml_bytes)
    gnode = root.find('.//array[@rvXMLIvarName="groups"]')
    changed = False
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        hexc = _GROUP_COLOR.get(g.get("name", ""))
        if hexc is None: continue
        want = _hex_rgba(hexc)
        if g.get("color") != want:
            g.set("color", want); changed = True
    return _xml_to_bytes(root, orig) if changed else xml_bytes

def _delete_slide_by_num(xml_bytes: bytes, num: int) -> tuple:
    """刪除第 num 張投影片；若其群組因此變空，連同空群組一起移除。
    回傳 (new_bytes, err)。"""
    root, orig = _load_root(xml_bytes)
    for g, _gi, _si, s, n in _iter_slides_global(root):
        if n == num:
            sarr = g.find('array[@rvXMLIvarName="slides"]')
            sarr.remove(s)
            if len(list(sarr)) == 0:                 # 群組空了 → 一併移除
                gnode = root.find('.//array[@rvXMLIvarName="groups"]')
                gnode.remove(g)
            return _xml_to_bytes(root, orig), None
    return xml_bytes, "找不到投影片"


# ═══════════════════════════════════════════════════════════════
# §7  UI
# ═══════════════════════════════════════════════════════════════

# 分頁圖示(favicon)：工程帽。page_icon 接受字串路徑，錨定腳本目錄避免雲端 CWD 差異
# ⋮ 選單「關於此工具」內容
_ABOUT_TEXT = """### ProParse · 投影片解析

ProPresenter 6（.pro6）投影片的批次檢視與編輯工具，特別適合雙語歌詞。

- **解析**：唯讀檢視整份檔的結構與明文。
- **模板**：對全部投影片套用一個批次動作（整理空格、繁簡、拼音、合併雙排…）。
- **撰寫**：逐圖層編輯文字，並可設段落類型(group)、熱鍵、刪投影片。
- **創造**：從純文字產生新的 .pro6。

編輯後從左側欄匯出 .pro6。
"""

st.set_page_config(
    page_title="ProParse · 投影片解析",
    page_icon=os.path.join(os.path.dirname(os.path.abspath(__file__)), "hard-hat.png"),
    layout="wide",
    menu_items={"About": _ABOUT_TEXT},
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+TC:wght@400;700&display=swap');
html,[class*="css"]{font-family:'Noto Sans TC',sans-serif;}
.stCodeBlock,code,pre{font-family:'IBM Plex Mono',monospace!important;font-size:0.78rem!important;}
.stTabs [data-baseweb="tab"]{font-weight:700;font-size:0.9rem;padding:0.5rem 1.5rem;}
/* 撰寫頁 slide 標頭：緊湊化 + 熱鍵正方形/大寫 */
/* 熱鍵：正方形、不被橫向容器拉伸 */
[class*="st-key-hk_"]{width:2.6rem!important;flex:0 0 auto!important;}
[class*="st-key-hk_"] input{width:2.6rem!important;height:2.6rem!important;text-align:center;
  text-transform:uppercase;font-weight:700;font-size:1rem;padding:0;}
/* 段落 popover：用內容寬度（不被壓窄/換行） */
[class*="st-key-grppop_"]{flex:0 0 auto!important;}
[class*="st-key-grppop_"]>button{white-space:nowrap;}
[class*="st-key-grpbtn_"] button{padding:.1rem .5rem;min-height:0;}
/* 刪除鈕：與熱鍵同尺寸的正方形 */
[class*="st-key-delbtn_"]{flex:0 0 auto!important;}
[class*="st-key-delbtn_"] button{width:2.6rem!important;height:2.6rem!important;padding:0;min-height:0;}
</style>
""", unsafe_allow_html=True)

def _push_undo():
    """變更前把目前狀態存入 undo 堆疊（上限 50 步）。"""
    us=st.session_state.setdefault("undo_stack", [])
    us.append(st.session_state["xml_content"])
    if len(us)>50: del us[:len(us)-50]

def _soft_reset():
    """卡住時的自救：清全域快取 + 所有暫態旗標，把檔案還原到剛載入的狀態。"""
    try: st.cache_data.clear()
    except Exception: pass
    ss=st.session_state
    for k in [k for k in ss if k.startswith(("txt_","empty_","grp_","hk_","_"))]:
        ss.pop(k, None)                          # 清掉輸入框快取與所有 _xxx 暫態旗標
    if ss.get("xml_original") is not None:
        ss["xml_content"]=ss["xml_original"]; ss["undo_stack"]=[]; ss["history"]=[]
    st.rerun()

def _commit_change(tpl_name, nb, cnt, msg):
    """套用變更：存檔、記錄歷史、清掉撰寫頁快取、設定 toast，然後重跑。"""
    try:                                         # 防呆：只存「能解析的合法 XML」，壞檔不入狀態
        ET.fromstring(nb.decode("utf-8"))
    except Exception:
        st.session_state["_tpl_msg"]=f"⚠️「{tpl_name}」結果異常，已略過（檔案未變動）"
        st.rerun(); return                        # return 為保險（rerun 通常已中斷）
    _push_undo()
    st.session_state["xml_content"]=nb
    st.session_state["history"].append(f"{tpl_name}({cnt})")
    for kk in [kk for kk in st.session_state
               if kk.startswith(("txt_","empty_","grp_","hk_"))]:
        st.session_state.pop(kk, None)
    st.session_state["_tpl_msg"]=msg          # 下一輪以 st.toast 飄出
    st.rerun()

@st.dialog("拼音斷句")
def _pinyin_dialog(ti, tpl_name):
    """中文含換行時，跳出視窗詢問拼音是否跟著斷句。"""
    st.warning("偵測到中文含換行。拼音要不要跟著斷句？")
    pc=st.radio("拼音換行：", ["不斷句（單行）","斷句（跟隨中文換行）"],
                key=f"pyc_{ti}", horizontal=True)
    p1,p2=st.columns(2)
    if p1.button("確認套用", key=f"pyok_{ti}", use_container_width=True, type="primary"):
        nb,n,eng=_apply_pinyin(st.session_state["xml_content"],
                               st.session_state.get(f"mi2ni_{ti}", True),
                               keep_breaks=(pc=="斷句（跟隨中文換行）"))
        st.session_state.pop("_py_ask", None)
        if eng is None: st.error("拼音引擎不可用：請 pip install pypinyin。")
        else: _commit_change(tpl_name, nb, n, f"已把 {n} 張的拼音寫入第二層（引擎：{eng}）")
    if p2.button("取消", key=f"pycancel_{ti}", use_container_width=True):
        st.session_state.pop("_py_ask", None); st.rerun()

def _load_new_doc(raw, name):
    """把一份檔案（上傳／創造／覆蓋）載入為目前編輯對象，重置歷史。"""
    ss=st.session_state
    # _fk 用「原始」長度當識別，必須在正規化前算——否則正規化改了 byte 數，
    # 會與上傳端的 uploaded.size 對不上，導致每次 rerun 都重載原檔、洗掉所有編輯。
    ss["_fk"]=(name, len(raw))
    # 匯入時：群組名稱若已是預設類型，把顏色對齊綁定狀態
    try: raw=_normalize_preset_groups(raw)
    except Exception: pass
    ss["xml_original"]=raw; ss["xml_content"]=raw
    ss["filename"]=name; ss["history"]=[]; ss["undo_stack"]=[]
    ss["export_name"]=name.rsplit(".",1)[0]
    # 清掉舊檔的撰寫頁輸入框快取，否則新檔會沿用同 key 顯示成舊內容
    for k in [k for k in ss if k.startswith(("txt_","empty_","grp_","hk_"))]:
        ss.pop(k, None)

def _request_new(xml, name):
    """要產生新檔：已有檔案在編輯→先彈窗確認覆蓋；否則直接（延到下一輪最前面）載入。"""
    if "xml_content" in st.session_state:
        st.session_state["_overwrite_new"]=(xml, name)   # 觸發覆蓋確認彈窗
    else:
        st.session_state["_pending_new"]=(xml, name)
    st.rerun()

@st.dialog("覆蓋目前的檔案？")
def _overwrite_dialog():
    st.warning("目前已有檔案在編輯，產生新檔會**取代**它（記得先匯出舊檔）。確定覆蓋？")
    c1,c2=st.columns(2)
    if c1.button("確認覆蓋", key="ow_yes", type="primary", use_container_width=True):
        st.session_state["_pending_new"]=st.session_state.pop("_overwrite_new")
        st.rerun()
    if c2.button("取消", key="ow_no", use_container_width=True):
        st.session_state.pop("_overwrite_new", None); st.rerun()

@st.dialog("刪除投影片")
def _del_slide_dialog(num):
    """撰寫頁刪除某張的確認框。"""
    st.warning(f"確定要刪除 **Slide {num}**？刪除後可用左側「還原」復原。")
    c1,c2=st.columns(2)
    if c1.button("確認刪除", key=f"delok_{num}", type="primary", use_container_width=True):
        nb,err=_delete_slide_by_num(st.session_state["xml_content"], num)
        st.session_state.pop("_del_ask", None)
        if err: st.session_state["_text_err"]=err
        else:
            _push_undo(); st.session_state["xml_content"]=nb
            st.session_state["history"].append(f"刪除S{num}")
            for k in [k for k in st.session_state if k.startswith(("txt_","empty_","hk_"))]:
                st.session_state.pop(k, None)
        st.rerun()
    if c2.button("取消", key=f"delcancel_{num}", use_container_width=True):
        st.session_state.pop("_del_ask", None); st.rerun()

def _create_ui():
    """創造：單欄＝可選換頁／換圖層依據；按右側「＋」開右欄做雙排（雙語）逐行配對。"""
    if "_overwrite_new" in st.session_state:       # 已有檔案時的覆蓋確認
        _overwrite_dialog()
    st.caption("單欄＝依下方「換頁／換圖層依據」分割（預設空行換頁、換行換圖層）。"
               "按文字框右側「＋」開右欄＝雙排：左右各一行配成一張（上排左欄、下排右欄）。")
    up=st.file_uploader("上傳 .txt（填入左欄）", type=["txt"], key="create_txt")
    dual=st.session_state.get("create_dual", False)
    page_by=layer_by=None

    if not dual:
        col_t, col_b = st.columns([12,1])
        txt=col_t.text_area("或在此貼上文字", key="create_text", height=240,
                            placeholder="第一張投影片\n（段內可多行）\n\n第二張投影片\n\n第三張…")
        col_b.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if col_b.button("＋", key="create_add", help="新增右欄，做雙排（雙語）逐行配對"):
            st.session_state["create_dual"]=True; st.rerun()
        d1,d2=st.columns(2)
        page_by =d1.selectbox("換頁依據", ["空行","換行"], key="create_page_by")
        layer_by=d2.selectbox("換圖層依據", ["換行","空行"], key="create_layer_by")
        left_src=(up.read().decode("utf-8","replace") if up is not None else txt) or ""
        right_src=None
    else:
        col_l, col_r = st.columns(2)
        txt =col_l.text_area("左欄（上排）", key="create_text",  height=240,
                             placeholder="第一行\n第二行\n第三行…")
        txt2=col_r.text_area("右欄（下排）", key="create_text2", height=240,
                             placeholder="line 1\nline 2\nline 3…")
        if col_r.button("移除右欄（改回單欄）", key="create_del"):
            st.session_state["create_dual"]=False; st.rerun()
        left_src =(up.read().decode("utf-8","replace") if up is not None else txt) or ""
        right_src=txt2 or ""

    st.caption("樣式固定：PingFangTC-Medium · 65pt · 白 · 1920×1080 置中。")
    _name=_name_from_text(left_src)+".pro6"      # 預設檔名＝首行內容

    if right_src is None:                       # 單欄：依 page_by/layer_by 分割
        n=len(_split_pages(left_src, page_by or "空行")) if left_src.strip() else 0
        st.caption(f"預估：{n} 張投影片（{page_by or '空行'}換頁、{layer_by or '換行'}換圖層）")
        if st.button("產生並開始編輯", type="primary", use_container_width=True, disabled=n==0):
            _request_new(_build_pro6_structured(left_src, page_by or "空行",
                                                layer_by or "換行"), _name)
    else:                                       # 雙排：逐行配對
        nl=len(_split_lines_ne(left_src)); nr=len(_split_lines_ne(right_src))
        equal=nl>0 and nl==nr
        st.caption(f"左欄 **{nl}** 行　右欄 **{nr}** 行　"
                   +("行數相等，可雙排創造" if equal else "兩欄行數需相等才能雙排創造"))
        if st.button("雙排創造（上排左欄、下排右欄，逐行配對）", type="primary",
                     use_container_width=True, disabled=not equal):
            _request_new(_build_pro6_bilingual(left_src,right_src), _name)

# 創造分頁按「產生」後，延到此處（任何 widget 實例化之前）才載入新檔
if "_pending_new" in st.session_state:
    _raw,_name=st.session_state.pop("_pending_new")
    _load_new_doc(_raw,_name)

# ── Upload / 創造 ───────────────────────────────────────────────
st.title("ProParse · 投影片解析")
uploaded = st.file_uploader("上傳 .xml 或 .pro6", type=["xml","pro6"])
if uploaded is not None:
    fk=(uploaded.name, uploaded.size)
    if st.session_state.get("_fk")!=fk:
        _load_new_doc(uploaded.read(), uploaded.name)
if "xml_content" not in st.session_state:
    st.divider()
    st.subheader("創造（從文字產生新檔）")
    _create_ui()
    st.stop()

xml_bytes=st.session_state["xml_content"]
try:                                             # 保險絲：檔案若解析不了就不要整頁崩，給自救鈕
    doc_meta, _summary_groups=_doc_summary(xml_bytes)
except Exception:
    st.error("⚠️ 目前檔案無法解析，狀態可能異常。")
    if st.button("🔄 重設（清快取與狀態、還原到剛載入的檔）", type="primary"):
        _soft_reset()
    st.stop()

# ── Sidebar ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**{doc_meta['title'] or '(無標題)'}**")
    # 文件資訊用小灰字（caption）一行一行列，群組以 • 列點。
    _info=[doc_meta["res"]]
    if doc_meta["author"]:    _info.append(f"作者：{doc_meta['author']}")
    if doc_meta["publisher"]: _info.append(f"出版：{doc_meta['publisher']}")
    for g in _summary_groups:
        _info.append(f"• {g['name']}　{g['n']} slides　color={g['color']}")
    st.caption("<br>".join(_info), unsafe_allow_html=True)
    st.divider()
    if st.session_state.get("history"):
        st.caption("→ ".join(st.session_state["history"][-6:]))
    _undo=st.session_state.get("undo_stack", [])
    if st.button("還原（復原上一步）", use_container_width=True,
                 disabled=not _undo):
        st.session_state["xml_content"]=_undo.pop()
        if st.session_state.get("history"): st.session_state["history"].pop()
        for k in [k for k in st.session_state if k.startswith(("txt_","empty_","grp_","hk_"))]:
            st.session_state.pop(k, None)
        st.rerun()
    st.divider()
    default_name=st.session_state["filename"].rsplit(".",1)[0]
    out_name=st.text_input("匯出檔名", key="export_name").strip() or default_name
    # 匯出時自動確保 UUID 不重複
    export_bytes, _n_uuid = _dedup_uuids(xml_bytes)
    if _n_uuid: st.caption(f"匯出將修復 {_n_uuid} 個重複 UUID")
    st.download_button(f"匯出 {out_name}.pro6", export_bytes, out_name+".pro6",
                       "application/xml", use_container_width=True)
    st.divider()
    # 卡住自救：清全域快取＋暫態旗標、還原到剛載入的檔（不丟掉已上傳的檔）
    if st.button("🔄 卡住了？重設", use_container_width=True,
                 help="清除快取與暫存狀態、把檔案還原到剛載入時。操作後若怪怪的、重新整理也沒用時點這個。"):
        _soft_reset()

# ── 操作後的飄出提示（toast 會被 rerun 清掉，故存到 session_state 於下一輪顯示）──
if st.session_state.get("_tpl_msg"):
    st.toast(st.session_state.pop("_tpl_msg"))

# ── Tabs ───────────────────────────────────────────────────────
tab_parse, tab_tpl, tab_text, tab_new = st.tabs(["解析", "模板", "撰寫", "創造"])


# ─── TAB 1: 解析 ──────────────────────────────────────────────
with tab_parse:
    st.caption("唯讀檢視整份檔。文件資訊見左側欄。")
    for gname,gcolor,slides in _build_parse_display(xml_bytes):
        c=gcolor
        dot=(f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
             f'background:{c};margin-right:5px;vertical-align:middle"></span>'
             if c!="transparent" else "")
        st.markdown(f'<p style="font-size:.75rem;font-weight:700;letter-spacing:.08em;'
                    f'text-transform:uppercase;color:#555;margin:.6rem 0 .2rem">'
                    f'{dot}{gname}</p>', unsafe_allow_html=True)
        for _,text in slides:
            st.code(text, language="")


# ─── TAB 2: 模板 ──────────────────────────────────────────────
with tab_tpl:
    if _STYLES:
        with st.container(border=True):
            st.markdown("**樣式**", help=(
                "套用參考排版（字體／字級／顏色／位置／陰影）到每一張，文字保留。"
                "逐層對應；該張文字層數比樣式多的，多出的維持原樣。"))
            _sc1,_sc2=st.columns([2,1])
            _sty=_sc1.selectbox("樣式", list(_STYLES.keys()), key="style_pick",
                                label_visibility="collapsed")
            if _sc2.button("套用樣式", key="apply_style", use_container_width=True, type="primary"):
                _snb,_sn=_apply_style(st.session_state["xml_content"], _sty)
                _commit_change(f"樣式:{_sty}", _snb, _sn, f"已套用樣式「{_sty}」到 {_sn} 個文字圖層")
        st.divider()
    st.caption("選擇模板套用到全部投影片")

    if not TEMPLATES:
        st.info("尚未定義任何模板。請在程式碼 §TEMPLATES 區塊新增。")
    else:
        _TPL_CAT={
            "prune_empty":"統整","tidy":"統整","prune_slides":"統整",
            "keep_first":"統整","del_last":"統整",
            "tc2sc":"轉換","pinyin":"轉換",
            "reverse_layers":"操作","split_lines":"操作","layers_to_slides":"操作",
            "add_layer":"操作","merge_runs":"操作","merge_rows":"操作",
        }
        def _tpl_cat(t):
            return t.get("cat") or (_TPL_CAT.get(t.get("action"),"其他")
                                    if t.get("action") else "操作")
        _CAT_ORDER=["轉換","操作","統整","其他"]
        _flat=[]
        for _cat in _CAT_ORDER:
            _grp=[(gi,gt) for gi,gt in enumerate(TEMPLATES) if _tpl_cat(gt)==_cat]
            if not _grp: continue
            _flat.append(("hdr",_cat,None,0))
            for _j2,(gi,gt) in enumerate(_grp):
                _flat.append(("tpl",gi,gt,_j2))
        _cols=None
        for _kind,_a,_b,_j in _flat:
            if _kind=="hdr":
                st.markdown(f"##### {_a}"); _cols=None; continue
            ti,tpl=_a,_b
            if _j%3==0: _cols=st.columns(3)
            with _cols[_j%3], st.container(border=True):
                # 說明放在名稱旁的小問號 ? 提示（滑過顯示）
                st.markdown(f"**{tpl['name']}**", help=tpl["desc"])
                action=tpl.get("action")
                # 展開內只放「額外選項 + 套用按鈕」
                if action=="pinyin":
                    st.checkbox("mi轉換（把敬語「祢」的拼音 mi 改成 ni）",
                                value=True, key=f"mi2ni_{ti}")
                elif action=="tc2sc":
                    st.checkbox("反向（簡→繁）", value=False, key=f"rev_{ti}")
                elif action=="prune_slides":
                    st.checkbox("保留只有背景影片/圖片的投影片",
                                value=True, key=f"keepbg_{ti}")
                elif action=="tidy":
                    st.checkbox("連單換行都刪（接成一行、補空格；空行段落保留）",
                                value=False, key=f"dropnl_{ti}")
                elif action=="keep_first":
                    st.number_input("保留前幾個圖層", min_value=1, max_value=50,
                                    value=2, step=1, key=f"keepn_{ti}")

                def _commit(nb, cnt, msg):
                    _commit_change(tpl["name"], nb, cnt, msg)

                # 拼音斷句：偵測到需詢問時，跳出視窗
                if action=="pinyin" and st.session_state.get("_py_ask")==ti:
                    _pinyin_dialog(ti, tpl["name"])

                if st.button("套用到全部投影片", key=f"tpl_{ti}",
                             use_container_width=True, type="primary"):
                    src=st.session_state["xml_content"]
                    try:
                        if action=="reverse_layers":
                            nb,n=_reverse_layers(src); _commit(nb,n,f"已顛倒 {n} 張的圖層順序")
                        elif action=="prune_empty":
                            nb,n=_prune_empty_layers(src); _commit(nb,n,f"已刪除 {n} 個空圖層")
                        elif action=="split_lines":
                            nb,n=_split_layer_lines(src); _commit(nb,n,f"已拆出 {n} 個新圖層")
                        elif action=="layers_to_slides":
                            nb,n=_split_layers_to_slides(src); _commit(nb,n,f"已把圖層拆成 {n} 張新投影片")
                        elif action=="add_layer":
                            nb,n=_add_layer_all(src)
                            _commit(nb,n,f"已為 {n} 張投影片各加一個圖層" if n
                                    else "找不到可作範本的文字圖層")
                        elif action=="del_last":
                            nb,n=_del_last_layer(src); _commit(nb,n,f"已刪除 {n} 張的最後一個圖層")
                        elif action=="tidy":
                            _dn=st.session_state.get(f"dropnl_{ti}", False)
                            nb,n=_apply_tidy(src, _dn)
                            _commit(nb,n,f"已整理 {n} 個圖層的空格"+("（含刪單換行）" if _dn else ""))
                        elif action=="prune_slides":
                            nb,n=_delete_empty_slides(src, st.session_state.get(f"keepbg_{ti}", True))
                            _commit(nb,n,f"已刪除 {n} 張無圖層的投影片")
                        elif action=="keep_first":
                            keep=int(st.session_state.get(f"keepn_{ti}", 2))
                            nb,n=_keep_first_layers(src, keep)
                            _commit(nb,n,f"已處理 {n} 張（只保留前 {keep} 個圖層）")
                        elif action=="merge_runs":
                            nb,n=_merge_layer_runs(src); _commit(nb,n,f"已合併 {n} 個圖層的段落")
                        elif action=="merge_rows":
                            nb,n=_merge_double_rows(src); _commit(nb,n,f"已兩兩合併 {n} 組（上下雙排）")
                        elif action=="tc2sc":
                            rev=st.session_state.get(f"rev_{ti}", False)
                            nb,n,errs=_apply_tc2sc(src, rev)
                            _commit(nb,n,f"{n} 個圖層已{'簡轉繁' if rev else '繁轉簡'}"
                                    +(f"（{len(errs)} 個錯誤）" if errs else ""))
                        elif action=="pinyin":
                            if _pinyin_has_multiline(src):
                                st.session_state["_py_ask"]=ti; st.rerun()
                            else:
                                nb,n,engine=_apply_pinyin(src, st.session_state.get(f"mi2ni_{ti}", True))
                                if engine is None:
                                    st.error("拼音引擎不可用：請 pip install pypinyin。")
                                else:
                                    _commit(nb,n,f"已把 {n} 張的拼音寫入第二層（引擎：{engine}）")
                    except Exception as e:
                        st.error(f"套用時發生問題：{e}（檔案未變動，可改用側邊欄「🔄 卡住了？重設」）")

    # ── 第三部分：大量填入文字（每頁一行，依序填入指定圖層）──────────
    st.divider()
    with st.container(border=True):
        st.markdown("**大量填入文字**",
                    help="貼上和頁數相同行數的文字，一行對一頁、按文件順序填入指定的文字圖層。")
        _bm, _bg = _parse_xml(st.session_state["xml_content"])
        _btargets = [s for g in _bg for s in g["slides"]
                     if any(l["type"]=="RVTextElement" for l in s["layers"])]
        _bmax = max((sum(1 for l in s["layers"] if l["type"]=="RVTextElement")
                     for g in _bg for s in g["slides"]), default=0)
        _bc1, _bc2 = st.columns([1,2])
        _blayer = _bc1.number_input(
            "覆蓋第幾個文字圖層", min_value=1, max_value=max(_bmax+1, 1), value=1, step=1,
            key="bulk_layer",
            help=(f"1～{_bmax}：覆蓋每頁第 N 個文字圖層的內文；"
                  f"填 {_bmax+1}（超過現有層數）＝在每頁最後新增一個圖層放這些文字。"))
        _bc2.caption(f"可填 **{len(_btargets)}** 頁（有文字圖層的投影片）。"
                     f"目前各頁最多 {_bmax} 個文字圖層。")
        _btext = st.text_area("貼上文字（每頁一行）", key="bulk_text", height=240,
                              placeholder="第一頁\n第二頁\n第三頁\n…",
                              label_visibility="collapsed")
        _blines = _btext.split("\n")
        if len(_blines) > 1 and _blines[-1] == "": _blines = _blines[:-1]   # 去掉尾端多的一行
        _bok = len(_btargets) > 0 and len(_blines) == len(_btargets)
        st.caption(f"輸入 **{len(_blines)}** 行 ／ 需要 **{len(_btargets)}** 行"
                   + ("　✅ 行數相符" if _bok else "　⚠️ 行數需與頁數相符才能填入"))
        if st.button("填入全部投影片", key="bulk_apply", type="primary",
                     use_container_width=True, disabled=not _bok):
            try:
                _bnb,_bn,_berr = _bulk_fill_lines(
                    st.session_state["xml_content"], _blines, int(_blayer))
                if _berr:
                    st.error(_berr)
                elif _bn == 0:
                    st.info("沒有任何變更（內容與原本相同？）")
                else:
                    _commit_change("大量填入", _bnb, _bn, f"已把文字填入 {_bn} 張投影片")
            except Exception as e:
                st.error(f"填入時發生問題：{e}（檔案未變動，可改用側邊欄「🔄 卡住了？重設」）")


# ─── TAB 3: 撰寫（逐段編輯明文，失焦自動儲存）─────────────────
# 包成 fragment：編輯/儲存單一段落時只重跑此區塊，不重新解析整份檔案、不動其他分頁。
@st.fragment
def _write_tab():
    # fragment 內自行重讀 session_state 的最新內容並重解析，
    # 確保存檔後本區塊（含下方數字串）即時更新，而其餘分頁與側欄維持不動。
    xml=st.session_state["xml_content"]
    _dm, groups=_parse_xml(xml)

    # 各投影片圖層數一覽（一字一張，隨內容即時更新，方便快速掃描異常）
    _slides_flat = [s for g in groups for s in g["slides"]]
    _layer_counts = "".join(str(len(s["layers"])) for s in _slides_flat)
    st.markdown(
        '<div style="font-family:monospace;font-size:.9rem;color:#999;letter-spacing:2px;'
        f'word-break:break-all;margin:.2rem 0 .6rem">圖層數：{_layer_counts}</div>',
        unsafe_allow_html=True)
    st.markdown("---")

    if st.session_state.get("_text_err"):
        st.error(f"{st.session_state.pop('_text_err')}")
    if st.session_state.get("_hk_msg"):
        st.info(st.session_state.pop("_hk_msg"), icon="⌨️")

    def _save_layer_text(gi, si, li, key):
        """整層編輯失焦自動儲存：把整層文字以「首字（第一段）的字體/字級/顏色」寫回。"""
        text=st.session_state.get(key,"")
        xml=st.session_state["xml_content"]
        nb,err=_set_layer_text(xml, gi, si, li, text)
        if err: st.session_state["_text_err"]=err; return
        if nb is xml: return                         # 無變動
        _push_undo()
        st.session_state["xml_content"]=nb
        st.session_state.pop(key, None)
        st.session_state["history"].append(f"文字G{gi}S{si}L{li}")

    def _set_group(num, name, color):
        """按了段落類型按鈕：從這張往後（同組連續範圍）整段套用名稱+顏色，整頁刷新。
        類型為「標題」時，另把首頁首圖層內文左右加上書名號《》（已包則不動）。"""
        xml=st.session_state["xml_content"]
        nb,err=_set_group_fill(xml, num, name, color)
        if not err and name=="標題":
            nb,_=_wrap_title_marks(nb)               # 順帶把首頁首圖層包成《…》
        if not err and nb is not xml:
            _push_undo(); st.session_state["xml_content"]=nb
            st.session_state["history"].append(f"群組S{num}:{name}")
        st.rerun()                                   # 整頁刷新，連帶更新側邊欄群組

    def _save_hotkey(num):
        """設定熱鍵（自動轉大寫）；若該鍵已被別張用，覆蓋（從舊的移走）並提示。"""
        key=st.session_state.get(f"hk_{num}","").strip().upper()
        xml=st.session_state["xml_content"]
        owner=_hotkey_owner(xml, key, exclude=num) if key else None
        nb,err=_set_slide_hotkey(xml, num, key)
        if err: st.session_state["_text_err"]=err; return
        if nb is xml: return
        _push_undo(); st.session_state["xml_content"]=nb
        if owner:
            st.session_state["_hk_msg"]=f"熱鍵「{key}」原本在 Slide {owner}，已覆蓋改設到 Slide {num}"
        st.session_state["history"].append(f"熱鍵S{num}")
        for k in [k for k in st.session_state if k.startswith("hk_")]:
            st.session_state.pop(k, None)

    def _swatch(hx):
        if not hx or hx=="?": return ""
        return (f'<span style="display:inline-block;width:10px;height:10px;border:1px solid #999;'
                f'background:{hx};vertical-align:middle;margin-right:3px"></span>')

    for gi,g in enumerate(groups):
        text_slides=[sl for sl in g["slides"]
                     if any(l["type"]=="RVTextElement" for l in sl["layers"])]
        if not text_slides: continue
        for si,slide in enumerate(text_slides):
            si_orig=next(i for i,s in enumerate(g["slides"]) if s["num"]==slide["num"])
            num=slide["num"]
            lbl=slide["label"] or f"Slide {num}"
            # slide 標頭：外層 [1,3] 與下方編輯列同切，使右側控制區左緣對齊文字輸入框；
            # 控制區＝零間距水平容器：熱鍵 ＋ 段落 popover ＋ 刪除鈕(緊貼相鄰)
            _lab,_ctrl=st.columns([1,3], vertical_alignment="center")
            _lab.markdown(f"`Slide {num}` {lbl}")
            with _ctrl.container(horizontal=True, gap="xsmall", vertical_alignment="center"):
                if f"hk_{num}" not in st.session_state:
                    st.session_state[f"hk_{num}"]=slide["hotKey"]
                st.text_input("熱鍵", key=f"hk_{num}", max_chars=1, autocomplete="off",
                              placeholder="鍵", label_visibility="collapsed",
                              on_change=_save_hotkey, args=(num,))
                _cur=g["name"]
                _curlabel=f"{_GROUP_EMOJI.get(_cur,'⚫')} {_cur if _cur in _GROUP_EMOJI else '段落'}"
                with st.popover(_curlabel, key=f"grppop_{num}"):
                    for _gname,_ghex in _GROUP_PRESETS:
                        if st.button(f"{_GROUP_EMOJI[_gname]} {_gname}",
                                     key=f"grpbtn_{num}_{_gname}", use_container_width=True):
                            _set_group(num, _gname, _ghex)
                if st.button("🗑", key=f"delbtn_{num}", help="刪除這張投影片"):
                    st.session_state["_del_ask"]=num; st.rerun()
            for layer in [l for l in slide["layers"] if l["type"]=="RVTextElement"]:
                p=layer["pos"]; runs=layer["runs"]
                # full＝整層文字，已移除「換樣式時多出來的換行」（見 _drop_style_break_nl）
                full=layer.get("full","")
                if runs:                                  # 首字（第一段）樣式提示
                    r0=runs[0]
                    sz=f"{r0.font_size_pt:g}pt" if r0.font_size_pt else "?"
                    styles=[s for s,v in [("粗",r0.bold),("斜",r0.italic),("底線",r0.underline)] if v]
                    hint=(f'　首字樣式 {_swatch(r0.color_hex)}{r0.font_name} {sz} {r0.color_hex}'
                          + ("　"+"・".join(styles) if styles else ""))
                else:
                    hint='　<span style="color:#c0392b">空圖層（可直接輸入）</span>'
                st.markdown(
                    f'<div style="color:#444;font-size:.74rem;font-weight:600;margin:.5rem 0 .2rem">'
                    f'圖層 L{layer["idx"]}<span style="font-weight:400;color:#888">　'
                    f'x={p["x"]} y={p["y"]} w={p["w"]} h={p["h"]}{hint}</span></div>',
                    unsafe_allow_html=True)
                k=f"txt_{gi}_{si_orig}_{layer['idx']}"
                if k not in st.session_state: st.session_state[k]=full
                _h=max(68, min(240, 26*(full.count("\n")+1)+16))
                st.text_area(f"L{layer['idx']}", key=k, height=_h,
                             label_visibility="collapsed",
                             on_change=_save_layer_text,
                             args=(gi, si_orig, layer["idx"], k))
            st.markdown("<hr style='margin:.25rem 0;border:none;border-top:1px solid #eee'>",
                        unsafe_allow_html=True)


with tab_text:
    st.caption("每個圖層一個輸入框、可多行（換行直接按 Enter）。存檔時整層套用「首字樣式」"
               "（第一段的字體/字級/顏色），所以同層原本不同樣式會統一。（繁→簡、拼音在「模板」分頁）")
    if st.session_state.get("_del_ask") is not None:     # 刪除投影片確認框
        _del_slide_dialog(st.session_state["_del_ask"])
    _write_tab()


# ─── TAB 4: 創造（從文字產生新檔，會取代目前編輯對象）─────────────
with tab_new:
    st.caption("產生後會以新檔取代目前的編輯對象（記得先匯出舊檔）。")
    _create_ui()