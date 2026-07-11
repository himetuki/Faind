"""快速集成测试"""
from everything_search import EverythingSearch
from ai_parser import SearchAgent
from tag_manager import TagManager
from config import load_config

print("=== 配置模块 ===")
cfg = load_config()
print(f"配置域: {list(cfg.keys())}")
print(f"AI max_tokens: {cfg.get('ai', {}).get('max_tokens')}")

print("\n=== Everything搜索模块 ===")
es = EverythingSearch()
print(f"DLL加载: {es._initialized}")
print(f"使用CLI: {es._use_cli}")
print(f"CLI降级路径: {es._es_cli_path}")
print(f"有CLI降级: {es.has_cli_fallback}")

detail = es.get_status_detail()
print(f"详细状态: dll={detail['dll_loaded']}, cli={detail['cli_available']}, running={detail['everything_running']}")

print("\n=== 标签管理模块 ===")
tm = TagManager()
print(f"使用SQLite: {tm._use_local_db}")

print("\n=== SearchAgent 模块 ===")
agent = SearchAgent(es, tm)
print(f"AI可用: {agent.ai_available}")
print(f"AI模型: {agent.model}")
print(f"max_tokens: {agent.max_tokens}")

# 测试规则降级搜索
print("\n--- 规则降级搜索测试 ---")
result = agent.process("最近的Python文件")
print(f"搜索成功: {result['success']}")
print(f"结果总数: {result['total']}")
print(f"消息: {result.get('message', '')}")
if result.get('results'):
    print(f"首个结果: {result['results'][0]['name']}")

# 测试标签操作快速路径
print("\n--- 标签快速路径测试 ---")
tm.add_tags(["test_file.txt"], ["测试标签"])
tag_result = agent.process("添加标签 重要", {"selected_files": ["test_file.txt"]})
print(f"标签操作成功: {tag_result.get('success')}")
print(f"消息: {tag_result.get('message', '')}")

# 测试兼容旧接口
print("\n--- 兼容旧接口测试 ---")
intent = agent.parse_intent("找本周修改的PDF")
print(f"意图: {intent}")

tags = agent.suggest_tags({"name": "report.pdf", "extension": "pdf", "path": "C:/documents"})
print(f"推荐标签: {tags}")

tm.close()
print("\n=== 所有模块测试完成 ===")