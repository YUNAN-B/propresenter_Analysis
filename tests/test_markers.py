"""[] 段落標記（創造・單欄）：辨識、別名映射、分段、多群組建檔。"""
import xml.etree.ElementTree as ET

SRC = "[主歌]\n一句\n二句\n[副歌]\n三句\n[x2]\n四句\n[間奏]\n[Chorus]\n五句"


def _ok(b):
    return b"/>" not in b and ET.fromstring(b.decode()) is not None


# ── 辨識與別名 ─────────────────────────────────────────────────
def test_scan_markers(app):
    assert app._scan_markers(SRC) == ["主歌", "副歌", "x2", "間奏", "Chorus"]
    assert app._scan_markers("沒有標記\n只有歌詞") == []
    # 行內 [..]（非整行）不算標記
    assert app._scan_markers("唱兩次 [x2] 再結束") == []

def test_marker_aliases(app):
    f = app._marker_to_group
    assert f("主歌") == "Verse" and f("V1") == "Verse" and f("Verse 1") == "Verse"
    assert f("主歌2") == "Verse 2" and f("v2") == "Verse 2"
    assert f("副歌") == "Chorus" and f("C") == "Chorus" and f("CHORUS") == "Chorus"
    assert f("Pre Chorus") == "Pre-Chorus" and f("導歌") == "Pre-Chorus"
    assert f("橋段") == "Bridge" and f("b") == "Bridge"
    assert f("標題") == "標題" and f("Title") == "標題"
    assert f("x2") is None and f("間奏") is None


# ── 分段 ───────────────────────────────────────────────────────
def test_split_sections(app):
    secs = app._split_marked_sections(SRC)
    assert [m for m, _ in secs] == ["主歌", "副歌", "x2", "間奏", "Chorus"]
    assert secs[0][1].strip() == "一句\n二句"
    assert secs[3][1].strip() == ""            # [間奏] 緊接 [Chorus]：空段

def test_split_leading_content_and_as_lyric(app):
    secs = app._split_marked_sections("開頭\n[主歌]\nA\n[x2]\nB", as_lyric={"x2"})
    assert secs[0][0] is None and secs[0][1].strip() == "開頭"
    assert secs[1][0] == "主歌" and secs[1][1].strip() == "A\n[x2]\nB"


# ── 建檔：多群組 .pro6 ─────────────────────────────────────────
def test_build_marked_groups(app):
    dec = {"主歌": "Verse", "副歌": "Chorus", "x2": "__lyric__",
           "間奏": "__literal__", "Chorus": "Chorus"}
    b = app._build_pro6_marked(SRC, dec)
    assert _ok(b)
    gs = ET.fromstring(b.decode()).findall(".//RVSlideGrouping")
    # [x2] 當歌詞併入副歌段；[間奏] 無內容被跳過
    assert [g.get("name") for g in gs] == ["Verse", "Chorus", "Chorus"]
    assert gs[0].get("color").startswith("0.231373")        # Verse #3B6FD4
    assert gs[1].get("color").startswith("0.815686")        # Chorus #D0021B
    # [x2] 保留在歌詞圖層裡
    _, pg = app._parse_xml(b)
    texts = ["".join(r.text for r in l["runs"])
             for g in pg for s in g["slides"] for l in s["layers"]]
    assert "[x2]" in texts

def test_build_literal_name_escaped(app):
    b = app._build_pro6_marked('[A&"B]\nx', {'A&"B': "__literal__"})
    assert _ok(b)
    assert ET.fromstring(b.decode()).find(".//RVSlideGrouping").get("name") == 'A&"B'

def test_build_plain_still_single_group(app):
    """無標記路徑（_build_pro6_structured）維持單一無名群組。"""
    b = app._build_pro6_structured("第一張\n\n第二張")
    gs = ET.fromstring(b.decode()).findall(".//RVSlideGrouping")
    assert len(gs) == 1 and gs[0].get("name") == ""


# ── 檔名推導 ───────────────────────────────────────────────────
def test_name_skips_marker_lines(app):
    assert app._name_from_text("[主歌]\n真正的第一句") == "真正的第一句"
