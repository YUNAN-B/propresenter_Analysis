"""pytest 共用設定：以假的 streamlit 載入 app.py，並提供 fixture。

app.py 在模組層級會跑 Streamlit UI；這裡把 streamlit stub 掉，並讓 st.stop()
丟出 _Stop，讓 import 在「尚未上傳檔案」處乾淨停下——此時 §1~§6 所有純邏輯
函式都已定義，但 UI 主體不會執行。
"""
import os, sys, types, importlib.util
import pytest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
_APP  = os.path.join(_ROOT, "app.py")
_SAMPLE = os.path.join(_HERE, "fixtures", "sample.pro6")


class _Stop(Exception):
    pass


def _load_app():
    st = types.ModuleType("streamlit")
    _deco = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    st.cache_data = _deco
    st.cache_resource = _deco
    st.dialog = _deco          # @st.dialog("...") 於 import 時就會執行
    st.fragment = _deco
    _noop = lambda *a, **k: None
    for n in ["set_page_config", "markdown", "title", "file_uploader", "info", "caption",
              "divider", "button", "download_button", "tabs", "expander", "columns",
              "text_area", "success", "error", "rerun", "code", "checkbox", "radio",
              "warning", "text_input", "container", "toggle", "toast", "balloons", "snow",
              "subheader", "number_input", "selectbox"]:
        setattr(st, n, _noop)

    class _Ctx:                       # st.columns/container 的最小替身：可 with、可 .method()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __getattr__(self, k): return _noop
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

    spec = importlib.util.spec_from_file_location("app", _APP)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except _Stop:
        pass   # 純邏輯函式此時皆已定義
    return mod


@pytest.fixture(scope="session")
def app():
    """載入後的 app 模組（純邏輯函式）。"""
    return _load_app()


@pytest.fixture
def sample(app):
    """合成測試檔的 bytes。"""
    with open(_SAMPLE, "rb") as f:
        return f.read()
