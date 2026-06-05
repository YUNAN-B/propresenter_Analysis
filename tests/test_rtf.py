"""RTF 解析/編碼/空白 的單元測試（純函式，不需 fixture 檔）。"""


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


def test_runs_to_lines(app):
    lines = app._runs_to_lines([R("《\n"), R("shout\n"), R("》")])
    assert [t for t, _ in lines] == ["《", "shout", "》"]


# ── 小工具 ──────────────────────────────────────────────────────
def test_rgba_hex(app):
    assert app._rgba_hex("1 1 1 1") == "#FFFFFF"
    assert app._rgba_hex("0 0 0 0") == "transparent"

def test_parse_pos(app):
    assert app._parse_pos("{5 100 0 1910 300}") == {"x":5,"y":100,"z":0,"w":1910,"h":300}
