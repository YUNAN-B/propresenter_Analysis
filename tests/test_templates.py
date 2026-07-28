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

def test_add_layer_all(app, sample):
    nb, n = app._add_layer_all(sample)
    assert n == 7 and _ok(nb)                          # 7 張各加一層
    allt = [t for _, _, tl in _layers(app, nb) for _, _, t, _ in tl]
    assert allt.count("-") == 7

def test_del_last_layer(app):
    # 一張三層 → 刪掉最後一層剩兩層
    doc = app._build_pro6_structured("甲\n乙\n丙", "空行", "換行")
    assert len(_layers(app, doc)[0][2]) == 3
    nb, n = app._del_last_layer(doc)
    assert n == 1 and _ok(nb)
    assert len(_layers(app, nb)[0][2]) == 2

def test_bulk_fill_overwrite(app):
    doc = app._build_pro6_bilingual("中一\n中二", "En1\nEn2")   # 2 張、各 2 文字層
    nb, n, err = app._bulk_fill_lines(doc, ["新一", "新二"], 1)
    assert err is None and n == 2 and _ok(nb)
    rows = _layers(app, nb)                            # 第 1 個文字圖層被覆蓋
    assert rows[0][2][0][2] == "新一" and rows[1][2][0][2] == "新二"

def test_bulk_fill_new_layer(app):
    doc = app._build_pro6_bilingual("中一\n中二", "En1\nEn2")   # 各 2 層；超過＝填 3
    before = len(_layers(app, doc)[0][2])
    nb, n, err = app._bulk_fill_lines(doc, ["尾一", "尾二"], 3)
    assert err is None and n == 2 and _ok(nb)
    rows = _layers(app, nb)
    assert len(rows[0][2]) == before + 1              # 末端多一層
    texts0 = [t for _, _, t, _ in rows[0][2]]
    assert "尾一" in texts0 and "中一" in texts0         # 新增放尾、原文保留

def test_bulk_fill_count_mismatch(app):
    doc = app._build_pro6_bilingual("中一\n中二", "En1\nEn2")   # 2 頁
    nb, n, err = app._bulk_fill_lines(doc, ["只有一行"], 1)
    assert err is not None and n == 0 and nb is doc    # 行數不符 → 不動

def test_wrap_title_marks(app):
    doc = app._build_pro6_structured("標題行", "空行", "換行")   # 1 張 1 層
    nb, n = app._wrap_title_marks(doc)
    assert n == 1 and _ok(nb)
    assert _layers(app, nb)[0][2][0][2] == "《標題行》"
    nb2, n2 = app._wrap_title_marks(nb)                # 冪等：已包則不動
    assert n2 == 0 and nb2 is nb

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

def test_merge_runs_keep_lines(app, sample):
    # 合併「因格式不同而切開的 run」：統一樣式，同樣式換行保留、只去行首尾空白
    from types import SimpleNamespace as NS
    j = app._merge_runs_plain
    # 無樣式 stub＝同樣式 → 換行全保留（本來就要的斷行）
    assert j([NS(text="主啊 "), NS(text="\n敬拜")]) == "主啊\n敬拜"       # 行尾空格去掉、換行留
    assert j([NS(text="主啊"), NS(text="\n　敬拜")]) == "主啊\n敬拜"       # 行首全形空格也去
    assert j([NS(text="A\nB"), NS(text="\nC")]) == "A\nB\nC"           # 多行全保留
    assert j([NS(text="第一行\n第二行\n第三行")]) == "第一行\n第二行\n第三行"  # 不會被併成一行
    # 端對端：fixture multicolor（紅 cf1 / 藍 cf2，邊界 1 換行＝樣式切換多的）→ 併成一行「紅藍」
    nb, n = app._merge_layer_runs(sample)
    assert _ok(nb) and n >= 1
    mc = [tl for num, lab, tl in _layers(app, nb) if lab == "multicolor"][0]
    assert len(mc) == 1 and mc[0][2] == "紅藍"

def test_drop_style_break_nl(app):
    # 「換樣式時多插的換行」規則：樣式邊界換行扣一個、同樣式換行全保留
    TR = app.TextRun
    def r(text, font="A", color="#FFF"):
        return TR(text, font, 100.0, color, False, False, False, [])
    d = app._drop_style_break_nl
    # 不同樣式、邊界 1 換行 → 接成同一行（換行是樣式切換多的）
    assert d([r("I\n", "F1"), r("’\n", "F2"), r("m clean", "F1")]) == "I’m clean"
    # 不同樣式、邊界 2 換行 → 留 1 個（一個原本要的、一個段落多的）
    assert d([r("中文\n\n", "F1"), r("English", "F2")]) == "中文\nEnglish"
    # 不同樣式、邊界 3 換行（中間夾純換行段）→ 留 2 個（保留空行）
    assert d([r("clean \n", "F1"), r("\n\n", "F3"), r("曾", "F2")]) == "clean \n\n曾"
    # 同樣式之間的換行（含空行）全部保留
    assert d([r("第一行\n第二行")]) == "第一行\n第二行"
    assert d([r("A\n\nB")]) == "A\n\nB"
    # 顏色不同也算換樣式
    assert d([r("紅", color="#F00"), r("\n藍", color="#00F")]) == "紅藍"

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

# ── 撰寫頁：段落類型（group）與熱鍵 ────────────────────────────────
def _groups(app, b):
    """回傳 [(group名, 張數)...]，依文件順序。"""
    root = ET.fromstring(b.decode())
    out = []
    for g in root.find('.//array[@rvXMLIvarName="groups"]').findall("RVSlideGrouping"):
        sl = g.find('array[@rvXMLIvarName="slides"]')
        out.append((g.get("name"), len(list(sl)) if sl is not None else 0))
    return out

def _deck6(app):
    return app._build_pro6_structured("\n\n".join(f"S{i}" for i in range(1, 7)),
                                      "空行", "空行")  # 1 組、6 張

def test_group_fill_split(app):
    b = _deck6(app)
    assert _groups(app, b) == [("", 6)]
    b, _ = app._set_group_fill(b, 1, "Verse", "#3B6FD4")
    assert _groups(app, b) == [("Verse", 6)]                 # 第一張 → 整組
    b, _ = app._set_group_fill(b, 4, "Chorus", "#D0021B")
    assert _groups(app, b) == [("Verse", 3), ("Chorus", 3)]  # 從第4張切開
    b, _ = app._set_group_fill(b, 2, "Pre-Chorus", "#F5C518")
    assert _groups(app, b) == [("Verse", 1), ("Pre-Chorus", 2), ("Chorus", 3)]
    assert _ok(b) and sum(n for _, n in _groups(app, b)) == 6  # 張數守恆

def test_group_fill_merge_adjacent(app):
    b = _deck6(app)
    b, _ = app._set_group_fill(b, 4, "Chorus", "#D0021B")
    b, _ = app._set_group_fill(b, 1, "Chorus", "#D0021B")    # 全變 Chorus
    assert _groups(app, b) == [("Chorus", 6)]                # 相鄰同類型合併

def test_group_color_written(app):
    b = _deck6(app)
    b, _ = app._set_group_fill(b, 1, "Chorus", "#D0021B")
    root = ET.fromstring(b.decode())
    col = root.find('.//RVSlideGrouping').get("color")
    r, g, bl, a = (float(x) for x in col.split())
    assert abs(r - 0xD0/255) < 1e-4 and abs(g - 0x02/255) < 1e-4 and a == 1.0

def test_hotkey_set_and_overwrite(app):
    b = app._build_pro6_structured("A\n\nB\n\nC", "空行", "空行")
    b, _ = app._set_slide_hotkey(b, 1, "C")
    assert app._hotkey_owner(b, "C") == 1
    b, _ = app._set_slide_hotkey(b, 3, "C")                  # 重複 → 從第1張移走
    assert app._hotkey_owner(b, "C") == 3
    root = ET.fromstring(b.decode())
    hks = [s.get("hotKey", "") for *_, s, _n in app._iter_slides_global(root)]
    assert hks == ["", "", "C"] and _ok(b)

def test_hotkey_clear(app):
    b = app._build_pro6_structured("A\n\nB", "空行", "空行")
    b, _ = app._set_slide_hotkey(b, 1, "X")
    b, _ = app._set_slide_hotkey(b, 1, "")                   # 清空
    assert app._hotkey_owner(b, "X") is None

def test_normalize_preset_groups(app):
    b = app._build_pro6_structured("A\n\nB", "空行", "空行")
    root = ET.fromstring(b.decode())
    g = root.find('.//RVSlideGrouping'); g.set("name", "Chorus"); g.set("color", "0 0 0 1")
    b = app._xml_to_bytes(root, b.decode())
    b2 = app._normalize_preset_groups(b)                    # Chorus → 綁定紅
    assert ET.fromstring(b2.decode()).find('.//RVSlideGrouping').get("color") == app._hex_rgba("#D0021B")
    # 非預設名稱不動（byte 不變）
    b3 = app._build_pro6_structured("X\n\nY", "空行", "空行")
    assert app._normalize_preset_groups(b3) == b3

def test_delete_slide_by_num(app):
    b = app._build_pro6_structured("A\n\nB\n\nC", "空行", "空行")
    b2, err = app._delete_slide_by_num(b, 2)               # 刪中間那張
    assert err is None and _ok(b2)
    texts = ["".join(t for _,_,t,_ in tl) for _,_,tl in _layers(app, b2)]
    assert len(_layers(app, b2)) == 2 and "B" not in "".join(texts)
    # 刪到群組變空 → 群組也移除
    b3 = app._build_pro6_structured("X", "空行", "空行")
    b3, _ = app._delete_slide_by_num(b3, 1)
    root = ET.fromstring(b3.decode())
    assert len(root.find('.//array[@rvXMLIvarName="groups"]').findall("RVSlideGrouping")) == 0

def test_load_new_doc_fk_uses_original_size(app):
    # 回歸：匯入有預設群組名（會被正規化、byte 數改變）的檔時，_fk 必須用「原始」長度，
    # 否則每次 rerun 會與上傳端 uploaded.size 對不上 → 重載原檔、洗掉模板/編輯結果。
    b = app._build_pro6_structured("A\n\nB", "空行", "空行")
    root = ET.fromstring(b.decode())
    g = root.find('.//RVSlideGrouping'); g.set("name", "Chorus"); g.set("color", "0 0 0 1")
    raw = app._xml_to_bytes(root, b.decode())
    assert app._normalize_preset_groups(raw) != raw          # 正規化確實改了 byte
    app.st.session_state.clear()
    app._load_new_doc(raw, "song.pro6")
    assert app.st.session_state["_fk"] == ("song.pro6", len(raw))   # 用原始長度
    assert app.st.session_state["xml_content"] == app._normalize_preset_groups(raw)

def _regroup(app, b, parts):
    """把單組 deck 依序切成多個 group：parts=[(name, size)…]（用 _set_group_fill）。"""
    colors = ["#8E44AD", "#3B6FD4", "#D0021B", "#2E8B57", "#F5C518"]
    b, _ = app._set_group_fill(b, 1, parts[0][0], colors[0])
    num = 1 + parts[0][1]
    for i, (name, size) in enumerate(parts[1:], 1):
        b, _ = app._set_group_fill(b, num, name, colors[i % len(colors)])
        num += size
    return b

def test_merge_double_rows(app):
    # 段落內兩兩合併：標題(2)／Verse(3)／Chorus(3)；第一組(標題)不動、各組獨立、奇數末張留
    b = app._build_pro6_structured("\n\n".join(f"S{i}" for i in range(1, 9)), "空行", "空行")
    b = _regroup(app, b, [("標題", 2), ("Verse", 3), ("Chorus", 3)])
    nb, n = app._merge_double_rows(b)
    assert n == 2 and _ok(nb)
    texts = ["".join(t for _, _, t, _ in tl) for _, _, tl in _layers(app, nb)]
    # 標題 S1,S2 原封不動；Verse (S3,S4) 合併、S5 落單；Chorus (S6,S7) 合併、S8 落單
    assert texts == ["S1", "S2", "S3\nS4", "S5", "S6\nS7", "S8"]
    assert _groups(app, nb) == [("標題", 2), ("Verse", 2), ("Chorus", 2)]

def test_merge_double_rows_layer_count(app):
    # 非首組內，兩張圖層數 2,3 → 合併成 3 層、末層單行
    b = app._build_pro6_structured("標題\n\n行1\n行2\n\n行A\n行B\n行C", "空行", "換行")
    b = _regroup(app, b, [("標題", 1), ("Verse", 2)])
    nb, n = app._merge_double_rows(b)
    rows = _layers(app, nb)
    assert n == 1 and len(rows) == 2                          # 標題 + 合併後一張
    layer_texts = [t for _, _, t, _ in rows[1][2]]
    assert layer_texts == ["行1\n行A", "行2\n行B", "行C"]      # 圖層數取多、末層單行

def test_merge_double_rows_skips_lone_first_group(app):
    # 只有一個 group（無屬段落/標題）→ 完全不動
    b = app._build_pro6_structured("一\n\n二\n\n三\n\n四", "空行", "空行")
    nb, n = app._merge_double_rows(b)
    texts = ["".join(t for _, _, t, _ in tl) for _, _, tl in _layers(app, nb)]
    assert n == 0 and texts == ["一", "二", "三", "四"]       # 第一組不動 → 沒有任何合併

def test_batch_rename_layers(app, sample):
    nb, n = app._batch_rename_layers(sample, ["主歌詞", "副歌詞"])
    assert n >= 1 and _ok(nb)
    _, gs = app._parse_xml(nb)
    for g in gs:
        for s in g["slides"]:
            if len(s["layers"]) >= 1:
                assert s["layers"][0]["displayName"] == "主歌詞"
            if len(s["layers"]) >= 2:
                assert s["layers"][1]["displayName"] == "副歌詞"

