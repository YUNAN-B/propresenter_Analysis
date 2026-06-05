"""模板動作的整合測試（對合成 fixture 套用）。"""
import re
import xml.etree.ElementTree as ET


def _ok(b):
    return b"/>" not in b and ET.fromstring(b.decode()) is not None

def _layers(app, b):
    """回傳每張投影片的文字圖層 [(slide_num, label, [(idx,y,text,colors)...])]。"""
    _, gs = app._parse_xml(b)
    res = []
    for g in gs:
        for s in g["slides"]:
            tl = [(l["idx"], l["pos"]["y"], "".join(r.text for r in l["runs"]),
                   [r.color_hex for r in l["runs"]])
                  for l in s["layers"] if l["type"] == "RVTextElement"]
            res.append((s["num"], s["label"], tl))
    return res


# ── 統整 ────────────────────────────────────────────────────────
def test_prune_empty_layers(app, sample):
    nb, n = app._prune_empty_layers(sample)
    assert n == 2 and _ok(nb)                     # s3 的空圖層 + placeholder
    # s3 應再無文字圖層
    s3 = [tl for num, lab, tl in _layers(app, nb) if lab == "empties"][0]
    assert s3 == []

def test_prune_slides(app, sample):
    nb, n = app._delete_empty_slides(sample, keep_bg=True)
    assert n == 1 and _ok(nb)                     # s4 無圖層
    assert "no-layers" not in [lab for _, lab, _ in _layers(app, nb)]

def test_tidy_run(app, sample):
    nb, n = app._apply_tidy(sample)
    assert n >= 1 and _ok(nb)
    # 顏色保留：s5 多色仍是兩色
    s5 = [tl for num, lab, tl in _layers(app, nb) if lab == "multicolor"][0]
    assert len(s5[0][3]) == 2


# ── 轉換 ────────────────────────────────────────────────────────
def test_tc2sc_and_reverse(app, sample):
    nb, n, errs = app._apply_tc2sc(sample, reverse=False)
    assert n >= 1 and not errs and _ok(nb)
    allt = " ".join(t for _, _, tl in _layers(app, nb) for _, _, t, _ in tl)
    assert "赞" in allt and "讚" not in allt        # 讚→赞
    # 反向轉回：簡體 赞 應被轉回繁體（opencc 可能正規化成 讚 或 贊，故只檢查簡體消失）
    back, _, _ = app._apply_tc2sc(nb, reverse=True)
    allt2 = " ".join(t for _, _, tl in _layers(app, back) for _, _, t, _ in tl)
    assert "赞" not in allt2 and ("讚" in allt2 or "贊" in allt2)

def test_pinyin_detect_multiline(app, sample):
    assert app._pinyin_has_multiline(sample) is True   # s1 中文含換行

def test_pinyin_single_line(app, sample):
    nb, n, eng = app._apply_pinyin(sample, mi_to_ni=True, keep_breaks=False)
    assert eng == "pypinyin" and n >= 1 and _ok(nb)
    s1 = [tl for num, lab, tl in _layers(app, nb) if lab == "bilingual"][0]
    # 第二層（idx 1）變成第一層中文的拼音（單行、無聲調）
    second = [t for idx, y, t, c in s1 if idx == 1][0]
    assert second == "zan mei zhu ha li lu ya"

def test_pinyin_keep_breaks(app, sample):
    nb, n, eng = app._apply_pinyin(sample, mi_to_ni=True, keep_breaks=True)
    s1 = [tl for num, lab, tl in _layers(app, nb) if lab == "bilingual"][0]
    second = [t for idx, y, t, c in s1 if idx == 1][0]
    assert second == "zan mei zhu\nha li lu ya"        # 跟隨中文換行


# ── 操作 ────────────────────────────────────────────────────────
def test_reverse_layers(app, sample):
    before = [tl for num, lab, tl in _layers(app, sample) if lab == "bilingual"][0]
    nb, n = app._reverse_layers(sample)
    after = [tl for num, lab, tl in _layers(app, nb) if lab == "bilingual"][0]
    assert n >= 1 and _ok(nb)
    # 文字順序前後顛倒
    assert [t for _, _, t, _ in before] == list(reversed([t for _, _, t, _ in after]))

def test_split_layer_lines(app, sample):
    nb, n = app._split_layer_lines(sample)
    assert n >= 1 and _ok(nb)
    s1 = [tl for num, lab, tl in _layers(app, nb) if lab == "bilingual"][0]
    texts = [t for _, _, t, _ in s1]
    assert "讚美主" in texts and "哈利路亞" in texts   # 兩行各成一層
    # 後拆出的那層 y 較大（略低）
    ys = {t: y for _, y, t, _ in s1}
    assert ys["哈利路亞"] > ys["讚美主"]

def test_apply_style(app):
    assert len(app._STYLES) >= 1                      # styles.json 有載入
    doc = app._build_pro6_bilingual("中一\n中二", "En1\nEn2")   # 2 層雙語
    nb, n = app._apply_style(doc, "單句中英")
    assert n == 4 and _ok(nb)                          # 2 張×2 層
    texts = [t for _, _, tl in _layers(app, nb) for _, _, t, _ in tl]
    assert "中一" in texts and "En1" in texts           # 文字保留
    # 套用後第一張兩層的 y 位置應換成樣式的（955/1030），非原本的 0/540
    s1 = _layers(app, nb)[0][2]
    ys = sorted(y for _, y, _, _ in s1)
    assert ys == [955, 1030]

def test_created_pro6_has_required_structure(app):
    """產生的 .pro6 必須帶齊 ProPresenter 必要屬性/元素，否則它會 deserialize 失敗
    或 NSPathStore nil。守住結構完整性。"""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(app._build_pro6_bilingual("甲\n乙", "A\nB").decode())
    # 路徑類屬性必須「存在」（即使空字串），缺了就會 NSPathStore nil
    for k in ("resourcesDirectory", "chordChartPath"):
        assert k in root.attrib
    assert root.find('RVTimeline[@rvXMLIvarName="timeline"]') is not None
    sl = root.find('.//RVDisplaySlide')
    assert "chordChartPath" in sl.attrib and "drawingBackgroundColor" in sl.attrib
    te = root.find('.//RVTextElement')
    for k in ("source", "typeID", "bezelRadius", "displayDelay", "revealType"):
        assert k in te.attrib, f"TextElement 缺 {k}"
    assert te.find('shadow[@rvXMLIvarName="shadow"]') is not None
    assert te.find('dictionary[@rvXMLIvarName="stroke"]') is not None

def test_whitespace_unicode(app):
    from types import SimpleNamespace as NS
    # 含 thin(U+2009)/全形/NBSP/零寬(U+200B) 等各種 Unicode 空白
    runs = [NS(text="   主啊　  \n\xa0敬拜​ ")]
    # 整理空格：行頭尾各種空白都清乾淨、換行保留
    assert app._tidy_runs(runs)[0] == "主啊\n敬拜"

def test_tidy_drop_single_nl(app):
    from types import SimpleNamespace as NS
    def tidy(s): return app._tidy_runs([NS(text=s)], drop_nl=True)[0]
    assert tidy("主\n愛我") == "主 愛我"                    # 中文單換行 → 補空格接成一行
    assert tidy("Love\nyou") == "Love you"                # 英文同樣補空格
    assert tidy("第一段\n\n第二段") == "第一段\n\n第二段"   # 空行(段落)保留
    assert tidy("A\nB\n\nC\nD") == "A B\n\nC D"           # 混合：單換行黏、空行留
    assert tidy("行一  \n  行二") == "行一 行二"            # 換行兩側多餘空白一併整理
    # drop_nl=False 維持原本：不動換行
    assert app._tidy_runs([NS(text="主\n愛我")])[0] == "主\n愛我"

def test_merge_runs_no_gap(app, sample):
    # 合併「因格式不同而切開的 run」：交界不留空格、不留換行；run 內部換行保留
    from types import SimpleNamespace as NS
    j = app._merge_runs_plain
    assert j([NS(text="紅"), NS(text="\n藍")]) == "紅藍"                # 交界換行去掉
    assert j([NS(text="主啊 "), NS(text="\n敬拜")]) == "主啊敬拜"        # 交界空格＋換行都去
    assert j([NS(text="主啊"), NS(text="\n　敬拜")]) == "主啊敬拜"        # 全形空格也去
    assert j([NS(text="紅\n\n"), NS(text="藍")]) == "紅藍"             # 交界雙換行也清乾淨
    assert j([NS(text="A\nB"), NS(text="\nC")]) == "A\nBC"            # run 內部換行保留
    # 端對端：fixture 的 multicolor（紅 cf1 / 藍 cf2 兩 run）併成單段「紅藍」、無間隔
    nb, n = app._merge_layer_runs(sample)
    assert _ok(nb) and n >= 1
    mc = [tl for num, lab, tl in _layers(app, nb) if lab == "multicolor"][0]
    assert len(mc) == 1 and mc[0][2] == "紅藍"

def test_build_pro6_bilingual(app):
    nb = app._build_pro6_bilingual("讚美主\n哈利路亞", "Praise\nHallelu")
    assert _ok(nb)
    rows = _layers(app, nb)
    assert len(rows) == 2                                     # 兩行→兩張
    # 每張兩個圖層：上排(左欄, y 較小)＝中文、下排(右欄, y 較大)＝英文
    s1 = rows[0][2]
    s1 = sorted(s1, key=lambda r: r[1])                       # 依 y 排序
    assert "讚美主" in s1[0][2] and "Praise" in s1[1][2]
    assert s1[0][1] < s1[1][1]                                # 中文在上、英文在下
    # 行數不等→以較小者為準
    nb2 = app._build_pro6_bilingual("a\nb\nc", "x\ny")
    assert len(_layers(app, nb2)) == 2

def test_build_pro6_single_blank_paging(app):
    nb = app._build_pro6_structured("行一\n行二\n\n第二段", "空行", "空行")
    assert _ok(nb)
    rows = _layers(app, nb)
    assert len(rows) == 2 and rows[0][2][0][2] == "行一\n行二"  # 空行分頁、段內換行保留

def test_split_layers_to_slides(app):
    # 創造出「1 張、多個單行圖層」（無空行、換行換圖層）→ 應能拆成多張
    doc = app._build_pro6_structured("標題\n第一句\n第二句\n第三句", "空行", "換行")
    assert len(_layers(app, doc)) == 1                  # 先是 1 張
    nb, n = app._split_layers_to_slides(doc)
    assert n == 3 and _ok(nb)                           # 4 層 → 4 張（+3）
    rows = _layers(app, nb)
    assert len(rows) == 4
    for _, _, tl in rows:
        assert len(tl) == 1                             # 每張只剩一個文字層
        assert tl[0][1] == 0                            # y=0（全幅置中）

def test_split_slide_lines(app, sample):
    before = _layers(app, sample)
    n_before = len(before)
    nb, n = app._split_slide_lines(sample)
    assert n >= 1 and _ok(nb)
    after = _layers(app, nb)
    assert len(after) > n_before                       # 投影片變多
    # 雙語頁（zh 2 行 + en 1 行）→ 第一張同時有 zh 行0 與 en 行0，第二張只有 zh 行1
    texts = [t for _, _, tl in after for _, _, t, _ in tl]
    assert "讚美主" in texts and "哈利路亞" in texts
    # 「讚美主」與「哈利路亞」應落在不同投影片
    s_of = {}
    for num, lab, tl in after:
        for _, _, t, _ in tl:
            s_of.setdefault(t, num)
    assert s_of.get("讚美主") != s_of.get("哈利路亞")

def test_add_layer_all(app, sample):
    before = sum(len(tl) for _, _, tl in _layers(app, sample))
    nb, n = app._add_layer_all(sample)
    assert n == 7 and _ok(nb)                          # 7 張各加一層
    allt = [t for _, _, tl in _layers(app, nb) for _, _, t, _ in tl]
    assert allt.count("-") == 7
