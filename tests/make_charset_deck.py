"""把極端字元測試字串做成一個 .pro6：每個字串一張投影片，slide label 標好編號。

在 ProPresenter（7 初步、6 權威）開啟這一個檔，滑過去看哪張顯示跟預期不一致即可，
不必逐行貼字。產出：tests/fixtures/charset_deck.pro6

每張兩個文字圖層：
  L0 上方＝編號標籤（純 ASCII，方便辨識是哪一張）
  L1 下方＝要測的字串本身

執行：python tests/make_charset_deck.py
"""
import base64, os, sys, types, importlib.util

# 重用 app 的編碼器（_encode_run_text），確保產生的 RTF 與實際 app 輸出一致
def _load_app():
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_resource = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    class _Stop(Exception): pass
    _noop = lambda *a, **k: None
    for n in ["set_page_config","markdown","title","file_uploader","info","caption","divider",
              "button","download_button","tabs","expander","columns","text_area","success",
              "error","rerun","code","checkbox","radio","warning","text_input","container"]:
        setattr(st, n, _noop)
    st.stop = lambda: (_ for _ in ()).throw(_Stop())
    class _SS(dict):
        def __getattr__(self, k): return self.get(k)
    st.session_state = _SS()
    comp = types.ModuleType("streamlit.components"); v1 = types.ModuleType("streamlit.components.v1"); v1.html = _noop
    comp.v1 = v1; st.components = comp
    sys.modules["streamlit"] = st; sys.modules["streamlit.components"] = comp; sys.modules["streamlit.components.v1"] = v1
    root = os.path.dirname(os.path.dirname(__file__))
    spec = importlib.util.spec_from_file_location("app", os.path.join(root, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    try: spec.loader.exec_module(mod)
    except _Stop: pass
    return mod

mod = _load_app()

# (label, 要測的字串)
CASES = [
    ("A1 直撇號",   "It's a can't-miss don't-stop O'Brien"),
    ("A2 彎撇號",   "It’s can’t O’Brien"),
    ("A3 雙引號直", "He said \"hello\" and 'bye'"),
    ("A4 雙引號彎", "He said “hello” and ‘bye’"),
    ("A5 破折號",   "em A—B en A–B hyphen A-B"),
    ("A6 刪節號",   "wait… dots... ellipsis…"),
    ("A7 撇號接英", "I’ve I’ll we’re you’d they’ve"),
    ("B1 法文",     "café naïve résumé fiancé"),
    ("B2 德文",     "Über schön Mädchen Größe weiß"),
    ("B3 西葡",     "Señor mañana João coração"),
    ("B4 北歐",     "Ångström ø å æ œ ß"),
    ("B5 組合附加", "é à ñ"),
    ("C1 全形標點", "你好，世界。真的嗎？太好了！"),
    ("C2 全形括號", "《書名》「引」（圓）〈角〉"),
    ("C3 全形英數", "ＡＢＣ１２３ vs ABC123"),
    ("C4 全形空格", "前　中　後"),
    ("C5 NBSP",     "前 中 後"),
    ("D1 中英夾",   "中文English中文123中文"),
    ("D2 數字單位", "溫度 25°C ， $19.99 ， 50%"),
    ("D3 符號夾中", "A&B、C/D、E＋F、G–H"),
    ("E1 前導空白", "   這行開頭有空格"),
    ("E2 結尾空白", "這行結尾有空格   "),
    ("E3 開頭標點", "、開頭就是標點"),
    ("F1 超長單行", "這" + "是個很長的句子" * 6),
    ("F2 長英文",   "Supercalifragilisticexpialidocious-pneumonoultramicroscopic"),
    ("G1 符號",     "♪ ♫ ✝ ★ ☆ § ※"),
    ("G2 箭頭數學", "→ ← ± × ÷ ≠ ≤ ∞"),
    ("G3 貨幣",     "$ € £ ¥ ₩ ¢"),
    ("G4 emoji",    "\U0001f64f ✨ \U0001f525"),
    ("G5 emoji膚色","\U0001f44d\U0001f3fd \U0001f44f\U0001f3fc"),
    ("H1 大括號",   "text 有 { 和 } 大括號"),
    ("H2 反斜線",   "path C:\\folder\\file"),
    ("H3 三者並存", "{ \\ } 並存"),
    ("I1 段內換行", "第一行\n第二行\n第三行"),
    ("I2 連續換行", "A\n\n\nB"),
]

def _rtf(text, font="Helvetica"):
    body = mod._encode_run_text(text)
    return ("{\\rtf1\\ansi\\ansicpg950\\cocoartf2580\n"
            "{\\fonttbl\\f0\\fnil\\fcharset0 " + font + ";}\n"
            "{\\colortbl;\\red255\\green255\\blue255;}\n"
            "{\\*\\expandedcolortbl;;}\n"
            "\\pard\\tx560\\pardirnatural\\qc\\partightenfactor0\n"
            "\\f0\\fs120 \\cf1 " + body + "}")

def _b64(rtf):
    return base64.b64encode(rtf.encode("utf-8")).decode("ascii")

def _text_el(uuid, y, h, b64, fs="120"):
    return (f'<RVTextElement UUID="{uuid}" displayName="Text" opacity="1.000000" '
            f'verticalAlignment="0" useAllCaps="false" adjustsHeightToFit="true" '
            f'drawingFill="false" fillColor="0 0 0 0" rotation="0" fromTemplate="false">'
            f'<RVRect3D rvXMLIvarName="position">{{40 {y} 0 1840 {h}}}</RVRect3D>'
            f'<NSString rvXMLIvarName="RTFData">{b64}</NSString>'
            f'</RVTextElement>')

def build():
    slides = []
    for i, (label, text) in enumerate(CASES):
        # ascii-safe label 圖層 + 內容圖層
        lbl_b64 = _b64(_rtf(label))
        txt_b64 = _b64(_rtf(text))
        els = (_text_el(f"L{i}A", 80, 200, lbl_b64) +
               _text_el(f"L{i}B", 400, 500, txt_b64))
        # label 屬性也放 ascii 編號，左側清單可讀
        safe = "".join(c if ord(c) < 128 else "?" for c in label)
        slides.append(
            f'<RVDisplaySlide UUID="SL{i}" backgroundColor="0 0 0 1" enabled="true" '
            f'highlightColor="0 0 0 0" hotKey="" label="{safe}" notes="">'
            f'<array rvXMLIvarName="cues"></array>'
            f'<array rvXMLIvarName="displayElements">{els}</array>'
            f'</RVDisplaySlide>')
    body = "".join(slides)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<RVPresentationDocument CCLISongTitle="Charset Test" category="test" '
            'height="1080" width="1920" versionNumber="600" buildNumber="100" '
            'backgroundColor="0 0 0 1" docType="0" '
            'CCLIAuthor="" CCLIPublisher="" CCLICopyrightYear="" CCLISongNumber="" uuid="DECK">'
            '<array rvXMLIvarName="arrangements"></array>'
            '<array rvXMLIvarName="groups">'
            '<RVSlideGrouping name="Charset" color="0 0 1 1" uuid="GRP">'
            f'<array rvXMLIvarName="slides">{body}</array>'
            '</RVSlideGrouping></array></RVPresentationDocument>')

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "fixtures", "charset_deck.pro6")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build())
    print(f"已寫出 {out}（{len(CASES)} 張投影片）")
