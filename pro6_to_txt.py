r"""
pro6_to_txt.py · 批次將資料夾內的 ProPresenter 檔轉成純文字 .txt
═══════════════════════════════════════════════════════════════════
用法：
    python pro6_to_txt.py <輸入資料夾> [輸出資料夾]

  • 掃描輸入資料夾（含子資料夾）內所有 .pro6 檔；.pro（Pro7 protobuf）
    也支援——先經 pro7.py 轉成 pro6 XML 再解析。
  • 每個檔案輸出一個同名 .txt 到輸出資料夾（未指定則輸出到輸入資料夾）。
  • 文字擷取沿用 app.py 的核心邏輯：
      parse_rtf(keep_empty=True) → _drop_style_break_nl()
    亦即 RTFData base64 → RTF → 各 run 明文，並移除「換樣式多插的那個換行」
    （見 app.py 檔頭核心不變量），輸出即撰寫頁看到的整層文字。

輸出格式（歌詞友善）：
    [群組名]                ← 每個 RVSlideGrouping 一行標頭（空名略過）
    第一張投影片的文字…      ← 每張 slide 的所有文字圖層，圖層間以換行相接
                            ← slide 之間空一行
"""

import os
import sys
import types
import base64
import importlib.util
import xml.etree.ElementTree as ET

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

import pro7                                        # noqa: E402  Pro7 .pro → pro6 XML


# ── 載入 app.py 的純邏輯函式（手法同 tests/conftest.py）────────────
# app.py 模組層級會跑 Streamlit UI；以假 streamlit 載入、st.stop() 丟例外
# 讓 import 在「尚未上傳檔案」處乾淨停下，§1~§6 純邏輯函式皆已定義。
# 好處：文字擷取與 App/測試走同一份程式碼，且本腳本不需安裝 streamlit。

class _Stop(Exception):
    pass


def _load_app():
    st = types.ModuleType("streamlit")
    _deco = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_data = st.cache_resource = st.dialog = st.fragment = _deco
    _noop = lambda *a, **k: None

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __getattr__(self, k): return _noop

    st.__getattr__ = lambda name: _noop            # 其餘 st.* 一律 no-op
    st.columns = lambda spec, *a, **k: [_Ctx() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.stop = lambda: (_ for _ in ()).throw(_Stop())

    class _SS(dict):
        def __getattr__(self, k): return self.get(k)
    st.session_state = _SS()
    comp = types.ModuleType("streamlit.components")
    v1 = types.ModuleType("streamlit.components.v1"); v1.html = _noop
    comp.v1 = v1; st.components = comp
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = comp
    sys.modules["streamlit.components.v1"] = v1

    spec = importlib.util.spec_from_file_location("app", os.path.join(_ROOT, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except _Stop:
        pass
    return mod


_app = _load_app()
parse_rtf = _app.parse_rtf
_drop_style_break_nl = _app._drop_style_break_nl


def slide_text(slide_el) -> str:
    """一張 RVDisplaySlide → 明文（所有文字圖層，依圖層順序以換行相接）。"""
    parts = []
    disp = slide_el.find('array[@rvXMLIvarName="displayElements"]')
    for el in (disp if disp is not None else []):
        if el.tag != "RVTextElement":
            continue
        rn = el.find('NSString[@rvXMLIvarName="RTFData"]')
        if rn is None or not (rn.text or "").strip():
            continue
        try:
            rtf = base64.b64decode(rn.text.strip()).decode("utf-8", errors="replace")
            txt = _drop_style_break_nl(parse_rtf(rtf, keep_empty=True).runs).strip("\n")
        except Exception:
            continue
        if txt.strip():
            parts.append(txt)
    return "\n".join(parts)


def pro6_to_text(xml_bytes: bytes) -> str:
    """pro6 XML bytes → 整份純文字（群組標頭 + 各 slide 文字，slide 間空行）。"""
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    gnode = root.find('.//array[@rvXMLIvarName="groups"]')
    out = []
    for g in (gnode.findall("RVSlideGrouping") if gnode is not None else []):
        gname = (g.get("name") or "").strip()
        blocks = []
        snode = g.find('array[@rvXMLIvarName="slides"]')
        for sl in (snode if snode is not None else []):
            t = slide_text(sl)
            if t.strip():
                blocks.append(t)
        if not blocks:
            continue
        if gname:
            out.append(f"[{gname}]")
        out.append("\n\n".join(blocks))
        out.append("")                      # 群組之間空一行
    return "\n".join(out).strip("\n") + "\n"


def convert_file(path: str) -> str:
    """單一 .pro6 / .pro 檔 → 純文字。Pro7 檔先轉 pro6 XML。"""
    with open(path, "rb") as f:
        raw = f.read()
    if pro7.is_pro7(raw, os.path.basename(path)):
        raw, _report = pro7.pro7_to_pro6(raw)
    return pro6_to_text(raw)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    src = argv[0]
    dst = argv[1] if len(argv) > 1 else src
    if not os.path.isdir(src):
        print(f"找不到輸入資料夾：{src}")
        return 1
    os.makedirs(dst, exist_ok=True)

    targets = []
    for dirpath, _dirs, files in os.walk(src):
        for name in sorted(files):
            if name.lower().endswith((".pro6", ".pro")) and not name.startswith("."):
                targets.append(os.path.join(dirpath, name))
    if not targets:
        print(f"{src} 內沒有 .pro6 / .pro 檔。")
        return 1

    ok = fail = 0
    for path in targets:
        rel = os.path.relpath(path, src)
        out_path = os.path.join(dst, os.path.splitext(rel)[0] + ".txt")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        try:
            text = convert_file(path)
        except Exception as e:
            print(f"✗ {rel}: {e}")
            fail += 1
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✓ {rel} → {os.path.relpath(out_path, dst)}")
        ok += 1
    print(f"\n完成：{ok} 個成功" + (f"，{fail} 個失敗" if fail else ""))
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
