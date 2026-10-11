"""File-extension categories used for colouring names and picking thumbnails."""

IMAGE_EXTS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".heic", ".svg"}
)
VIDEO_EXTS = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts"}
)
ARCHIVE_EXTS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso"})
EXEC_EXTS = frozenset({".exe", ".msi", ".bat", ".cmd", ".ps1", ".com", ".scr"})

_CATEGORIES = (
    ("image", IMAGE_EXTS),
    ("video", VIDEO_EXTS),
    ("archive", ARCHIVE_EXTS),
    ("exec", EXEC_EXTS),
)


def category(ext: str) -> str:
    """Return "image" / "video" / "archive" / "exec", or "" for anything else."""
    ext = ext.lower()
    for name, exts in _CATEGORIES:
        if ext in exts:
            return name
    return ""
