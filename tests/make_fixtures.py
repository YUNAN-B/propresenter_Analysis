"""產生合成的測試用 .pro6（無版權歌詞、無個人路徑）。

手刻 RTF + XML 作為「正確答案」，刻意涵蓋各種邊角情境：
  s1 雙語多行中文 + 英文      → 拼音、依換行拆分
  s2 撇號 + 多餘空白 + 無\\uc0  → 刪前後/整理空白、\\uc0 回歸（I've→I'e）
  s3 空圖層 + Double-click    → 清除空圖層
  s4 無 displayElements       → 刪除無圖層投影片
  s5 多色（兩段不同顏色）       → 顏色保留
  s6/s7 重複 UUID            → 匯出去重

執行：python tests/make_fixtures.py  → 寫出 tests/fixtures/sample.pro6
"""
import base64, os

# ── RTF 組裝 ────────────────────────────────────────────────────
def _u(s):                       # 中文等非 ASCII → \uNNNN （需在 \uc0 區域）
    return "".join(f"\\u{ord(c)} " for c in s)

def _rtf(body, font="TestHei", colortbl=";\\red255\\green255\\blue255;"):
    return ("{\\rtf1\\ansi\\ansicpg950\\cocoartf2580\n"
            "\\cocoatextscaling0\\cocoaplatform0{\\fonttbl\\f0\\fnil\\fcharset0 " + font + ";}\n"
            "{\\colortbl" + colortbl + "}\n"
            "{\\*\\expandedcolortbl;;}\n"
            "\\pard\\tx560\\pardirnatural\\qc\\partightenfactor0\n"
            "\\f0\\fs200 \\cf1 " + body + "}")

def _b64(rtf):
    return base64.b64encode(rtf.encode("utf-8")).decode("ascii")

# 各種 RTF body（手刻的 ground truth）
RTF = {
    # 多行中文：讚美主 / 哈利路亞（\uc0 後用 \uNNNN，行間用 \ + 換行）
    "zh_multi": _rtf("\\uc0 " + _u("讚美主") + "\\\n" + _u("哈利路亞")),
    "en":       _rtf("Praise the Lord"),
    # 撇號用 \'92（cp1252），且整段沒有 \uc0 → 預設 \uc1。含多餘空白。
    "apos_ws":  _rtf("I\\'92ve  got   freedom "),
    "empty":    _rtf(""),                       # 只有控制字、無文字
    "placeholder": _rtf("Double-click to edit"),
    # 多色：紅(cf1) / 藍(cf2)，第二段在下一行
    "multicolor": _rtf("\\uc0 " + _u("紅") + "\\cf2 \\\n" + _u("藍"),
                       colortbl=";\\red255\\green255\\blue255;\\red0\\green0\\blue255;"),
}

# ── XML 組裝 ────────────────────────────────────────────────────
def _text_el(uuid, x, y, w, h, b64, name="Text", valign="0"):
    return (f'<RVTextElement UUID="{uuid}" displayName="{name}" opacity="1.000000" '
            f'verticalAlignment="{valign}" useAllCaps="false" adjustsHeightToFit="true" '
            f'drawingFill="false" fillColor="0 0 0 0" rotation="0" fromTemplate="false">'
            f'<RVRect3D rvXMLIvarName="position">{{{x} {y} 0 {w} {h}}}</RVRect3D>'
            f'<NSString rvXMLIvarName="RTFData">{b64}</NSString>'
            f'</RVTextElement>')

def _slide(uuid, elements, label="", bg="0 0 0 1"):
    els = "".join(elements)
    return (f'<RVDisplaySlide UUID="{uuid}" backgroundColor="{bg}" enabled="true" '
            f'highlightColor="0 0 0 0" hotKey="" label="{label}" notes="">'
            f'<array rvXMLIvarName="cues"></array>'
            f'<array rvXMLIvarName="displayElements">{els}</array>'
            f'</RVDisplaySlide>')

def build():
    slides = [
        # s1 雙語多行
        _slide("S1", [
            _text_el("S1L0", 5, 100, 1910, 300, _b64(RTF["zh_multi"])),
            _text_el("S1L1", 5, 900, 1910, 120, _b64(RTF["en"])),
        ], label="bilingual"),
        # s2 撇號 + 空白 + 無 \uc0
        _slide("S2", [
            _text_el("S2L0", 5, 400, 1910, 300, _b64(RTF["apos_ws"])),
        ], label="apostrophe"),
        # s3 空圖層 + placeholder
        _slide("S3", [
            _text_el("S3L0", 5, 100, 1910, 200, _b64(RTF["empty"])),
            _text_el("S3L1", 5, 400, 1910, 200, _b64(RTF["placeholder"])),
        ], label="empties"),
        # s4 無圖層
        _slide("S4", [], label="no-layers"),
        # s5 多色
        _slide("S5", [
            _text_el("S5L0", 5, 300, 1910, 400, _b64(RTF["multicolor"])),
        ], label="multicolor"),
        # s6 / s7 重複 UUID（DUP 故意重複）
        _slide("S6", [_text_el("DUP", 5, 100, 1910, 200, _b64(RTF["en"]))], label="dup-a"),
        _slide("S7", [_text_el("DUP", 5, 100, 1910, 200, _b64(RTF["en"]))], label="dup-b"),
    ]
    body = "".join(slides)
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<RVPresentationDocument CCLISongTitle="Test Song" category="test" '
           'height="1080" width="1920" versionNumber="600" buildNumber="100" '
           'backgroundColor="0 0 0 1" docType="0" '
           'CCLIAuthor="" CCLIPublisher="" CCLICopyrightYear="" CCLISongNumber="" uuid="DOC1">'
           '<array rvXMLIvarName="arrangements"></array>'
           '<array rvXMLIvarName="groups">'
           '<RVSlideGrouping name="Verse" color="1 0 0 1" uuid="GRP1">'
           f'<array rvXMLIvarName="slides">{body}</array>'
           '</RVSlideGrouping>'
           '</array>'
           '</RVPresentationDocument>')
    return xml

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pro6")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build())
    print("已寫出", out)
