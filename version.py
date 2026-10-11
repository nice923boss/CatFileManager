"""Application version and user-facing changelog (shown in the About dialog)."""

VERSION = "1.1.0"

# Newest first: (version, [change lines in Traditional Chinese])
CHANGELOG: list[tuple[str, list[str]]] = [
    (
        "1.1.0",
        [
            "Junction／符號連結／捷徑顯示箭頭徽章，右鍵可開啟實際位置",
            "設定視窗、淺色主題與跟隨系統、字型大小、啟動路徑",
            "顯示隱藏檔、副檔名開關，依檔案類型著色，記住欄寬與排序",
            "檔名衝突對話框、復原 Ctrl+Z、操作佇列、暫停續傳、複製後驗證",
            "遞迴搜尋、萬用字元與正規表示式、Everything、內容搜尋、搜尋歷史",
            "快捷鍵一覽與自訂、指令面板、面板版面切換、大圖示檢視",
        ],
    ),
    ("1.0.0", ["四面板檔案管理、目錄樹、我的最愛、資源回收筒"]),
]
