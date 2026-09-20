r"""
pro7.py · ProPresenter 7（.pro，protobuf）→ ProPresenter 6（.pro6，XML）轉換
═══════════════════════════════════════════════════════════════════
單向、唯讀解析：把 Pro7 的 protobuf 簡報檔轉成 Pro6 能直接開的 XML。
純標準庫（自帶極簡 protobuf 解碼器），不依賴 google.protobuf。

── 為什麼可以無損轉文字 ──────────────────────────────────────────
Pro7 的文字圖層內文（Graphics.Text.rtf_data）就是一份完整的 cocoa RTF
文件 bytes；Pro6 的 RTFData 也是同一族 RTF（只是多包一層 base64）。
所以歌詞轉換＝把 Pro7 的 RTF 原封 base64 進 Pro6 節點——字體、字級、
顏色、斷行、多樣式 run 全部保真，不經過任何重編碼。

── 欄位編號來源 ──────────────────────────────────────────────────
社群逆向的 proto 定義（github.com/greyshirtguy/ProPresenter7-Proto，
Proto7.16.2）。本檔用到的路徑：
  Presentation(root): name=3, cue_groups=12, cues=13, ccli=14
    CCLI: author=1, artist_credits=2, song_title=3, publisher=4,
          copyright_year=5, song_number=6
    CueGroup: group=1(Group), cue_identifiers=2(UUID[])
      Group: uuid=1, name=2, color=3(Color: float r=1 g=2 b=3 a=4)
  Cue: uuid=1, name=2, hot_key=8(HotKey: code=1), actions=10
    Action: label=3(Label: text=2), type=9, slide=23(SlideType)
      SlideType: presentation=2(PresentationSlide)
        PresentationSlide: base_slide=1(Slide), notes=2(rtf_data=1)
          Slide: elements=1(Slide.Element), draws_background_color=4,
                 background_color=5, size=6(w=1,h=2 double), uuid=7
            Slide.Element: element=1(Graphics.Element)
              Graphics.Element: uuid=1, name=2, bounds=3(Rect:
                origin=1{x=1,y=2}, size=2{w=1,h=2}，皆 double),
                opacity=5(double), text=13(Graphics.Text), hidden=16
                Graphics.Text: rtf_data=5(bytes),
                  vertical_alignment=6(0=top,1=middle,2=bottom──與
                  pro6 的 verticalAlignment 數值相同)
  HotKey.code: KeyCode enum，1..26=A..Z、27..36=0..9

── 已知取捨（轉不過去的東西）─────────────────────────────────────
• 背景媒體：cue 內嵌的媒體 action（Action.media=20 → MediaType.element=5
  → Media.url=2）與元素層的 media fill（Element.fill=9 → Fill.media=3）
  有 URL 就轉成 pro6 的 backgroundMediaCue／RVImage(Video)Element（路徑
  引用；可用 path_map 換前綴）。從 media bin 以 UUID 連結、檔內沒有 URL
  的（實測教會檔多屬此類）無從轉起，略過。shape、特效、transition 略過。
• Pro7 的 arrangements（編曲順序）：忽略，依文件原始順序輸出。
• Cue.isEnabled 是 proto3 bool，寫 false 時欄位直接省略、無從與
  「未設定」區分——一律輸出 enabled="true"。
"""

import base64
import re
import struct
import uuid as _uuid_mod
from urllib.parse import quote

__all__ = ["is_pro7", "parse_pro7", "pro7_to_pro6", "Pro7Error"]


class Pro7Error(ValueError):
    """看得懂的轉換錯誤（給 UI 顯示）。"""


# ═══════════════════════════════════════════════════════════════
# §1  極簡 protobuf 解碼器（唯讀）
#     _decode(buf) → {field: [(wiretype, value), ...]}；巢狀訊息
#     以 bytes 存放、需要時再 _decode 一層（lazy，不用 schema）。
# ═══════════════════════════════════════════════════════════════

def _read_varint(b, i):
    r = 0; s = 0
    while True:
        if i >= len(b): raise Pro7Error("protobuf 結構損毀（varint 越界）")
        x = b[i]; i += 1
        r |= (x & 0x7F) << s
        if not x & 0x80: return r, i
        s += 7
        if s > 70: raise Pro7Error("protobuf 結構損毀（varint 過長）")

def _decode(buf: bytes) -> dict:
    out = {}
    i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        f, wt = tag >> 3, tag & 7
        if f == 0: raise Pro7Error("protobuf 結構損毀（field 0）")
        if wt == 0:
            v, i = _read_varint(buf, i)
        elif wt == 1:
            v = buf[i:i+8]; i += 8
        elif wt == 5:
            v = buf[i:i+4]; i += 4
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            if i + ln > len(buf): raise Pro7Error("protobuf 結構損毀（長度越界）")
            v = buf[i:i+ln]; i += ln
        else:
            raise Pro7Error(f"protobuf 結構損毀（不支援的 wiretype {wt}）")
        out.setdefault(f, []).append((wt, v))
    return out

# ── 取值 helper：msg 為 _decode 的結果 ─────────────────────────
def _first(msg, f):
    v = msg.get(f)
    return v[0] if v else None

def _sub(msg, f) -> dict:
    """欄位 f 的第一個巢狀訊息（無則空 dict）。"""
    v = _first(msg, f)
    return _decode(v[1]) if v and v[0] == 2 else {}

def _subs(msg, f) -> list:
    """欄位 f 的所有巢狀訊息。"""
    return [_decode(v) for wt, v in msg.get(f, []) if wt == 2]

def _str(msg, f, default="") -> str:
    v = _first(msg, f)
    if not v or v[0] != 2: return default
    try: return v[1].decode("utf-8")
    except UnicodeDecodeError: return default

def _bytes(msg, f) -> bytes:
    v = _first(msg, f)
    return v[1] if v and v[0] == 2 else b""

def _varint(msg, f, default=0) -> int:
    v = _first(msg, f)
    return v[1] if v and v[0] == 0 else default

def _double(msg, f, default=0.0) -> float:
    v = _first(msg, f)
    if not v: return default
    if v[0] == 1: return struct.unpack("<d", v[1])[0]
    if v[0] == 5: return struct.unpack("<f", v[1])[0]
    return default

def _float(msg, f, default=0.0) -> float:
    v = _first(msg, f)
    if not v: return default
    if v[0] == 5: return struct.unpack("<f", v[1])[0]
    if v[0] == 1: return struct.unpack("<d", v[1])[0]
    return default

def _uuid_str(msg, f) -> str:
    """rv.data.UUID 欄位 → 大寫字串；無則空字串。"""
    return _str(_sub(msg, f), 1).upper()


# ═══════════════════════════════════════════════════════════════
# §2  Pro7 結構抽取 → 純 dict 模型
# ═══════════════════════════════════════════════════════════════

# KeyCode enum → pro6 hotKey 字元（1..26=A..Z、27..36=0..9；其餘不轉）
_KEYCODE = {i: chr(ord("A") + i - 1) for i in range(1, 27)}
_KEYCODE.update({i: str(i - 27) for i in range(27, 37)})

def _color_str(cmsg, default="0 0 0 0") -> str:
    """rv.data.Color → pro6 顏色字串「r g b a」(0~1、6 位小數)。"""
    if not cmsg: return default
    r = _float(cmsg, 1); g = _float(cmsg, 2); b = _float(cmsg, 3); a = _float(cmsg, 4)
    return f"{r:.6f} {g:.6f} {b:.6f} {a:.6f}"

def _rtf_plain(rtf_bytes: bytes) -> str:
    """RTF → 純文字的極簡萃取（僅供 slide notes 用；歌詞走 RTF 原封搬運）。"""
    try: s = rtf_bytes.decode("utf-8", errors="replace")
    except Exception: return ""
    m = re.search(r"\\pard[^\\{}]*", s)
    body = s[m.end():] if m else s
    out = []
    for tok in re.finditer(
            r"\\u(-?\d+)\s?\??|\\\'([0-9a-fA-F]{2})|\\\r?\n|\\[a-zA-Z*]+-?\d*\s?"
            r"|\\([{}\\])|([^\\{}\r\n]+)|[\r\n]+", body):
        if tok.group(1) is not None:
            cp = int(tok.group(1)); out.append(chr(cp + 65536 if cp < 0 else cp))
        elif tok.group(2) is not None:
            try: out.append(bytes([int(tok.group(2), 16)]).decode("cp950"))
            except Exception: pass
        elif tok.group(3) is not None:
            out.append(tok.group(3))
        elif tok.group(4) is not None:
            out.append(tok.group(4))
        elif tok.group(0).startswith("\\") and tok.group(0)[1:2] in ("\n", "\r"):
            out.append("\n")
    return "".join(out).strip()

# header 群組（fonttbl/colortbl/expandedcolortbl）：判空時先剝掉
_RTF_HDR_GROUP = re.compile(r"\{\\\*?\\?(?:fonttbl|colortbl|expandedcolortbl)[^{}]*\}")

def _rtf_is_empty(rtf: bytes) -> bool:
    """Pro7 的「空文字層」是 header-only RTF（無 \\pard、無內文）。
    剝掉 header 群組與控制字後若無任何內容 token（\\uNNNN、\\'xx、可見字元）
    即視為空。空圖層仍是圖層、照樣輸出（report 以 n_empty 統計），
    這個判定只用於統計呈現。"""
    try: s = rtf.decode("utf-8", "replace")
    except Exception: return False
    s = _RTF_HDR_GROUP.sub("", s)
    if re.search(r"\\u-?\d", s): return False          # unicode 字＝有內容（\uc0 不會誤中）
    if re.search(r"\\'[0-9a-fA-F]{2}", s): return False  # 碼頁 hex 字＝有內容
    s = re.sub(r"\\[a-zA-Z*]+-?\d*\s?", "", s)         # 控制字
    if re.search(r"\\[{}\\]", s): return False         # 跳脫字面 { } \ ＝有內容
    return not s.replace("{", "").replace("}", "").strip()

_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg")
_AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".aiff", ".flac")

def _url_str(url_msg) -> str:
    """rv.data.URL → 路徑字串（優先 absolute_string，其次 relative_path /
    local.path）；無則空字串。"""
    if not url_msg: return ""
    s = _str(url_msg, 1) or _str(url_msg, 2)
    if not s:
        s = _str(_sub(url_msg, 4), 2)      # LocalRelativePath.path
    return s

def _to_file_url(s: str) -> str:
    """路徑 → pro6 的 file:// URL（已是 URL 則原樣；純路徑補 scheme＋percent-encode）。"""
    if not s or "://" in s: return s
    return "file://" + quote(s, safe="/")

def _media_kind(path: str, media_msg=None, action_media=None) -> str:
    """判斷媒體種類：先看 oneof（Media TypeProperties 4/5/6、MediaType 6/7/8），
    再退回副檔名。回傳 'video' / 'image' / 'audio'。"""
    if media_msg is not None:
        if 6 in media_msg: return "video"
        if 5 in media_msg: return "image"
        if 4 in media_msg: return "audio"
    if action_media is not None:
        if 7 in action_media: return "video"
        if 6 in action_media: return "image"
        if 8 in action_media: return "audio"
    low = path.lower()
    if low.endswith(_VIDEO_EXT): return "video"
    if low.endswith(_AUDIO_EXT): return "audio"
    return "image"

def _media_from_action(act) -> dict:
    """Action 內的媒體（背景 cue 用）：有 URL 才回 {kind,url,name}；否則 None。"""
    am = _sub(act, 20)                      # Action.media (MediaType)
    if not am: return None
    el = _sub(am, 5)                        # MediaType.element (rv.data.Media)
    url = _url_str(_sub(el, 2))
    if not url: return None                 # media bin 連結（無 URL）→ 轉不了
    kind = _media_kind(url, el, am)
    if kind == "audio": return None         # pro6 背景 cue 不收音訊
    return {"kind": kind, "url": url, "name": _str(act, 2)}

def is_pro7(raw: bytes, name: str = "") -> bool:
    """這份 bytes 是不是 Pro7 的 .pro protobuf？
    XML（pro6）以 '<' 或 BOM+'<' 開頭；protobuf 開頭是 field 1 的 tag(0x0A)。
    副檔名 .pro（非 .pro6）且內容非 XML 即視為 Pro7。"""
    # 注意：不能對整份 lstrip——protobuf 開頭 0x0A 正好是 '\n'，會被當空白吃掉
    if raw.lstrip()[:1] == b"<": return False              # XML（可容忍 BOM/空白開頭）
    if name.lower().endswith(".pro6") or name.lower().endswith(".xml"): return False
    if name.lower().endswith(".pro"): return True
    return raw[:1] == b"\x0a"       # 無副檔名線索時看 magic（field 1 的 tag）

def parse_pro7(data: bytes) -> dict:
    """解析 .pro bytes → 純 dict 模型：
    {title, ccli:{...}, width, height,
     groups:[{name, color, slides:[{uuid,label,hotkey,notes,bg_color,
              draws_bg, elements:[{uuid,name,x,y,w,h,valign,rtf,hidden,
              has_text}], n_media}]}]}
    群組依「文件順序走訪 cues、遇到組別變化就開新組」重建，未入組的
    cue 歸入無名組——與 ProPresenter 顯示順序一致。"""
    try:
        root = _decode(data)
    except Pro7Error:
        raise
    except Exception as e:
        raise Pro7Error(f"protobuf 解析失敗：{e}")
    if 13 not in root and 3 not in root:
        raise Pro7Error("不是 ProPresenter 7 簡報檔（找不到 cues/name 欄位）")

    ccli_m = _sub(root, 14)
    ccli = {
        "author":    _str(ccli_m, 1),
        "artist":    _str(ccli_m, 2),
        "title":     _str(ccli_m, 3),
        "publisher": _str(ccli_m, 4),
        "year":      _varint(ccli_m, 5) or "",
        "number":    _varint(ccli_m, 6) or "",
        "display":   bool(_varint(ccli_m, 7)),
    }

    width = height = 0

    def _cue_to_slide(cue):
        """單一 Cue → slide dict；非投影片 cue（純媒體/音訊）回 None。"""
        nonlocal width, height
        hot = _KEYCODE.get(_varint(_sub(cue, 8), 1), "")
        label = _str(cue, 2)
        pres = None
        bg = None
        for act in _subs(cue, 10):       # 掃全部 action：投影片＋（可能的）背景媒體
            if pres is None:
                p = _sub(_sub(act, 23), 2)
                if p:
                    pres = p
                    if not label: label = _str(_sub(act, 3), 2)   # Action.Label.text
                    continue
            if bg is None:
                bg = _media_from_action(act)
        if pres is None:
            return None                  # 非投影片 cue（純媒體/音訊等）→ 跳過
        base = _sub(pres, 1)
        notes = _rtf_plain(_bytes(_sub(pres, 2), 1))
        ssize = _sub(base, 6)
        w = _double(ssize, 1); h = _double(ssize, 2)
        if w > width: width = int(round(w))
        if h > height: height = int(round(h))
        elements = []
        n_media = 0
        for se in _subs(base, 1):
            el = _sub(se, 1)
            text = _sub(el, 13)
            rtf = _bytes(text, 5)
            bounds = _sub(el, 3)
            org = _sub(bounds, 1); siz = _sub(bounds, 2)
            fill_media = _sub(_sub(el, 9), 3)              # Element.fill → Fill.media
            murl = _url_str(_sub(fill_media, 2))
            elements.append({
                "uuid":   _uuid_str(el, 1) or str(_uuid_mod.uuid4()).upper(),
                "name":   _str(el, 2),
                "x": int(round(_double(org, 1))), "y": int(round(_double(org, 2))),
                "w": int(round(_double(siz, 1))), "h": int(round(_double(siz, 2))),
                "valign": _varint(text, 6, 0),
                "rtf":    rtf,
                "hidden": bool(_varint(el, 16)),
                "has_text": bool(rtf.strip()),
                "is_empty": bool(rtf.strip()) and _rtf_is_empty(rtf),
                "media_url":  murl,
                "media_kind": _media_kind(murl, fill_media) if murl else "",
            })
            if not rtf.strip() and not murl: n_media += 1
        return {
            "uuid":     _uuid_str(base, 7) or str(_uuid_mod.uuid4()).upper(),
            "label":    label,
            "hotkey":   hot,
            "notes":    notes,
            "bg_color": _color_str(_sub(base, 5), "0 0 0 1"),
            "draws_bg": bool(_varint(base, 4)),
            "elements": elements,
            "n_media":  n_media,
            "bg":       bg,
        }

    # ── 重點：顯示順序＝cue_groups 的順序 ＋ 各組 cue_identifiers 的順序。
    #    Presentation.cues（field 13）只是「儲存袋」，實測順序是打散的；
    #    照它走會把群組切成幾十段。未被任何群組引用的 cue 依檔內順序
    #    附在最後（無名群組）。
    cue_by_uuid = {}
    cue_order = []                                    # 檔內順序（fallback 用）
    for cue in _subs(root, 13):
        cu = _uuid_str(cue, 1)
        cue_by_uuid[cu] = cue
        cue_order.append(cu)

    groups = []
    used = set()
    for cg in _subs(root, 12):
        g = _sub(cg, 1)
        gname = _str(g, 2)
        gcolor = _color_str(_sub(g, 3))
        slides = []
        for u in _subs(cg, 2):                        # cue_identifiers（有序）
            us = _str(u, 1).upper()
            cue = cue_by_uuid.get(us)
            if cue is None: continue
            used.add(us)
            sl = _cue_to_slide(cue)
            if sl is not None: slides.append(sl)
        if slides:
            groups.append({"name": gname, "color": gcolor, "slides": slides})
    leftover = []
    for cu in cue_order:
        if cu in used: continue
        sl = _cue_to_slide(cue_by_uuid[cu])
        if sl is not None: leftover.append(sl)
    if leftover:
        groups.append({"name": "", "color": "0 0 0 0", "slides": leftover})

    return {
        "title":  _str(root, 3),
        "ccli":   ccli,
        "width":  width or 1920,
        "height": height or 1080,
        "groups": groups,
    }


# ═══════════════════════════════════════════════════════════════
# §3  Pro6 XML 生成
#     結構比照 app.py 的「創造」路徑（該結構經 tests 驗證 ProPresenter
#     6.x 可正常開啟）；文字圖層的 RTFData ＝ Pro7 RTF 原封 base64。
# ═══════════════════════════════════════════════════════════════

def _esc(s: str) -> str:
    """XML 屬性值跳脫（含換行——notes 可能多行）。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("\n", "&#10;"))

def _text_element_xml(el: dict) -> str:
    b64 = base64.b64encode(el["rtf"]).decode("ascii")
    name = _esc(el["name"] or "TextElement")
    return (f'<RVTextElement UUID="{el["uuid"]}" additionalLineFillHeight="0.000000" '
            'adjustsHeightToFit="false" bezelRadius="0.000000" displayDelay="0.000000" '
            f'displayName="{name}" drawLineBackground="false" drawingFill="false" '
            'drawingShadow="false" drawingStroke="false" fillColor="0 0 0 0" '
            'fromTemplate="false" lineBackgroundType="0" lineFillVerticalOffset="0.000000" '
            'locked="false" opacity="1.000000" persistent="false" revealType="0" '
            'rotation="0.000000" source="" textSourceRemoveLineReturnsOption="false" '
            f'typeID="0" useAllCaps="false" verticalAlignment="{el["valign"]}">'
            f'<RVRect3D rvXMLIvarName="position">{{{el["x"]} {el["y"]} 0 {el["w"]} {el["h"]}}}</RVRect3D>'
            '<shadow rvXMLIvarName="shadow">0.000000|0 0 0 0|{4, -4}</shadow>'
            '<dictionary rvXMLIvarName="stroke">'
            '<NSColor rvXMLDictionaryKey="RVShapeElementStrokeColorKey">0 0 0 0</NSColor>'
            '<NSNumber hint="integer" rvXMLDictionaryKey="RVShapeElementStrokeWidthKey">0</NSNumber>'
            '</dictionary>'
            f'<NSString rvXMLIvarName="RTFData">{b64}</NSString>'
            '</RVTextElement>')

def _map_url(url: str, path_map) -> str:
    """套用路徑前綴替換（同時試 raw 與 percent-encoded 兩種寫法），再轉 file:// URL。"""
    if path_map and path_map[0]:
        old, new = path_map
        url = url.replace(old, new)
        qold, qnew = quote(old, safe="/:"), quote(new, safe="/:")
        if qold != old: url = url.replace(qold, qnew)
    return _to_file_url(url)

# 影片/圖片元素的共用屬性（模板取自實際 ProPresenter 6 檔；時長/幀率未知，
# 填中性預設值——Pro6 開檔後會依實際媒體重讀）
def _video_element_xml(url, name, x, y, w, h, ivar) -> str:
    return (f'<RVVideoElement UUID="{str(_uuid_mod.uuid4()).upper()}" audioVolume="1.000000" '
            'bezelRadius="0.000000" displayDelay="0.000000" displayName="'+_esc(name or "VideoElement")+'" '
            'drawingFill="false" drawingShadow="false" drawingStroke="false" endPoint="0" '
            'fieldType="0" fillColor="" flippedHorizontally="false" flippedVertically="false" '
            'format="" frameRate="0.000000" fromTemplate="false" imageOffset="{0, 0}" inPoint="0" '
            'locked="false" manufactureName="" manufactureURL="" naturalSize="{'+f"{w}, {h}"+'}" '
            'opacity="1.000000" outPoint="0" persistent="false" playRate="1.000000" '
            'playbackBehavior="1" rotation="0.000000" '
            + (f'rvXMLIvarName="{ivar}" ' if ivar else '') +
            f'scaleBehavior="3" scaleSize="{{1, 1}}" source="{_esc(url)}" timeScale="600" typeID="0">'
            f'<RVRect3D rvXMLIvarName="position">{{{x} {y} 0 {w} {h}}}</RVRect3D>'
            '<shadow rvXMLIvarName="shadow">0.000000|0 0 0 0|{4, -4}</shadow>'
            '<dictionary rvXMLIvarName="stroke">'
            '<NSColor rvXMLDictionaryKey="RVShapeElementStrokeColorKey">0 0 0 0</NSColor>'
            '<NSNumber hint="integer" rvXMLDictionaryKey="RVShapeElementStrokeWidthKey">0</NSNumber>'
            '</dictionary></RVVideoElement>')

def _image_element_xml(url, name, x, y, w, h, ivar) -> str:
    return (f'<RVImageElement UUID="{str(_uuid_mod.uuid4()).upper()}" bezelRadius="0.000000" '
            'displayDelay="0.000000" displayName="'+_esc(name or "ImageElement")+'" '
            'drawingFill="false" drawingShadow="false" drawingStroke="false" fillColor="" '
            'flippedHorizontally="false" flippedVertically="false" format="" fromTemplate="false" '
            'imageOffset="{0, 0}" locked="false" manufactureName="" manufactureURL="" '
            'opacity="1.000000" persistent="false" rotation="0.000000" '
            + (f'rvXMLIvarName="{ivar}" ' if ivar else '') +
            f'scaleBehavior="3" scaleSize="{{1, 1}}" source="{_esc(url)}" typeID="0">'
            f'<RVRect3D rvXMLIvarName="position">{{{x} {y} 0 {w} {h}}}</RVRect3D>'
            '<shadow rvXMLIvarName="shadow">0.000000|0 0 0 0|{4, -4}</shadow>'
            '<dictionary rvXMLIvarName="stroke">'
            '<NSColor rvXMLDictionaryKey="RVShapeElementStrokeColorKey">0 0 0 0</NSColor>'
            '<NSNumber hint="integer" rvXMLDictionaryKey="RVShapeElementStrokeWidthKey">0</NSNumber>'
            '</dictionary></RVImageElement>')

def _media_cue_xml(bg: dict, w: int, h: int, path_map) -> str:
    url = _map_url(bg["url"], path_map)
    name = bg["name"] or url.rsplit("/", 1)[-1]
    if bg["kind"] == "video":
        el = _video_element_xml(url, name, 0, 0, w, h, "element")
    else:
        el = _image_element_xml(url, name, 0, 0, w, h, "element")
    return (f'<RVMediaCue UUID="{str(_uuid_mod.uuid4()).upper()}" actionType="0" alignment="4" '
            f'behavior="1" dateAdded="" delayTime="0.000000" displayName="{_esc(name)}" '
            'enabled="true" nextCueUUID="" rvXMLIvarName="backgroundMediaCue" tags="" '
            f'timeStamp="0.000000">{el}</RVMediaCue>')

def _slide_xml(sl: dict, doc_w: int, doc_h: int, path_map=None) -> str:
    parts = []
    for e in sl["elements"]:
        if e["hidden"]: continue
        if e["has_text"]:
            parts.append(_text_element_xml(e))
        elif e["media_url"]:
            url = _map_url(e["media_url"], path_map)
            fn = _video_element_xml if e["media_kind"] == "video" else _image_element_xml
            parts.append(fn(url, e["name"], e["x"], e["y"], e["w"], e["h"], ""))
    cue = _media_cue_xml(sl["bg"], doc_w, doc_h, path_map) if sl.get("bg") else ""
    return (f'<RVDisplaySlide UUID="{sl["uuid"]}" backgroundColor="{sl["bg_color"]}" '
            f'chordChartPath="" drawingBackgroundColor="{"true" if sl["draws_bg"] else "false"}" '
            f'enabled="true" highlightColor="0 0 0 0" hotKey="{_esc(sl["hotkey"])}" '
            f'label="{_esc(sl["label"])}" notes="{_esc(sl["notes"])}" socialItemCount="1">'
            '<array rvXMLIvarName="cues"></array>'
            + cue +
            f'<array rvXMLIvarName="displayElements">{"".join(parts)}</array>'
            '</RVDisplaySlide>')

def _doc_xml(model: dict, path_map=None) -> bytes:
    c = model["ccli"]
    gs = "".join(
        f'<RVSlideGrouping name="{_esc(g["name"])}" color="{g["color"]}" '
        f'uuid="{str(_uuid_mod.uuid4()).upper()}">'
        f'<array rvXMLIvarName="slides">'
        f'{"".join(_slide_xml(s, model["width"], model["height"], path_map) for s in g["slides"])}'
        '</array>'
        '</RVSlideGrouping>' for g in model["groups"])
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<RVPresentationDocument CCLIArtistCredits="{_esc(c["artist"])}" '
        f'CCLIAuthor="{_esc(c["author"])}" CCLICopyrightYear="{_esc(c["year"])}" '
        f'CCLIDisplay="{"true" if c["display"] else "false"}" '
        f'CCLIPublisher="{_esc(c["publisher"])}" CCLISongNumber="{_esc(c["number"])}" '
        f'CCLISongTitle="{_esc(model["title"] or c["title"])}" '
        'backgroundColor="0 0 0 1" buildNumber="100991749" category="Lyrics" '
        'chordChartPath="" docType="0" drawingBackgroundColor="false" '
        f'height="{model["height"]}" lastDateUsed="" notes="" os="2" '
        'resourcesDirectory="" selectedArrangementID="" usedCount="0" '
        f'uuid="{str(_uuid_mod.uuid4()).upper()}" versionNumber="600" '
        f'width="{model["width"]}">'
        '<RVTimeline duration="0.000000" loop="false" playBackRate="0.000000" '
        'rvXMLIvarName="timeline" selectedMediaTrackIndex="0" timeOffset="0.000000">'
        '<array rvXMLIvarName="timeCues"></array><array rvXMLIvarName="mediaTracks"></array>'
        '</RVTimeline>'
        f'<array rvXMLIvarName="groups">{gs}</array>'
        '<array rvXMLIvarName="arrangements"></array>'
        '</RVPresentationDocument>').encode("utf-8")


def pro7_to_pro6(data: bytes, path_map=None) -> tuple:
    """Pro7 .pro bytes → (pro6 XML bytes, report dict)。
    path_map=(舊前綴, 新前綴)：套用到所有媒體路徑（背景 cue 與媒體元素）。
    report: title / width / height / n_groups / n_slides / n_text /
            n_bg（帶出的背景媒體 cue）/ n_media_el（帶出的媒體元素）/
            n_skipped（無 URL 或隱藏而略過的元素數）/ groups=[(名, 張數)]"""
    model = parse_pro7(data)
    n_slides = sum(len(g["slides"]) for g in model["groups"])
    if n_slides == 0:
        raise Pro7Error("檔案裡沒有任何投影片（可能是純媒體/音訊文件）")
    n_text = sum(1 for g in model["groups"] for s in g["slides"]
                 for e in s["elements"] if e["has_text"] and not e["hidden"])
    n_skip = sum(1 for g in model["groups"] for s in g["slides"]
                 for e in s["elements"]
                 if e["hidden"] or (not e["has_text"] and not e["media_url"]))
    n_empty = sum(1 for g in model["groups"] for s in g["slides"]
                  for e in s["elements"] if not e["hidden"] and e.get("is_empty"))
    n_bg = sum(1 for g in model["groups"] for s in g["slides"] if s.get("bg"))
    n_media_el = sum(1 for g in model["groups"] for s in g["slides"]
                     for e in s["elements"]
                     if not e["hidden"] and not e["has_text"] and e["media_url"])
    report = {
        "title":    model["title"] or model["ccli"]["title"],
        "width":    model["width"], "height": model["height"],
        "n_groups": len(model["groups"]), "n_slides": n_slides,
        "n_text":   n_text, "n_skipped": n_skip,
        "n_bg":     n_bg,   "n_media_el": n_media_el, "n_empty": n_empty,
        "groups":   [(g["name"] or "(無名)", len(g["slides"])) for g in model["groups"]],
    }
    return _doc_xml(model, path_map), report
