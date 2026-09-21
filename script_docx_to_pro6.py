r"""
script_docx_to_pro6.py · 舞台劇台詞 docx → .pro6
═══════════════════════════════════════════════════════════════════
輸入：中英對照台詞 .docx（結構＝「中文行 / 英文行 / 空行」三行一組；
      「Title: xxx」開頭行為文件標題；「（歌曲）/＊＊歌曲＊＊」為歌曲標記）
輸出：每組台詞兩張投影片——
  • 中文一張：enabled="false"（停用，操作時自動跳過、僅供對照），
    樣式＝styles.json「大字中英」的中文層（SourceHanSerifTC-Heavy 110pt 白），
    滿版置中。
  • 英文一張：樣式＝styles.json「單句英文」（Optima-Bold 65pt），
    沿用樣式原始位置──底部字幕條（y=971、垂直置底）。
歌曲標記 → 一張「空白投影片」，以 label 標示（例：＊＊歌曲＊＊），不用 group
（全檔單一無名 group）——操作者看清單就知道這裡要切歌，觸發時畫面清空。

用法：.venv/bin/python script_docx_to_pro6.py 第一幕_中英對照.docx
（輸出 <標題>_台詞.pro6 於同目錄；標題取自 Title: 行，無則取檔名）

依賴 app.py 的 RTF/XML 機具（_set_el_text、_doc_wrapper_groups…），
以 tests/conftest 的 streamlit stub 載入，不啟動 UI。
"""
import base64
import json
import os
import re
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "tests"))
from conftest import _load_app          # streamlit stub 載入 app 模組
app = _load_app()

# ── docx 解析 ───────────────────────────────────────────────────
def docx_paragraphs(path):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8")
    return ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
            for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)]

_MARKER = re.compile(r"^[（(＊*\s]*歌曲[）)＊*\s]*$")

def parse_script(paras):
    """段落 → (title, items)；item＝("pair", cn, en) 或 ("marker", 標記字面)。
    以空行切組：每組應為 [中, 英]；「Title:」組取標題；異常組列入 warnings。"""
    title = None
    items = []
    warnings = []
    run = []
    def flush():
        nonlocal title
        if not run: return
        lines = run[:]
        run.clear()
        if lines[0].startswith("Title:"):
            if title is None:
                title = lines[0].split(":", 1)[1].strip()
            return
        if _MARKER.match(lines[0]):
            items.append(("marker", lines[0].strip()))
            return
        if len(lines) == 2:
            items.append(("pair", lines[0].strip(), lines[1].strip()))
        elif len(lines) == 1:
            items.append(("pair", lines[0].strip(), ""))   # 缺英文 → 僅中文張
            warnings.append(f"單行（無英文配對）：{lines[0]!r}")
        else:                                              # 3 行以上：兩兩容錯
            warnings.append(f"{len(lines)} 行連在一起（依序兩兩配對）：{lines[0]!r}…")
            for i in range(0, len(lines) - 1, 2):
                items.append(("pair", lines[i].strip(), lines[i+1].strip()))
            if len(lines) % 2:
                items.append(("pair", lines[-1].strip(), ""))
    for ln in paras:
        if ln.strip():
            run.append(ln.strip())
        else:
            flush()
    flush()
    return title, items, warnings

# ── 樣式模板 → 元素（中文置中滿版、英文照樣式置底）─────────────────────────────────────
_STYLES = json.load(open(os.path.join(_HERE, "styles.json"), encoding="utf-8"))
_CN_TMPL = _STYLES["大字中英"][0]      # 中文層：SourceHanSerifTC-Heavy 110pt 白
_EN_TMPL = _STYLES["單句英文"][0]      # 英文：Optima-Bold 65pt

def _styled_element(tmpl_xml: str, text: str, center: bool) -> str:
    """樣式模板 → 注入文字。center=True 改為滿版垂直置中（中文用）；
    False 保留模板原始位置與對齊（英文用──單句英文樣式本來就是置底字幕條）。"""
    el = ET.fromstring(tmpl_xml)
    el.set("UUID", str(uuid.uuid4()).upper())
    if center:
        el.set("verticalAlignment", "1")
        pn = el.find('RVRect3D[@rvXMLIvarName="position"]')
        if pn is not None: pn.text = "{0 0 0 1920 1080}"
    app._set_el_text(el, text)          # 以模板首字樣式寫入（保留字體/字級/顏色）
    return ET.tostring(el, encoding="unicode")

def _slide(elements_xml: str, enabled=True, label="") -> str:
    return (f'<RVDisplaySlide UUID="{str(uuid.uuid4()).upper()}" backgroundColor="0 0 0 1" '
            'chordChartPath="" drawingBackgroundColor="false" '
            f'enabled="{"true" if enabled else "false"}" highlightColor="0 0 0 0" '
            f'hotKey="" label="{app._xml_attr(label)}" notes="" socialItemCount="1">'
            '<array rvXMLIvarName="cues"></array>'
            f'<array rvXMLIvarName="displayElements">{elements_xml}</array>'
            '</RVDisplaySlide>')

def build_pro6(title, items):
    slides = []
    for it in items:
        if it[0] == "marker":                              # 歌曲 → 空白張＋label 標記
            slides.append(_slide("", enabled=True, label=it[1]))
            continue
        _, cn, en = it
        if cn:                                             # 中文張：停用、僅供對照
            slides.append(_slide(_styled_element(_CN_TMPL, cn, center=True), enabled=False))
        if en:                                             # 英文張：實際投影
            slides.append(_slide(_styled_element(_EN_TMPL, en, center=False), enabled=True))
    xml = app._doc_wrapper_groups([("", "0 0 0 0", slides)])
    xml = app._set_title(xml, title)
    xml, _ = app._dedup_uuids(xml)
    ET.fromstring(xml.decode("utf-8"))                     # 最終驗證
    return xml

def _load_splits():
    """splits.json（可選）：{原始中文句: [[中1,英1],[中2,英2]…]}——長句切分表。
    只切不改字（由核對腳本保證）；英文空字串＝該半句不出英文張。"""
    p = os.path.join(_HERE, "splits.json")
    if not os.path.exists(p): return {}
    d = json.load(open(p, encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}

def _apply_splits(items, table):
    out = []
    n = 0
    for it in items:
        if it[0] == "pair" and it[1] in table:
            for cn, en in table[it[1]]:
                out.append(("pair", cn, en))
            n += 1
        else:
            out.append(it)
    return out, n

def main(path):
    paras = docx_paragraphs(path)
    title, items, warnings = parse_script(paras)
    items, n_split = _apply_splits(items, _load_splits())
    if n_split: print(f"   已套用長句切分：{n_split} 句 → 各拆兩張")
    # 無 Title: 行時退回檔名（去掉「_中英對照」尾綴，如第四幕）
    title = title or os.path.basename(path).rsplit(".", 1)[0].replace("_中英對照", "")
    xml = build_pro6(title, items)
    out = os.path.join(os.path.dirname(os.path.abspath(path)) or ".", f"{title}_台詞.pro6")
    with open(out, "wb") as f: f.write(xml)
    n_pair = sum(1 for i in items if i[0] == "pair")
    n_mark = sum(1 for i in items if i[0] == "marker")
    n_slides = sum(1 for i in items if i[0] == "marker" or i[1]) \
             + sum(1 for i in items if i[0] == "pair" and i[2])
    print(f"✅ {out}")
    print(f"   台詞 {n_pair} 組 → 中文(停用)+英文各一張；歌曲標記 {n_mark} 個（空白張+label）")
    print(f"   總投影片 {n_slides} 張")
    for w in warnings: print(f"   ⚠️ {w}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    for p in sys.argv[1:]:
        main(p)
