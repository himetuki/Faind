"""
Faind 标签管理模块
SQLite 始终作为主存储，TMSU 作为可选的同步目标
支持双向同步：SQLite ↔ TMSU
"""

import subprocess
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

import config


class TagManager:
    """标签管理器：SQLite 主存储 + TMSU 双向同步"""

    def __init__(self):
        self.tmsu_path = ""
        self.tmsu_db_path = ""
        self._tmsu_available = False
        self._local_db = None
        self._init_tag_system()

    def _init_tag_system(self):
        """初始化标签系统：SQLite 始终启用，TMSU 可选同步"""
        # 1. 始终初始化 SQLite 主存储
        self._init_local_db()
        print("[TagManager] SQLite 标签存储已初始化")

        # 2. 检测 TMSU 可用性
        cfg = config.load_config()
        tmsu_cfg = cfg.get("tmsu", {})

        # 自动探测 TMSU 路径
        self.tmsu_path = config.resolve_tmsu_path()
        if not self.tmsu_path:
            # 回退到配置中的路径
            self.tmsu_path = tmsu_cfg.get("executable_path", "tmsu.exe")

        self.tmsu_db_path = tmsu_cfg.get("db_path", "")

        if self._check_tmsu_available():
            self._tmsu_available = True
            print(f"[TagManager] TMSU 可用: {self.tmsu_path}，双存储同步模式")
        else:
            self._tmsu_available = False
            print("[TagManager] TMSU 不可用，仅使用 SQLite 存储")

    def _check_tmsu_available(self) -> bool:
        """检查 TMSU 是否可用"""
        if not self.tmsu_path:
            return False
        try:
            result = subprocess.run(
                [self.tmsu_path, "--version"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace"
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def _init_local_db(self):
        """初始化本地 SQLite 标签数据库"""
        db_dir = config._get_config_dir()
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

    # ============ 属性 ============

    @property
    def is_tmsu_available(self) -> bool:
        """TMSU 是否可用"""
        return self._tmsu_available

    @property
    def storage_mode(self) -> str:
        """当前存储模式描述"""
        if self._tmsu_available:
            return "sqlite+tmsu"
        return "sqlite"

    # ============ 核心操作（SQLite 主存储） ============

    def add_tags(self, file_paths: List[str], tags: List[str]) -> dict:
        """
        为文件添加标签（SQLite 主存储 + TMSU 同步）
        """
        if not file_paths or not tags:
            return {"success": False, "message": "文件路径或标签为空", "failed_files": []}

        # 1. 写入 SQLite 主存储
        result = self._add_tags_local(file_paths, tags)

        # 2. 如果 TMSU 可用，同步写入
        if result["success"] and self._tmsu_available:
            self._sync_add_to_tmsu(file_paths, tags)

        return result

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

    def _sync_add_to_tmsu(self, file_paths: List[str], tags: List[str]):
        """将添加操作同步到 TMSU"""
        for file_path in file_paths:
            try:
                cmd = [self.tmsu_path, "tag", "--none"]
                if self.tmsu_db_path:
                    cmd.extend(["--database", self.tmsu_db_path])
                cmd.append(file_path)
                cmd.extend(tags)

                subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace"
                )
            except Exception as e:
                print(f"[TagManager] TMSU 同步添加失败 ({file_path}): {e}")

    def remove_tags(self, file_paths: List[str], tags: List[str]) -> dict:
        """
        移除文件标签（SQLite 主存储 + TMSU 同步）
        """
        if not file_paths or not tags:
            return {"success": False, "message": "文件路径或标签为空"}

        # 1. 从 SQLite 移除
        result = self._remove_tags_local(file_paths, tags)

        # 2. 如果 TMSU 可用，同步移除
        if result["success"] and self._tmsu_available:
            self._sync_remove_from_tmsu(file_paths, tags)

        return result

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

    def _sync_remove_from_tmsu(self, file_paths: List[str], tags: List[str]):
        """将移除操作同步到 TMSU"""
        for file_path in file_paths:
            try:
                cmd = [self.tmsu_path, "untag"]
                if self.tmsu_db_path:
                    cmd.extend(["--database", self.tmsu_db_path])
                cmd.append(file_path)
                cmd.extend(tags)

                subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace"
                )
            except Exception as e:
                print(f"[TagManager] TMSU 同步移除失败 ({file_path}): {e}")

    def get_tags(self, file_path: str) -> List[str]:
        """
        获取文件的所有标签（从 SQLite 主存储读取）
        """
        return self._get_tags_local(file_path)

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
        """
        获取所有已使用的标签（从 SQLite 主存储读取）
        """
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
        """
        查找具有某标签的所有文件（从 SQLite 主存储读取）
        """
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
        """
        删除标签本身及所有文件关联
        :param tag_name: 标签名
        :return: {"success": bool, "message": str, "removed_associations": int}
        """
        try:
            # 获取标签 ID
            row = self._local_db.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()
            if not row:
                return {"success": False, "message": f"标签 '{tag_name}' 不存在"}

            tag_id = row[0]

            # 统计关联数
            count_row = self._local_db.execute(
                "SELECT COUNT(*) FROM file_tags WHERE tag_id = ?", (tag_id,)
            ).fetchone()
            removed_count = count_row[0] if count_row else 0

            # 删除所有关联
            self._local_db.execute(
                "DELETE FROM file_tags WHERE tag_id = ?", (tag_id,)
            )
            # 删除标签本身
            self._local_db.execute(
                "DELETE FROM tags WHERE id = ?", (tag_id,)
            )
            self._local_db.commit()

            # 同步到 TMSU
            if self._tmsu_available and removed_count > 0:
                self._sync_delete_tag_to_tmsu(tag_name)

            return {
                "success": True,
                "message": f"标签 '{tag_name}' 已删除，移除了 {removed_count} 个文件关联",
                "removed_associations": removed_count
            }
        except sqlite3.Error as e:
            return {"success": False, "message": f"数据库错误: {e}"}

    def rename_tag(self, old_name: str, new_name: str) -> dict:
        """
        重命名标签
        :param old_name: 原标签名
        :param new_name: 新标签名
        :return: {"success": bool, "message": str}
        """
        if not new_name or not new_name.strip():
            return {"success": False, "message": "新标签名不能为空"}

        new_name = new_name.strip()

        try:
            # 检查原标签是否存在
            row = self._local_db.execute(
                "SELECT id FROM tags WHERE name = ?", (old_name,)
            ).fetchone()
            if not row:
                return {"success": False, "message": f"标签 '{old_name}' 不存在"}

            # 检查新名称是否已存在
            existing = self._local_db.execute(
                "SELECT id FROM tags WHERE name = ?", (new_name,)
            ).fetchone()
            if existing:
                return {"success": False, "message": f"标签 '{new_name}' 已存在"}

            # 重命名
            self._local_db.execute(
                "UPDATE tags SET name = ? WHERE name = ?", (new_name, old_name)
            )
            self._local_db.commit()

            # 同步到 TMSU：先删除旧标签，再添加新标签
            if self._tmsu_available:
                self._sync_rename_tag_to_tmsu(old_name, new_name)

            return {
                "success": True,
                "message": f"标签 '{old_name}' 已重命名为 '{new_name}'"
            }
        except sqlite3.Error as e:
            return {"success": False, "message": f"数据库错误: {e}"}

    def _sync_delete_tag_to_tmsu(self, tag_name: str):
        """将标签删除操作同步到 TMSU"""
        try:
            # 获取 TMSU 中该标签下的所有文件
            files = self._search_by_tag_tmsu(tag_name)
            for file_path in files:
                cmd = [self.tmsu_path, "untag"]
                if self.tmsu_db_path:
                    cmd.extend(["--database", self.tmsu_db_path])
                cmd.append(file_path)
                cmd.append(tag_name)
                subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace"
                )
        except Exception as e:
            print(f"[TagManager] TMSU 同步删除标签失败 ({tag_name}): {e}")

    def _sync_rename_tag_to_tmsu(self, old_name: str, new_name: str):
        """将标签重命名操作同步到 TMSU"""
        try:
            # TMSU 没有重命名命令，需要先给所有文件添加新标签，再删除旧标签
            files = self._search_by_tag_tmsu(old_name)
            for file_path in files:
                # 添加新标签
                cmd_add = [self.tmsu_path, "tag", "--none"]
                if self.tmsu_db_path:
                    cmd_add.extend(["--database", self.tmsu_db_path])
                cmd_add.append(file_path)
                cmd_add.append(new_name)
                subprocess.run(
                    cmd_add, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace"
                )
                # 删除旧标签
                cmd_rm = [self.tmsu_path, "untag"]
                if self.tmsu_db_path:
                    cmd_rm.extend(["--database", self.tmsu_db_path])
                cmd_rm.append(file_path)
                cmd_rm.append(old_name)
                subprocess.run(
                    cmd_rm, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace"
                )
        except Exception as e:
            print(f"[TagManager] TMSU 同步重命名标签失败 ({old_name}->{new_name}): {e}")

    # ============ TMSU 同步操作 ============

    def sync_from_tmsu(self) -> dict:
        """
        从 TMSU 导入所有标签数据到 SQLite（合并，不覆盖）
        :return: {"success": bool, "message": str, "imported_tags": int, "imported_associations": int}
        """
        if not self._tmsu_available:
            return {"success": False, "message": "TMSU 不可用，无法同步", "imported_tags": 0, "imported_associations": 0}

        try:
            # 1. 获取 TMSU 所有标签
            tmsu_tags = self._get_all_tags_tmsu()
            if not tmsu_tags:
                return {"success": True, "message": "TMSU 中无标签数据", "imported_tags": 0, "imported_associations": 0}

            # 2. 获取 TMSU 所有文件-标签关联
            imported_tags = 0
            imported_associations = 0

            for tag in tmsu_tags:
                # 插入标签（如已存在则跳过）
                cursor = self._local_db.execute(
                    "INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,)
                )
                if cursor.rowcount > 0:
                    imported_tags += 1

                # 获取该标签下的所有文件
                tmsu_files = self._search_by_tag_tmsu(tag)
                tag_id = self._local_db.execute(
                    "SELECT id FROM tags WHERE name = ?", (tag,)
                ).fetchone()[0]

                for file_path in tmsu_files:
                    try:
                        cursor = self._local_db.execute(
                            "INSERT OR IGNORE INTO file_tags (file_path, tag_id, source) VALUES (?, ?, 'tmsu')",
                            (file_path, tag_id)
                        )
                        if cursor.rowcount > 0:
                            imported_associations += 1
                    except sqlite3.Error:
                        pass

            self._local_db.commit()

            msg = f"从 TMSU 导入完成：{imported_tags} 个新标签，{imported_associations} 个新关联"
            print(f"[TagManager] {msg}")
            return {
                "success": True,
                "message": msg,
                "imported_tags": imported_tags,
                "imported_associations": imported_associations
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"TMSU 同步失败: {e}",
                "imported_tags": 0,
                "imported_associations": 0
            }

    def sync_to_tmsu(self) -> dict:
        """
        将 SQLite 中所有标签数据导出到 TMSU（合并，不覆盖）
        :return: {"success": bool, "message": str, "exported_tags": int, "exported_associations": int}
        """
        if not self._tmsu_available:
            return {"success": False, "message": "TMSU 不可用，无法同步", "exported_tags": 0, "exported_associations": 0}

        try:
            # 获取 TMSU 已有的标签（避免重复）
            existing_tmsu_tags = set(self._get_all_tags_tmsu())

            # 获取 SQLite 所有标签
            all_tags = self._get_all_tags_local()
            exported_tags = 0
            exported_associations = 0

            for tag in all_tags:
                is_new_tag = tag not in existing_tmsu_tags

                # 获取该标签下的所有文件
                files = self._search_by_tag_local(tag)

                for file_path in files:
                    # 获取该文件在 TMSU 中已有的标签
                    existing_file_tags = set(self._get_tags_tmsu(file_path))

                    if tag not in existing_file_tags:
                        # 同步单个标签到 TMSU
                        try:
                            cmd = [self.tmsu_path, "tag", "--none"]
                            if self.tmsu_db_path:
                                cmd.extend(["--database", self.tmsu_db_path])
                            cmd.append(file_path)
                            cmd.append(tag)

                            result = subprocess.run(
                                cmd, capture_output=True, text=True, timeout=30,
                                encoding="utf-8", errors="replace"
                            )
                            if result.returncode == 0:
                                exported_associations += 1
                                if is_new_tag:
                                    exported_tags += 1
                                    is_new_tag = False  # 只计一次
                        except Exception as e:
                            print(f"[TagManager] 导出标签到 TMSU 失败 ({file_path}, {tag}): {e}")

            msg = f"导出到 TMSU 完成：{exported_tags} 个新标签，{exported_associations} 个新关联"
            print(f"[TagManager] {msg}")
            return {
                "success": True,
                "message": msg,
                "exported_tags": exported_tags,
                "exported_associations": exported_associations
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"导出到 TMSU 失败: {e}",
                "exported_tags": 0,
                "exported_associations": 0
            }

    def get_sync_status(self) -> dict:
        """
        获取同步状态信息
        """
        sqlite_tags = len(self._get_all_tags_local())
        sqlite_associations = self._count_local_associations()

        tmsu_tags = 0
        tmsu_associations = 0
        if self._tmsu_available:
            tmsu_tags = len(self._get_all_tags_tmsu())
            tmsu_associations = self._count_tmsu_associations()

        return {
            "tmsu_available": self._tmsu_available,
            "tmsu_path": self.tmsu_path,
            "storage_mode": self.storage_mode,
            "sqlite_tags": sqlite_tags,
            "sqlite_associations": sqlite_associations,
            "tmsu_tags": tmsu_tags,
            "tmsu_associations": tmsu_associations
        }

    def _count_local_associations(self) -> int:
        """统计 SQLite 中的标签关联数"""
        try:
            row = self._local_db.execute("SELECT COUNT(*) FROM file_tags").fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0

    def _count_tmsu_associations(self) -> int:
        """统计 TMSU 中的标签关联数"""
        try:
            count = 0
            tags = self._get_all_tags_tmsu()
            for tag in tags:
                files = self._search_by_tag_tmsu(tag)
                count += len(files)
            return count
        except Exception:
            return 0

    # ============ TMSU 原始操作（仅用于同步） ============

    def _get_tags_tmsu(self, file_path: str) -> List[str]:
        """使用 TMSU 获取文件标签"""
        try:
            cmd = [self.tmsu_path, "tags"]
            if self.tmsu_db_path:
                cmd.extend(["--database", self.tmsu_db_path])
            cmd.append(file_path)

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace"
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if ":" in output:
                    tags_str = output.split(":", 1)[1].strip()
                    if tags_str:
                        return [t.strip() for t in tags_str.split() if t.strip()]
            return []
        except Exception:
            return []

    def _get_all_tags_tmsu(self) -> List[str]:
        """使用 TMSU 获取所有标签"""
        try:
            cmd = [self.tmsu_path, "tags"]
            if self.tmsu_db_path:
                cmd.extend(["--database", self.tmsu_db_path])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace"
            )

            if result.returncode == 0:
                tags = set()
                for line in result.stdout.strip().split("\n"):
                    if ":" in line:
                        tags_str = line.split(":", 1)[1].strip()
                        for tag in tags_str.split():
                            if tag.strip():
                                tags.add(tag.strip())
                return sorted(tags)
            return []
        except Exception:
            return []

    def _search_by_tag_tmsu(self, tag: str) -> List[str]:
        """使用 TMSU 按标签搜索"""
        try:
            cmd = [self.tmsu_path, "files"]
            if self.tmsu_db_path:
                cmd.extend(["--database", self.tmsu_db_path])
            cmd.append(tag)

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace"
            )

            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
            return []
        except Exception:
            return []

    # ============ 生命周期 ============

    def close(self):
        """关闭数据库连接"""
        if self._local_db:
            self._local_db.close()
            self._local_db = None