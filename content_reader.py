"""
文档内容读取模块
基于 pyxtxt 提取文档文件的纯文本内容，支持开关控制
"""

import logging
import os
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

# 默认支持的文件扩展名白名单
DEFAULT_SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.doc', '.xlsx', '.xls',
    '.pptx', '.ppt', '.txt', '.md', '.rtf',
    '.epub', '.html', '.htm', '.odt', '.ods', '.odp'
}


class ContentReader:
    """文档内容读取器，封装 pyxtxt"""

    def __init__(self, config: dict = None):
        if config is None:
            import config as cfg_module
            config = cfg_module.load_config().get('content_reader', {})
        self.enabled = config.get('enabled', False)
        self.max_chars = config.get('max_chars_per_file', 5000)
        self.supported_extensions = set(
            config.get('supported_formats', DEFAULT_SUPPORTED_EXTENSIONS)
        )

    def toggle(self, enabled: bool):
        """切换开关状态"""
        self.enabled = enabled

    @property
    def is_ready(self) -> bool:
        return self.enabled

    def is_supported(self, file_path: str) -> bool:
        """检查文件扩展名是否在白名单中"""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    def extract_text(self, file_path: str, max_chars: Optional[int] = None) -> str:
        """
        提取文件的纯文本内容
        返回空字符串表示提取失败或不支持
        """
        if not self.enabled:
            logger.debug(f"内容读取器未启用，跳过: {os.path.basename(file_path)}")
            return ""

        if not self.is_supported(file_path):
            logger.debug(f"格式不支持，跳过: {os.path.basename(file_path)}")
            return ""

        try:
            from pyxtxt import xtxt
            import io
            import sys
            # pyxtxt 内部多处 print() 使用了 emoji 字符，在 Windows GBK 终端
            # 会触发 UnicodeEncodeError 导致整个提取崩溃。
            # 临时替换 stdout 和 stderr，捕获后记录到日志
            _stdout, _stderr = sys.stdout, sys.stderr
            captured = io.StringIO()
            sys.stdout = sys.stderr = captured
            try:
                raw_text = xtxt(file_path)
            finally:
                sys.stdout, sys.stderr = _stdout, _stderr
            # 记录 pyxtxt 的输出（用于调试）
            cap_out = captured.getvalue().strip()
            if cap_out:
                logger.debug(f"pyxtxt 输出 [{os.path.basename(file_path)}]: {cap_out[:300]}")

            max_chars = max_chars or self.max_chars
            if raw_text is None:
                logger.info(f"无内容: {os.path.basename(file_path)}")
                return ""
            if not isinstance(raw_text, str):
                raw_text = str(raw_text)
            if not raw_text.strip():
                logger.info(f"内容为空: {os.path.basename(file_path)}")
                return ""
            extracted_len = len(raw_text)
            if extracted_len > max_chars:
                logger.info(f"提取成功(已截断): {os.path.basename(file_path)} "
                           f"({extracted_len} → {max_chars} 字符)")
                return raw_text[:max_chars] + "\n... (内容已截断)"
            logger.info(f"提取成功: {os.path.basename(file_path)} ({extracted_len} 字符)")
            return raw_text
        except ImportError:
            logger.warning("pyxtxt 未安装，无法提取文件内容")
            return ""
        except Exception as e:
            logger.error(f"提取失败: {os.path.basename(file_path)}, 错误: {e}")
            return ""

    def read_content(self, file_path: str, max_chars: Optional[int] = None) -> str:
        """extract_text 的别名，供外部调用"""
        return self.extract_text(file_path, max_chars)

    def extract_batch(self, file_paths: List[str], max_chars: Optional[int] = None) -> dict:
        """批量提取文件内容"""
        if not self.enabled:
            return {path: "" for path in file_paths}
        results = {}
        for path in file_paths:
            results[path] = self.extract_text(path, max_chars)
        return results


def analyze_content_relevance(file_contents: dict, user_query: str,
                               ai_client, model: str, max_tokens: int = 1000) -> list:
    """
    使用 AI 分析文件内容与用户查询的相关性
    :param file_contents: {file_path: text_content}
    :param user_query: 用户原始查询
    :param ai_client: OpenAI 客户端实例
    :param model: 模型名
    :param max_tokens: 最大 token 数
    :return: [{"file_path": str, "relevance": float, "reason": str, "snippet": str}, ...]
    """
    if not file_contents or not ai_client:
        return []

    # 只取有内容的文件
    valid = {fp: txt for fp, txt in file_contents.items() if txt and len(txt) > 10}
    if not valid:
        return []

    # 构造给 AI 的分析请求
    files_info = []
    for fp, txt in valid.items():
        fname = Path(fp).name
        snippet = txt[:800]
        files_info.append(f"--- {fname} ---\n路径: {fp}\n内容摘要: {snippet}\n")

    prompt = f"""用户想找: {user_query}

以下是搜索到的文件及其内容片段，请分析哪些文件与用户需求真正相关:

{chr(10).join(files_info)}

请以 JSON 数组格式返回，只包含有相关性的文件（相关性 > 0），按相关性从高到低排序:
[{{"file_path": "完整路径", "file_name": "文件名", "relevance": 0.0~1.0, "reason": "简短理由", "snippet": "最相关的片段(50字内)"}}]

规则:
- 文件名完全无关但内容相关的，也要纳入（给高分）
- 文件名相关但内容完全无关的，排除（给0分）
- 同一文档是否直接讨论用户要找的主题
- 只返回 JSON 数组，不要任何其他文字"""

    try:
        response = ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是文件内容分析专家。只输出JSON数组，不要输出任何其他内容。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or "[]"
        # 清理可能的 markdown 代码块包裹
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        results = json.loads(content)
        if isinstance(results, list):
            return results
    except Exception as e:
        logger.error(f"内容相关性分析失败: {e}")

    return []


def _json_loads_safe(s: str):
    """兼容的 JSON 加载"""
    import json
    return json.loads(s)
