"""pro7.py（Pro7 .pro → .pro6 轉換）測試。

合成 fixture：用極簡 protobuf「編碼器」手刻一份 .pro（無版權內容），
涵蓋：群組順序（cue_groups 為準、cues 儲存順序刻意打亂）、雙文字圖層、
中文 RTF 原封搬運、熱鍵、標籤、CCLI、未入組 cue、媒體(無文字)元素略過。
另有真實檔煙霧測試（repo 根目錄的 02.*.pro，存在才跑）。
"""
import base64
import glob
import os
import struct
import sys
import xml.etree.ElementTree as ET

import pytest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import pro7


# ── 極簡 protobuf 編碼器（測試專用）─────────────────────────────
def _vi(n):
    out = b""
    while True:
        b = n & 0x7F; n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n: return out

def _tag(f, wt): return _vi((f << 3) | wt)
def _len(f, payload): return _tag(f, 2) + _vi(len(payload)) + payload
def _str(f, s): return _len(f, s.encode("utf-8"))
def _int(f, n): return _tag(f, 0) + _vi(n)
def _dbl(f, x): return _tag(f, 1) + struct.pack("<d", x)
def _flt(f, x): return _tag(f, 5) + struct.pack("<f", x)
def _uuid(f, s): return _len(f, _str(1, s))

_RTF = ("{\\rtf1\\ansi\\ansicpg950\\cocoartf2821\n"
        "{\\fonttbl\\f0\\fnil\\fcharset0 PingFangTC-Medium;}\n"
        "{\\colortbl;\\red255\\green255\\blue255;}\n"
        "\\pard\\pardirnatural\\qc\\partightenfactor0\n"
        "\\f0\\fs130 \\cf1 \\uc0\\u35406 \\u32654 \\u20027 }")     # 「诶美主」→ 讚美主

def _text_el(uuid_s, name, x, y, w, h, rtf=_RTF, valign=1):
    text = _len(5, rtf.encode("utf-8")) + _int(6, valign)
    bounds = _len(1, _dbl(1, x) + _dbl(2, y)) + _len(2, _dbl(1, w) + _dbl(2, h))
    g_el = _uuid(1, uuid_s) + _str(2, name) + _len(3, bounds) + _dbl(5, 1.0) + _len(13, text)
    return _len(1, g_el)          # Slide.Element{ element=1(Graphics.Element) }

def _media_el():                  # 無 text 的元素（模擬圖片/形狀）→ 應被略過
    g_el = _uuid(1, "MEDIA-EL") + _str(2, "圖片")
    return _len(1, g_el)

def _slide(uuid_s, elements, w=1920, h=1080):
    # Slide{ elements=1(repeated Slide.Element), size=6, uuid=7 }
    base = (b"".join(_len(1, e) for e in elements)
            + _len(6, _dbl(1, w) + _dbl(2, h)) + _uuid(7, uuid_s))
    pres = _len(1, base)          # PresentationSlide{ base_slide=1 }
    return pres

def _cue(uuid_s, pres, label="", hotkey_code=0, cue_name=""):
    action = _len(23, _len(2, pres)) + _int(9, 11)          # slide=23{presentation=2}, type=11
    if label: action = _len(3, _str(2, label)) + action     # Action.Label.text
    c = _uuid(1, uuid_s)
    if cue_name: c += _str(2, cue_name)
    if hotkey_code: c += _len(8, _int(1, hotkey_code))
    c += _len(10, action) + _int(12, 1)
    return c

def _group(name, rgba, cue_ids):
    g = _uuid(1, "G-" + name) + _str(2, name) + _len(
        3, _flt(1, rgba[0]) + _flt(2, rgba[1]) + _flt(3, rgba[2]) + _flt(4, rgba[3]))
    cg = _len(1, g) + b"".join(_uuid(2, u) for u in cue_ids)
    return cg

@pytest.fixture(scope="module")
def synth_pro():
    """兩組（Verse 藍、Chorus 紅）各 1 張＋1 張未入組；cues 欄位刻意倒序儲存。"""
    s1 = _cue("CUE-1", _slide("SL-1", [
        _text_el("EL-1", "中文", 0, 0, 1920, 540),
        _text_el("EL-2", "英文", 0, 540, 1920, 540),
    ]), label="第一張", hotkey_code=1)                        # hotkey A
    s2 = _cue("CUE-2", _slide("SL-2", [_text_el("EL-3", "中文", 0, 0, 1920, 1080),
                                       _media_el()]))
    s3 = _cue("CUE-3", _slide("SL-3", [_text_el("EL-4", "中文", 0, 0, 1920, 1080)]))
    ccli = _str(1, "作者甲") + _str(3, "測試歌") + _str(4, "出版乙") + _int(5, 2024)
    doc = (_len(1, _int(1, 1))                     # application_info（讓檔案以 0x0A 開頭）
           + _str(3, "《合成測試》")
           + _len(12, _group("Verse", (0.2, 0.4, 0.9, 1.0), ["CUE-1"]))
           + _len(12, _group("Chorus", (0.9, 0.1, 0.1, 1.0), ["CUE-2"]))
           # cues 儲存順序刻意打亂：3,2,1——正確輸出仍須是 1,2,3
           + _len(13, s3) + _len(13, s2) + _len(13, s1)
           + _len(14, ccli))
    return doc


def test_is_pro7(synth_pro, sample):
    assert pro7.is_pro7(synth_pro, "x.pro")
    assert pro7.is_pro7(synth_pro, "")                # magic 0x0A
    assert not pro7.is_pro7(sample, "sample.pro6")    # pro6 XML
    assert not pro7.is_pro7(b"<xml/>", "a.pro6")

def test_parse_model(synth_pro):
    m = pro7.parse_pro7(synth_pro)
    assert m["title"] == "《合成測試》"
    assert m["width"] == 1920 and m["height"] == 1080
    # 群組順序＝cue_groups 順序，未入組的墊底
    assert [g["name"] for g in m["groups"]] == ["Verse", "Chorus", ""]
    assert [len(g["slides"]) for g in m["groups"]] == [1, 1, 1]
    v = m["groups"][0]["slides"][0]
    assert v["label"] == "第一張" and v["hotkey"] == "A"
    assert len(v["elements"]) == 2 and all(e["has_text"] for e in v["elements"])
    # Chorus 那張的媒體元素沒有文字
    ch = m["groups"][1]["slides"][0]
    assert [e["has_text"] for e in ch["elements"]] == [True, False]

def test_convert_to_valid_pro6(app, synth_pro):
    nb, rep = pro7.pro7_to_pro6(synth_pro)
    assert rep["n_groups"] == 3 and rep["n_slides"] == 3
    assert rep["n_text"] == 4 and rep["n_skipped"] == 1
    root = ET.fromstring(nb.decode("utf-8"))          # 合法 XML
    assert root.tag == "RVPresentationDocument"
    assert root.get("CCLISongTitle") == "《合成測試》"
    assert root.get("CCLIAuthor") == "作者甲"
    assert root.get("width") == "1920"
    gs = root.find('.//array[@rvXMLIvarName="groups"]').findall("RVSlideGrouping")
    assert [g.get("name") for g in gs] == ["Verse", "Chorus", ""]
    assert gs[0].get("color").startswith("0.2")
    # 第一張：標籤、熱鍵、兩個文字層、位置
    s1 = gs[0].find(".//RVDisplaySlide")
    assert s1.get("label") == "第一張" and s1.get("hotKey") == "A"
    tls = s1.findall(".//RVTextElement")
    assert len(tls) == 2
    assert tls[1].find("RVRect3D").text == "{0 540 0 1920 540}"
    # RTF 原封搬運：解出的明文＝原字
    rtf = base64.b64decode(tls[0].find('NSString[@rvXMLIvarName="RTFData"]').text)
    assert rtf.decode("utf-8") == _RTF
    plain = app.parse_rtf(rtf.decode("utf-8")).plain()
    assert [ord(c) for c in plain.strip()] == [35406, 32654, 20027]   # 㕀6㉥4 7
    # 媒體元素不產生文字層
    s2 = gs[1].find(".//RVDisplaySlide")
    assert len(s2.findall(".//RVTextElement")) == 1

def test_app_pipeline_on_converted(app, synth_pro):
    """轉換結果要能走完 ProParse 全管線：_parse_xml、解析頁排版、匯出。"""
    nb, _ = pro7.pro7_to_pro6(synth_pro)
    meta, groups = app._parse_xml(nb)
    assert meta["width"] == 1920
    assert sum(len(g["slides"]) for g in groups) == 3
    # 每個文字層都有明文
    full = [l["full"] for g in groups for s in g["slides"] for l in s["layers"]
            if l["type"] == "RVTextElement"]
    assert len(full) == 4 and all(f.strip() for f in full)
    out, n = app._dedup_uuids(nb)                     # 匯出路徑
    ET.fromstring(out.decode("utf-8"))

def test_bad_input():
    with pytest.raises(pro7.Pro7Error):
        pro7.pro7_to_pro6(b"\x0a\x03abc")             # 可解但無 cues → 無投影片
    with pytest.raises(pro7.Pro7Error):
        pro7.parse_pro7(b"\xff\xff\xff")              # 壞 protobuf


def test_load_new_doc_autoconverts(app, synth_pro):
    """app._load_new_doc 收到 .pro 時要自動轉檔載入（檔名改 .pro6、留下來源註記）。"""
    ss = app.st.session_state
    ss.clear()
    app._load_new_doc(synth_pro, "測試.pro")
    assert ss["filename"] == "測試.pro6"
    assert ss["_fk"] == ("測試.pro", len(synth_pro))      # _fk 用原始大小（比對 uploader）
    assert "_src_note" in ss and "3 張" in ss["_src_note"]
    ET.fromstring(ss["xml_content"].decode("utf-8"))      # 已是合法 pro6 XML
    # 壞檔：不載入、留錯誤訊息
    ss.clear()
    app._load_new_doc(b"\x0a\x02\x08\x01", "壞檔.pro")
    assert "xml_content" not in ss and "_pro7_err" in ss


_REAL = sorted(glob.glob(os.path.join(_ROOT, "*.pro")))

@pytest.mark.skipif(not _REAL, reason="repo 根目錄沒有真實 .pro 檔")
def test_real_file_smoke(app):
    raw = open(_REAL[0], "rb").read()
    nb, rep = pro7.pro7_to_pro6(raw)
    assert rep["n_slides"] > 0 and rep["n_text"] > 0
    meta, groups = app._parse_xml(nb)
    plains = [l["full"] for g in groups for s in g["slides"] for l in s["layers"]
              if l["type"] == "RVTextElement"]
    assert plains and any(p.strip() for p in plains)
