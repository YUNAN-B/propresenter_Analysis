# ProParse · 投影片解析

解析並批次編輯 **ProPresenter 6**（`.pro6` / `.xml`）檔的網頁工具，特別適合雙語歌詞、字幕等需要大量整理的投影片。
核心是「先解析檔案結構、再安全逆寫」，所有編輯只動三個維度：**圖層**、**位置**、**明文**。

🔗 **線上試用**：<https://proparse.streamlit.app/>

> 為什麼是 pro6：大多數機器仍裝第 6 版，且 ProPresenter 7 可向下相容開啟 pro6。

## 功能

三個分頁：

- **解析** — 唯讀檢視整份檔（文件資訊、背景影片/圖片、每個圖層的位置/字體/顏色/陰影、明文）。
- **模板** — 對全部投影片套用一個動作，分四類：
  - *統整*：清除空圖層、刪除前後空白、整理空白、刪除無圖層投影片
  - *轉換*：繁簡轉換（可反向）、拼音（第一層中文→第二層，opencc + pypinyin）
  - *操作*：圖層順序顛倒、依換行拆分圖層、圖層拆成投影片、全部投影片加圖層、合併圖層段落等
- **撰寫** — 逐段編輯明文（保留各段字體/字級/顏色），失焦自動儲存；支援 ⌘Z 還原。

匯出時自動確保所有 UUID 不重複。

## 安裝與執行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

瀏覽器開啟 http://localhost:8501，上傳 `.pro6` / `.xml` 即可編輯，最後從側邊欄匯出 `.pro6`。

## 設計重點（維護前必讀）

逆寫對格式很敏感，這些是踩過坑換來的不變量，詳見 `app.py` 檔頭：

- **不整份 ET round-trip**：`ET.tostring` 會把 `<x></x>` 折成 `<x/>`，原始 pro6 不用自閉合標籤，
  ProPresenter 可能讀不回。序列化後一律展開回 `<x></x>`，原始檔即逐字節無損。
- **明文逆寫是定點 span 替換**：只改被動到的片段，保留 RTF header 與所有控制字；無改動的儲存 byte 不變。
- **`\uc0` 陷阱**：RTF 的 `\uNNNN` 後會跳過 `\uc` 個替代字元；重編文字時前置 `\uc0` 避免吃掉下一個字。
- **拼音**：先 opencc 繁→簡再 pypinyin，才命中詞組字典、多音字才準。

## 測試

回歸測試用合成的 `.pro6`（無版權內容），涵蓋每個模板動作、無損逆寫、byte 穩定、
明文編輯，以及 `\uc0` 這類編碼回歸。

```bash
pip install -r requirements.txt   # 已含 pytest
pytest                            # 跑全部測試
python tests/make_fixtures.py     # 需要時重新產生測試資料
```

## 檔案地圖

### 核心程式
| 檔案 | 功能與作用 |
|------|-----------|
| `app.py` | **主程式**（Streamlit）。RTF/XML 解析、模板批次動作、撰寫頁定點逆寫、創造新檔，全部在這一支。檔頭有「核心不變量」說明，動程式碼前必讀。 |

### 樣式
| 檔案 | 功能與作用 |
|------|-----------|
| `make_styles.py` | 從一個參考 `.pro6` 抽出每張投影片的**排版樣式** → 寫出 `styles.json`（清空文字，只留字體／字級／顏色／位置／陰影等，**不含版權內容**）。 |
| `styles.json` | 預先產生的樣式清單（單句中文／英文／中英／英中、大字中英／英中）。app 的「樣式」功能讀它套排版。 |

### 執行與設定
| 檔案 | 功能與作用 |
|------|-----------|
| `requirements.txt` | 相依套件：streamlit／opencc／pypinyin（測試用的 pytest 也一併列入）。 |
| `pytest.ini` | pytest 設定。 |
| `.streamlit/config.toml` | Streamlit 主題（淺藍強調色、明暗可切換）與精簡的 ⋮ 工具選單。 |
| `.devcontainer/devcontainer.json` | GitHub Codespaces／VS Code 開發容器設定（Python 3.11、自動裝相依）。 |
| `.gitignore` | git 忽略清單（`.venv`、快取等不進版控）。 |
| `hard-hat.png` | 分頁圖示（工程帽 favicon）。 |

### 測試（`tests/`）
| 檔案 | 功能與作用 |
|------|-----------|
| `tests/conftest.py` | 用假的 streamlit stub 載入 `app.py`，讓純邏輯函式可被測而不啟動 UI；提供共用 fixture。 |
| `tests/test_rtf.py` | RTF 解析/整理空格/顯示 round-trip，以及逆寫回歸（無損序列化、byte 穩定、`\uc0`、UUID 去重）。 |
| `tests/test_templates.py` | 每個模板動作、段落類型(group)/熱鍵、刪除投影片等行為測試。 |
| `tests/make_fixtures.py` | 產生合成測試檔（無版權內容、涵蓋各種邊角情境）。 |
| `tests/fixtures/sample.pro6` | 上面產生的主要合成測試檔。 |

### 文件
| 檔案 | 功能與作用 |
|------|-----------|
| `README.md` | 本說明文件。 |
