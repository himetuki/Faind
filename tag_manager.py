"""
Faind 标签管理模块
基于 SQLite 的标签存储与管理
"""

import sqlite3
from pathlib import Path
from typing import List


class TagManager:
    """标签管理器：SQLite 存储"""

    def __init__(self):
        self._local_db = None
        self._init_tag_system()

    def _init_tag_system(self):
        """初始化标签系统"""
        self._init_local_db()
        print("[TagManager] SQLite 标签存储已初始化")

    def _init_local_db(self):
        """初始化本地 SQLite 标签数据库"""
        from config import _get_config_dir
        db_dir = _get_config_dir()
        db_file = db_dir / "tags.db"

        self._local_db = sqlite3.connect(str(db_file), check_same_thread=False)
        self._local_db.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        self._local_db.execute("""
            CREATE TABLE IF NOT EXISTS file_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                source TEXT DEFAULT 'local',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tag_id) REFERENCES tags(id),
                UNIQUE(file_path, tag_id)
            )
        """)
        self._local_db.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_tags_path 
            ON file_tags(file_path)
        """)
        self._local_db.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_tags_tag 
            ON file_tags(tag_id)
        """)
        self._local_db.commit()

    # ============ 核心操作 ============

    def add_tags(self, file_paths: List[str], tags: List[str]) -> dict:
        """为文件添加标签"""
        if not file_paths or not tags:
            return {"success": False, "message": "文件路径或标签为空", "failed_files": []}

        return self._add_tags_local(file_paths, tags)

    def _add_tags_local(self, file_paths: List[str], tags: List[str]) -> dict:
        """使用 SQLite 添加标签"""
        try:
            for tag in tags:
                self._local_db.execute(
                    "INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,)
                )

            tag_ids = []
            for tag in tags:
                row = self._local_db.execute(
                    "SELECT id FROM tags WHERE name = ?", (tag,)
                ).fetchone()
                if row:
                    tag_ids.append(row[0])

            success_count = 0
            for file_path in file_paths:
                for tag_id in tag_ids:
                    try:
                        self._local_db.execute(
                            "INSERT OR IGNORE INTO file_tags (file_path, tag_id) VALUES (?, ?)",
                            (file_path, tag_id)
                        )
                        success_count += 1
                    except sqlite3.Error:
                        pass

            self._local_db.commit()

            return {
                "success": True,
                "message": f"成功为 {len(file_paths)} 个文件添加 {len(tags)} 个标签",
                "failed_files": []
            }
        except sqlite3.Error as e:
            return {
                "success": False,
                "message": f"数据库错误: {e}",
                "failed_files": file_paths
            }

    def remove_tags(self, file_paths: List[str], tags: List[str]) -> dict:
        """移除文件标签"""
        if not file_paths or not tags:
            return {"success": False, "message": "文件路径或标签为空"}

        return self._remove_tags_local(file_paths, tags)

    def _remove_tags_local(self, file_paths: List[str], tags: List[str]) -> dict:
        """使用 SQLite 移除标签"""
        try:
            tag_ids = []
            for tag in tags:
                row = self._local_db.execute(
                    "SELECT id FROM tags WHERE name = ?", (tag,)
                ).fetchone()
                if row:
                    tag_ids.append(row[0])

            if not tag_ids:
                return {"success": False, "message": "未找到指定的标签"}

            removed = 0
            for file_path in file_paths:
                for tag_id in tag_ids:
                    cursor = self._local_db.execute(
                        "DELETE FROM file_tags WHERE file_path = ? AND tag_id = ?",
                        (file_path, tag_id)
                    )
                    removed += cursor.rowcount

            # 清理无引用的孤立标签
            self._local_db.execute("""
                DELETE FROM tags WHERE id NOT IN (
                    SELECT DISTINCT tag_id FROM file_tags
                )
            """)
            self._local_db.commit()

            return {
                "success": True,
                "message": f"成功移除 {removed} 个标签关联"
            }
        except sqlite3.Error as e:
            return {"success": False, "message": f"数据库错误: {e}"}

    def get_tags(self, file_path: str) -> List[str]:
        """获取文件的所有标签"""
        return self._get_tags_local(file_path)

    def get_tags_batch(self, file_paths: List[str]) -> dict:
        """批量获取多个文件的标签（一次 SQL 查询）"""
        if not file_paths:
            return {}
        result = {fp: [] for fp in file_paths}
        try:
            placeholders = ','.join('?' * len(file_paths))
            rows = self._local_db.execute(f"""
                SELECT ft.file_path, t.name FROM tags t
                JOIN file_tags ft ON t.id = ft.tag_id
                WHERE ft.file_path IN ({placeholders})
                ORDER BY t.name
            """, tuple(file_paths)).fetchall()
            for fp, tag in rows:
                result.setdefault(fp, []).append(tag)
        except sqlite3.Error:
            pass
        return result

    def update_path(self, old_path: str, new_path: str) -> bool:
        """重命名/移动文件后更新标签中的文件路径"""
        try:
            self._local_db.execute(
                "UPDATE file_tags SET file_path = ? WHERE file_path = ?",
                (new_path, old_path)
            )
            self._local_db.commit()
            return True
        except sqlite3.Error:
            return False

    def _get_tags_local(self, file_path: str) -> List[str]:
        """使用 SQLite 获取文件标签"""
        try:
            rows = self._local_db.execute("""
                SELECT t.name FROM tags t
                JOIN file_tags ft ON t.id = ft.tag_id
                WHERE ft.file_path = ?
                ORDER BY t.name
            """, (file_path,)).fetchall()
            return [row[0] for row in rows]
        except sqlite3.Error:
            return []

    def get_all_tags(self) -> List[str]:
        """获取所有已使用的标签"""
        return self._get_all_tags_local()

    def _get_all_tags_local(self) -> List[str]:
        """使用 SQLite 获取所有标签"""
        try:
            rows = self._local_db.execute(
                "SELECT name FROM tags ORDER BY name"
            ).fetchall()
            return [row[0] for row in rows]
        except sqlite3.Error:
            return []

    def search_by_tag(self, tag: str) -> List[str]:
        """查找具有某标签的所有文件"""
        return self._search_by_tag_local(tag)

    def _search_by_tag_local(self, tag: str) -> List[str]:
        """使用 SQLite 按标签搜索"""
        try:
            rows = self._local_db.execute("""
                SELECT ft.file_path FROM file_tags ft
                JOIN tags t ON t.id = ft.tag_id
                WHERE t.name = ?
                ORDER BY ft.file_path
            """, (tag,)).fetchall()
            return [row[0] for row in rows]
        except sqlite3.Error:
            return []

    # ============ 标签管理操作 ============

    def delete_tag(self, tag_name: str) -> dict:
        """删除标签本身及所有文件关联"""
        try:
            row = self._local_db.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()
            if not row:
                return {"success": False, "message": f"标签 '{tag_name}' 不存在"}

            tag_id = row[0]

            count_row = self._local_db.execute(
                "SELECT COUNT(*) FROM file_tags WHERE tag_id = ?", (tag_id,)
            ).fetchone()
            removed_count = count_row[0] if count_row else 0

            self._local_db.execute(
                "DELETE FROM file_tags WHERE tag_id = ?", (tag_id,)
            )
            self._local_db.execute(
                "DELETE FROM tags WHERE id = ?", (tag_id,)
            )
            self._local_db.commit()

            return {
                "success": True,
                "message": f"标签 '{tag_name}' 已删除，移除了 {removed_count} 个文件关联",
                "removed_associations": removed_count
            }
        except sqlite3.Error as e:
            return {"success": False, "message": f"数据库错误: {e}"}

    def rename_tag(self, old_name: str, new_name: str) -> dict:
        """重命名标签"""
        if not new_name or not new_name.strip():
            return {"success": False, "message": "新标签名不能为空"}

        new_name = new_name.strip()

        try:
            row = self._local_db.execute(
                "SELECT id FROM tags WHERE name = ?", (old_name,)
            ).fetchone()
            if not row:
                return {"success": False, "message": f"标签 '{old_name}' 不存在"}

            existing = self._local_db.execute(
                "SELECT id FROM tags WHERE name = ?", (new_name,)
            ).fetchone()
            if existing:
                return {"success": False, "message": f"标签 '{new_name}' 已存在"}

            self._local_db.execute(
                "UPDATE tags SET name = ? WHERE name = ?", (new_name, old_name)
            )
            self._local_db.commit()

            return {
                "success": True,
                "message": f"标签 '{old_name}' 已重命名为 '{new_name}'"
            }
        except sqlite3.Error as e:
            return {"success": False, "message": f"数据库错误: {e}"}

    # ============ 生命周期 ============

    def close(self):
        """关闭数据库连接"""
        if self._local_db:
            self._local_db.close()
            self._local_db = None
