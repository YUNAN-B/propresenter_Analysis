"""搜尋取代（_find_replace）、投影片移動（_move_slide）、視覺預覽
（_render_preview_html）的測試。文件皆用 app 的「創造」builder 合成。"""
import xml.etree.ElementTree as ET

import pytest


def _texts(app, xb):
    """依文件順序取出每張投影片的（首文字層）明文。"""
    _, gs = app._parse_xml(xb)
    return [l["full"] for g in gs for s in g["slides"] for l in s["layers"]
            if l["type"] == "RVTextElement"]


# ── 搜尋取代 ────────────────────────────────────────────────────
def test_find_replace_literal(app):
    xb = app._build_pro6_structured("哈利路亞\n\n讚美主")
    nb, n, err = app._find_replace(xb, "主", "耶穌")
    assert err is None and n == 1
    assert _texts(app, nb) == ["哈利路亞", "讚美耶穌"]

def test_find_replace_literal_is_not_regex(app):
    xb = app._build_pro6_structured("1+1")
    nb, n, err = app._find_replace(xb, "1+1", "2")     # 「+」按字面比對
    assert err is None and n == 1 and _texts(app, nb) == ["2"]

def test_find_replace_regex(app):
    xb = app._build_pro6_structured("第1張\n\n第22張")
    nb, n, err = app._find_replace(xb, r"第(\d+)張", r"No.\1", use_regex=True)
    assert err is None and n == 2
    assert _texts(app, nb) == ["No.1", "No.22"]

def test_find_replace_errors(app):
    xb = app._build_pro6_structured("內容")
    _, n, err = app._find_replace(xb, "", "x")
    assert err and n == 0
    _, n, err = app._find_replace(xb, "[壞", "x", use_regex=True)
    assert err and "正則" in err
    nb, n, err = app._find_replace(xb, "找不到", "x")
    assert err is None and n == 0 and nb == xb or n == 0   # 無符合＝0 處


# ── 投影片移動 ──────────────────────────────────────────────────
def _two_group_doc(app):
    """A 組（一）＋ B 組（二、三）。"""
    sl = lambda t: app._slide_element([app._text_element(t, 0, 0, 1920, 1080)])
    return app._doc_wrapper_groups([
        ("A", "0 0 0 0", [sl("一")]),
        ("B", "0 0 0 0", [sl("二"), sl("三")]),
    ])

def test_move_within_group(app):
    xb = _two_group_doc(app)
    nb, err = app._move_slide(xb, 3, -1)               # 三上移（B 組內）
    assert err is None and _texts(app, nb) == ["一", "三", "二"]
    nb2, err = app._move_slide(nb, 2, 1)               # 再移回去
    assert err is None and _texts(app, nb2) == ["一", "二", "三"]

def test_move_across_group(app):
    xb = _two_group_doc(app)
    nb, err = app._move_slide(xb, 2, -1)               # 二上移 → 進 A 組、排在一之前
    assert err is None and _texts(app, nb) == ["二", "一", "三"]
    root = ET.fromstring(nb.decode("utf-8"))
    gs = root.find('.//array[@rvXMLIvarName="groups"]').findall("RVSlideGrouping")
    assert [len(g.find('array[@rvXMLIvarName="slides"]')) for g in gs] == [2, 1]

def test_move_empties_group(app):
    xb = _two_group_doc(app)
    nb, err = app._move_slide(xb, 1, 1)                # 一下移 → A 組空 → A 組移除
    assert err is None and _texts(app, nb) == ["二", "一", "三"]
    root = ET.fromstring(nb.decode("utf-8"))
    gs = root.find('.//array[@rvXMLIvarName="groups"]').findall("RVSlideGrouping")
    assert [g.get("name") for g in gs] == ["B"]

def test_move_boundary(app):
    xb = _two_group_doc(app)
    _, err = app._move_slide(xb, 1, -1)
    assert err
    _, err = app._move_slide(xb, 3, 1)
    assert err


# ── 視覺預覽 ────────────────────────────────────────────────────
def test_preview_html(app):
    xb = app._build_pro6_structured("預覽文字")
    html = app._render_preview_html(xb)
    assert "pv-canvas" in html and "預覽文字" in html
    assert "font-size" in html and "#FFFFFF" in html   # 創造預設白字
    # HTML 跳脫
    xb2 = app._build_pro6_structured("a<b&c")
    assert "a&lt;b&amp;c" in app._render_preview_html(xb2)


# ── 轉換分頁：zip 收集 ──────────────────────────────────────────
def test_collect_pro_files_zip(app):
    import io, zipfile
    class FakeUp:
        def __init__(self, name, data): self.name=name; self._d=data
        def getvalue(self): return self._d
    zbuf=io.BytesIO()
    with zipfile.ZipFile(zbuf,"w") as zf:
        zf.writestr("歌曲A.pro", b"\x0a\x01x")
        zf.writestr("sub/歌曲B.pro", b"\x0a\x01y")
        zf.writestr("__MACOSX/._歌曲A.pro", b"junk")
        zf.writestr("讀我.txt", b"skip")
    got=app._collect_pro_files([FakeUp("包.zip", zbuf.getvalue()),
                                FakeUp("單檔.pro", b"\x0a\x01z")])
    assert [(n, d) for n, d in got] == [("歌曲A", b"\x0a\x01x"),
                                        ("歌曲B", b"\x0a\x01y"),
                                        ("單檔", b"\x0a\x01z")]
