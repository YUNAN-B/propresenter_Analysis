"""RTF 解析/編碼/空白 的單元測試，外加逆寫回歸（原 test_writeback.py 併入）。"""
import base64, re
import xml.etree.ElementTree as ET


class R:
    """最小 run 替身：上述函式只讀 .text。"""
    def __init__(self, text): self.text = text


# ── _encode_run_text ────────────────────────────────────────────
def test_encode_ascii_literal(app):
    assert app._encode_run_text("freedom") == "freedom"

def test_encode_ascii_no_uc0(app):
    # 純 ASCII 不該加 \uc0（保持精簡 + byte 穩定）
    assert "\\uc0" not in app._encode_run_text("hello world")

def test_encode_newline_is_backslash_lf(app):
    assert app._encode_run_text("a\nb") == "a\\\nb"

def test_encode_brace_backslash_escaped(app):
    assert app._encode_run_text("{}\\") == "\\{\\}\\\\"

def test_encode_uc0_before_unicode(app):
    # 回歸：I've→I'e。非 ASCII 的 \uNNNN 前必須有 \uc0，否則 \uc1 區域會吃掉下一個字。
    out = app._encode_run_text("I’ve")          # ' = U+2019(8217)
    assert "\\uc0" in out
    assert out.index("\\uc0") < out.index("\\u8217")
    # 'v' 必須還在
    assert out.endswith("ve")


# ── parse_rtf ───────────────────────────────────────────────────
_SIMPLE = ("{\\rtf1\\ansi\\ansicpg950\\cocoartf2580\n{\\fonttbl\\f0\\fnil\\fcharset0 F;}\n"
           "{\\colortbl;\\red255\\green255\\blue255;}\n{\\*\\expandedcolortbl;;}\n"
           "\\pard\\pardirnatural\\partightenfactor0\n\\f0\\fs200 \\cf1 hello}")

def test_parse_rtf_plain(app):
    assert app.parse_rtf(_SIMPLE).plain() == "hello"

def test_parse_rtf_records_spans(app):
    runs = app.parse_rtf(_SIMPLE, keep_empty=True).runs
    assert len(runs) == 1 and runs[0].text == "hello"
    assert runs[0].text_token_spans, "應記錄文字 token 的來源 span"

def test_parse_rtf_internal_newline(app):
    rtf = _SIMPLE.replace("hello}", "a\\\nb}")        # a + 換行 + b
    assert app.parse_rtf(rtf).plain() == "a\nb"

def test_escaped_literals_roundtrip(app):
    # 回歸：{ } \ 跳脫後必須能讀回（曾經讀回變空字串）
    for s in ("{ \\ }", "C:\\path\\file", "a{b}c"):
        body = app._encode_run_text(s)
        rtf = _SIMPLE.replace("\\f0\\fs200 \\cf1 hello", "\\f0\\fs200 \\cf1 " + body)
        assert app.parse_rtf(rtf).plain() == s


# ── 整理空格：每行頭尾清乾淨 + 字中間多空白併一；換行保留 ──────────
def test_tidy_runs(app):
    out = "".join(app._tidy_runs([R("祖創  \n統管  一切 ")]))
    # 祖創  ↵統管  一切    →  祖創↵統管 一切（行頭尾清乾淨、字中間多空白併成一個）
    assert out == "祖創\n統管 一切"


# ── 撰寫頁：隱藏/補回段間換行 round-trip ────────────────────────
def test_display_compose_roundtrip(app):
    runs = [R("《\n"), R("shout\n"), R("》")]   # 《↵ / shout↵ / 》
    disp = app._run_display_texts(runs)
    assert disp == ["《", "shout", "》"]          # 段間換行隱藏
    real = app._compose_from_display(runs, disp)
    assert real == [r.text for r in runs]                  # 補回後完全還原


# ── 小工具 ──────────────────────────────────────────────────────
def test_rgba_hex(app):
    assert app._rgba_hex("1 1 1 1") == "#FFFFFF"
    assert app._rgba_hex("0 0 0 0") == "transparent"

def test_parse_pos(app):
    assert app._parse_pos("{5 100 0 1910 300}") == {"x":5,"y":100,"z":0,"w":1910,"h":300}


# ═══════════════════════════════════════════════════════════════
# 逆寫回歸（原 test_writeback.py 併入）
# ═══════════════════════════════════════════════════════════════
def _iter_text_layers(app, xb):
    _, gs = app._parse_xml(xb)
    for gi, g in enumerate(gs):
        for si, s in enumerate(g["slides"]):
            for l in s["layers"]:
                if l["type"] == "RVTextElement" and l["runs"]:
                    yield gi, si, l

def _decoded_rtfs(b):
    for m in re.findall(r'<NSString rvXMLIvarName="RTFData">([A-Za-z0-9+/=\s]+)</NSString>',
                        b.decode()):
        yield base64.b64decode(m.strip()).decode("utf-8", "replace")


# ── 無損序列化（原始檔逐字節不變）──────────────────────────────
def test_xml_to_bytes_lossless(app, sample):
    orig = sample.decode("utf-8")
    out = app._xml_to_bytes(ET.fromstring(orig), orig).decode("utf-8")
    assert out == orig

def test_no_self_closing_tags(app, sample):
    # 我們的輸出不該出現 <x/>（ProPresenter 相容）
    _, gs = app._parse_xml(sample)
    nb, _ = app._reverse_layers(sample)
    assert b"/>" not in nb


# ── 明文無改動儲存 → byte 不變 ─────────────────────────────────
def test_noop_save_byte_stable(app, sample):
    checked = 0
    for gi, si, l in _iter_text_layers(app, sample):
        rk = [r.text.replace("\n", "\\n") for r in l["runs"]]
        nb, err = app._apply_text_runs(sample, gi, si, l["idx"], rk)
        assert err is None
        assert nb == sample, f"未改動卻產生 byte 差異 @ G{gi}S{si}L{l['idx']}"
        checked += 1
    assert checked >= 5


# ── 編輯一段 → 只該段變、可解析 ────────────────────────────────
def test_edit_one_run(app, sample):
    gi, si, l = next(_iter_text_layers(app, sample))
    rk = [r.text.replace("\n", "\\n") for r in l["runs"]]
    rk[0] = "改過XYZ"
    nb, err = app._apply_text_runs(sample, gi, si, l["idx"], rk)
    assert err is None and nb != sample
    assert ET.fromstring(nb.decode()) is not None
    texts = ["".join(r.text for r in ll["runs"]) for _, _, ll in _iter_text_layers(app, nb)]
    assert any("改過XYZ" in t for t in texts)


# ── 清空一段 → 該段被刪 ────────────────────────────────────────
def test_empty_run_deletes_it(app, sample):
    # s5 多色：兩段，清空第二段
    target = None
    for gi, si, l in _iter_text_layers(app, sample):
        if len(l["runs"]) >= 2:
            target = (gi, si, l); break
    assert target, "fixture 應有多段圖層"
    gi, si, l = target
    rk = [r.text.replace("\n", "\\n") for r in l["runs"]]
    rk[-1] = ""
    nb, err = app._apply_text_runs(sample, gi, si, l["idx"], rk)
    assert err is None
    _, gs = app._parse_xml(nb)
    after = gs[gi]["slides"][si]["layers"][l["idx"]]["runs"]
    assert len(after) == len(l["runs"]) - 1


# ── \uc0 回歸：撇號重編後不該吃掉下一個字 ──────────────────────
def test_apostrophe_uc0_after_tidy(app, sample):
    nb, n = app._apply_tidy(sample)
    assert n >= 1
    # s2 的 "I've got freedom" 應完整，且 RTF 內 \u 之前有 \uc0
    hit = False
    for rtf in _decoded_rtfs(nb):
        plain = app.parse_rtf(rtf).plain()
        if "got" in plain and "freedom" in plain:
            hit = True
            assert "’ve" in plain and "’e " not in plain      # 'v' 沒被吃掉
            j = rtf.find("\\u8217")
            assert j > 0 and "\\uc0" in rtf[max(0, j-12):j]    # 舗 前有 \uc0
    assert hit, "找不到 s2 的撇號文字"


# ── 匯出去重 ────────────────────────────────────────────────────
def test_dedup_uuids(app, sample):
    def dup_count(b):
        u = re.findall(r'\sUUID="([^"]+)"', b.decode())
        from collections import Counter
        return sum(v - 1 for v in Counter(u).values() if v > 1)
    assert dup_count(sample) == 1            # fixture 故意放一組重複 "DUP"
    nb, n = app._dedup_uuids(sample)
    assert n == 1 and dup_count(nb) == 0
