---
name: path-priority-search
description: 路径优先搜索策略实现 - 搜索时先匹配路径/文件夹名再搜索单独文件
type: project
---

Faind 项目实现了两层路径优先搜索防御：
1. **AI Agent + 规则降级层**：AGENT_SYSTEM_PROMPT 强调 path: 搜索，_build_everything_query() 对所有关键词默认添加 path: 前缀
2. **搜索引擎层**：everything_search.py 的 search() 方法在结果 < 5 且查询不含 path: 时，自动用 _rewrite_with_path_prefix() 重试并合并去重

**Why:** 用户搜索 "Candydoll" 只返回 1 个结果（文件名匹配），实际有数百个文件在 Candydoll_* 文件夹内。path:Candydoll 可匹配路径返回完整结果集。

**How to apply:** 搜索主题/人名/系列时，确保使用 path: 前缀。_build_everything_query 已默认处理，搜索引擎有自动重试兜底。