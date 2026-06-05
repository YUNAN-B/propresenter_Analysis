"""從一個參考 .pro6 抽出每張投影片的「文字樣式」→ styles.json（不含任何文字內容）。

每個樣式 = 該張投影片所有文字元素（RVTextElement）的完整 XML，但 RTFData 內文已清空，
只保留字體/字級/顏色/段落等排版設定，以及元素屬性、位置、shadow、stroke。
因此 styles.json 不含版權歌詞，可安全提交。

用法：python make_styles.py [參考檔.pro6]   （預設 fyb.pro6）→ 寫出 styles.json
套用邏輯見 app.py 的 _apply_style。
"""
import sys, os, json, copy
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tests"))
import conftest                       # 用假的 streamlit 載入 app（取得 _set_el_text 等）
app = conftest._load_app()


def build(src_path):
    root = ET.fromstring(open(src_path, encoding="utf-8").read())
    styles, used = {}, {}
    for i, sl in enumerate(root.iter("RVDisplaySlide")):
        de = sl.find('array[@rvXMLIvarName="displayElements"]')
        tes = [e for e in (de if de is not None else []) if e.tag == "RVTextElement"]
        if not tes:
            continue
        name = (sl.get("label", "") or f"樣式{i}").strip() or f"樣式{i}"
        if name in used:                       # 標籤重複 → 加序號
            used[name] += 1; name = f"{name} ({used[name]})"
        else:
            used[name] = 0
        layers = []
        for te in tes:
            t = copy.deepcopy(te)
            app._set_el_text(t, "")            # 清空內文，只留排版
            layers.append(ET.tostring(t, encoding="unicode"))
        styles[name] = layers
    return styles


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "fyb.pro6"
    styles = build(src)
    out = os.path.join(os.path.dirname(__file__), "styles.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(styles, f, ensure_ascii=False, indent=1)
    print(f"已寫出 {out}：{len(styles)} 個樣式")
    for k, v in styles.items():
        print(f"  {k}  ({len(v)} 層)")
