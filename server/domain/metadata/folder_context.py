"""纯词法提取有界目录提示，不访问文件系统或发送完整路径。"""

import re
from pathlib import PurePath, PurePosixPath, PureWindowsPath

from server.models.ai import AIFolderContext


def _lexical_path(value: str) -> PurePath | None:
    if not value or re.search(r"(?:\w+://|www\.)", value, re.I):
        return None
    path_type = (
        PureWindowsPath if "\\" in value or re.match(r"^[A-Za-z]:", value) else PurePosixPath
    )
    # 115 返回的多个前导斜杠不是 UNC；归一化但不读取路径。
    if path_type is PurePosixPath and value.startswith("/"):
        value = "/" + value.lstrip("/")
    path = path_type(value)
    return None if ".." in path.parts else path


def _safe_names(parts: list[str]) -> list[str]:
    names = []
    for part in parts:
        try:
            name = AIFolderContext.clean_name(part)
        except ValueError:
            continue
        if name:
            names.append(name)
    return names


def build_ai_folder_context(file_path: str, scan_root: str | None = None) -> AIFolderContext:
    """保留扫描根、最外作品层和最近目录；未知根只取最近两层。"""
    path = _lexical_path(file_path)
    if path is None:
        return AIFolderContext()
    root = _lexical_path(scan_root) if scan_root else None
    if root is not None and type(path) is type(root):
        try:
            relative = path.parent.relative_to(root)
        except ValueError:
            pass  # 越界时不伪造作品层，也不泄露根的祖先目录。
        else:
            relative_names = _safe_names(list(relative.parts))
            root_names = _safe_names([root.name])
            all_names = root_names + relative_names
            positions = sorted({0, *range(max(0, len(all_names) - 2), len(all_names))})
            if root_names and relative_names:
                positions = sorted({*positions, 1})
            names = [all_names[index] for index in positions if index < len(all_names)]
            return AIFolderContext(
                scan_root_name=root_names[0] if root_names else None,
                outer_folder_name=(relative_names or root_names or [None])[0],
                parent_folder_name=all_names[-1] if all_names else None,
                folder_names=names,
            )
    # PurePath 的 anchor 可能是盘符或 UNC 网络位置，绝不作为目录提示。
    parts = [part for part in path.parent.parts if part != path.anchor]
    names = _safe_names(parts[-2:])
    return AIFolderContext(
        outer_folder_name=names[0] if names else None,
        parent_folder_name=names[-1] if names else None,
        folder_names=names,
    )
