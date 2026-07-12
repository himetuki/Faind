"""
AI 意图解析的本地缓存模块
避免对相同或相似输入重复调用 AI API
"""

import json
import hashlib
import re
import time
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Dict, Any


class AICache:
    """AI 意图解析的本地缓存（LRU 淘汰，JSON 文件持久化）"""

    def __init__(self, cache_dir: str = "~/.faind", max_entries: int = 1000):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "ai_cache.json"
        self.max_entries = max_entries
        self.cache: Dict[str, Any] = self._load()

    def _load(self) -> dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        """保存缓存，超出上限时淘汰最旧条目"""
        if len(self.cache) > self.max_entries:
            ordered = OrderedDict(self.cache)
            while len(ordered) > self.max_entries:
                ordered.popitem(last=False)
            self.cache = dict(ordered)
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    def _normalize(self, text: str) -> str:
        """归一化用户输入，提高缓存命中率"""
        stopwords = ['帮我', '请', '一下', '那个', '这个', '看看', '找找', '我要', '我想', '帮忙']
        for word in stopwords:
            text = text.replace(word, '')
        text = re.sub(r'[，,。.！!？?、:：；;]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _hash(self, text: str) -> str:
        normalized = self._normalize(text)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def get(self, user_input: str) -> Optional[dict]:
        """查询缓存，命中时移到末尾（LRU）"""
        key = self._hash(user_input)
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return {k: v for k, v in value.items() if not k.startswith('_')}
        return None

    def set(self, user_input: str, value: dict):
        """写入缓存"""
        key = self._hash(user_input)
        value['_cached_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        self.cache[key] = value
        self._save()

    def clear(self):
        """清空缓存"""
        self.cache = {}
        self._save()

    def get_stats(self) -> dict:
        return {
            "total_entries": len(self.cache),
            "max_entries": self.max_entries,
            "cache_file": str(self.cache_file)
        }


class NotRelevantCache:
    """非本项缓存：记录用户对特定搜索词标记为"不相关"的文件路径
    后续相似搜索自动过滤这些文件"""

    def __init__(self, cache_dir: str = "~/.faind", max_entries: int = 5000):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "not_relevant_cache.json"
        self.max_entries = max_entries
        self.cache: Dict[str, list] = self._load()

    def _load(self) -> dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        total = sum(len(v) for v in self.cache.values())
        if total > self.max_entries:
            ordered = OrderedDict(self.cache)
            while sum(len(v) for v in ordered.values()) > self.max_entries:
                ordered.popitem(last=False)
            self.cache = dict(ordered)
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    def _normalize(self, text: str) -> str:
        stopwords = ['帮我', '请', '一下', '那个', '这个', '看看', '找找', '我要', '我想', '帮忙']
        for word in stopwords:
            text = text.replace(word, '')
        text = re.sub(r'[，,。.！!？?、:：；;]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _hash(self, text: str) -> str:
        normalized = self._normalize(text)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def mark_not_relevant(self, query: str, file_path: str) -> bool:
        """标记文件为当前搜索词的非本项"""
        if not query or not file_path:
            return False
        key = self._hash(query)
        if key not in self.cache:
            self.cache[key] = []
        normalized_path = file_path.replace('\\', '/')
        if normalized_path not in self.cache[key]:
            self.cache[key].append(normalized_path)
            self._save()
            return True
        return False

    def is_not_relevant(self, query: str, file_path: str) -> bool:
        """判断文件是否已被标记为当前搜索词的非本项"""
        if not query or not file_path:
            return False
        key = self._hash(query)
        normalized_path = file_path.replace('\\', '/')
        return normalized_path in self.cache.get(key, [])

    def get_blocked_paths(self, query: str) -> set:
        """获取当前搜索词下所有被屏蔽的文件路径集合"""
        if not query:
            return set()
        key = self._hash(query)
        return set(p.replace('\\', '/') for p in self.cache.get(key, []))

    def get_blocked(self, query: str) -> list:
        """获取当前搜索词下被屏蔽的文件路径列表"""
        if not query:
            return []
        key = self._hash(query)
        return list(self.cache.get(key, []))

    def unmark(self, query: str, file_path: str = None) -> bool:
        """取消非本项标记。file_path 为 None 时清除整个搜索词的所有标记"""
        if not query:
            return False
        key = self._hash(query)
        if file_path is None:
            if key in self.cache:
                del self.cache[key]
                self._save()
                return True
            return False
        if key in self.cache:
            normalized_path = file_path.replace('\\', '/')
            if normalized_path in self.cache[key]:
                self.cache[key].remove(normalized_path)
                if not self.cache[key]:
                    del self.cache[key]
                self._save()
                return True
        return False

    def clear_all(self):
        """清空所有非本项缓存"""
        self.cache = {}
        self._save()
