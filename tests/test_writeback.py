"""逆寫相關回歸：無損序列化、byte 穩定、明文編輯、\\uc0、去重。"""
import base64, re
import xml.etree.ElementTree as ET


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
