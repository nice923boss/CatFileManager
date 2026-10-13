# CatFileManager 四面板檔案管理器

Windows 用的多面板檔案管理器，以 Python 與 PySide6（Qt 6）撰寫。一個視窗同時開 1 到 4 個資料夾，面板之間拖曳、複製、搬移，不用在多個檔案總管視窗間切換。

## 主要功能

- **多面板版面**：單一、左右、上下、三面板、四面板，隨時切換並記住
- **檔案操作**：複製、搬移、刪除（資源回收筒）、重新命名、批次重新命名（序號、取代文字、正規表示式、大小寫、日期前綴，含即時預覽）
- **操作佇列**：大量複製在背景排隊執行，可暫停後續傳；檔名衝突時可選覆蓋、略過、自動改名；可選複製後驗證
- **復原**：Ctrl+Z 復原搬移、重新命名、複製、刪除到資源回收筒
- **搜尋**：目前資料夾篩選、遞迴搜尋子資料夾、萬用字元與正規表示式、檔案內容搜尋（UTF-8／Big5／UTF-16）、搭配 Everything 秒搜全碟、搜尋歷史
- **連結辨識**：Junction、符號連結、捷徑顯示箭頭徽章，右鍵可開啟實際位置
- **外觀**：深色、淺色、跟隨系統主題；字型與字級可調；依檔案類型著色；詳細資料與大圖示檢視
- **效率工具**：快捷鍵全部可自訂（F1 查看一覽）、命令面板（Ctrl+Shift+P）、右鍵選單項目可排序與隱藏、我的最愛（找不到的路徑會標示）
- **其他**：在此開啟 CMD／PowerShell／Windows Terminal、壓縮 ZIP、計算雜湊值、空白鍵 QuickLook 預覽

## 系統需求

- Windows 10 或 11
- Python 3.12 以上（從原始碼執行時）

## 從原始碼執行

```bash
git clone https://github.com/nice923boss/CatFileManager.git
```

```bash
cd CatFileManager
```

```bash
python -m pip install -r requirements.txt
```

```bash
python app.py
```

### 用 start.bat 背景啟動（選用）

第一次先執行 `relink_launcher.bat`，它會從 PATH 上的 Python 複製一份 `pythonw_catfm.exe`，工作管理員裡就能一眼認出這個程式。之後雙擊 `start.bat` 啟動、`stop.bat` 關閉。

## 選用的外部工具

| 工具 | 用途 | 下載 |
|------|------|------|
| Everything 與 ES 命令列工具 | 全碟秒搜（搜尋視窗選「Everything」模式） | https://www.voidtools.com/ |
| QuickLook | 空白鍵預覽檔案 | https://github.com/QL-Win/QuickLook |

沒裝 Everything 時，Everything 搜尋結果視窗會出現「一鍵安裝 Everything」按鈕，執行 `install_everything.ps1`：用 winget 安裝 ES 命令列工具與 Everything（安裝 Everything 會跳出系統管理員確認），已安裝但沒執行的 Everything 會直接啟動。裝好後按「重新搜尋」。支援 Everything 1.4、1.5 Beta 與 1.5 Alpha（自動改用 `-instance 1.5a`）。

es.exe 不在預設位置時，可在「設定 → 操作與搜尋」指定路徑。

## 設定與記錄檔位置

| 檔案 | 位置 |
|------|------|
| 設定 | `%USERPROFILE%\.quad-file-manager\settings.json` |
| 記錄檔 | `%USERPROFILE%\.catfm\app.log` |

## 打包成 exe

```bash
python -m pip install pyinstaller
```

```bash
python build.py --zip
```

產出在 `dist\CatFileManager\CatFileManager.exe`，加上 `--zip` 會另外產生可上傳到 GitHub Releases 的壓縮檔。

## 開發

```bash
python -m pip install pytest ruff
```

```bash
python -m pytest tests -q
```

```bash
ruff format . && ruff check .
```

## 已知限制

尚未完成或有條件限制的項目列在 [GAPS.md](GAPS.md)。

## 授權

[MIT License](LICENSE)

製作者：黃政文
