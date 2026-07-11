from everything_search import EverythingSearch
es = EverythingSearch()

print("=== path:Candydoll ext:jpg ===")
r1 = es.search('path:Candydoll ext:jpg', apply_filters=False, max_results=10)
print(f"结果: {r1['total']}个")
for i in r1['results'][:5]:
    print(f"  {i['name']}")

print("\n=== path:Candydoll ===")
r2 = es.search('path:Candydoll', apply_filters=False, max_results=10)
print(f"结果: {r2['total']}个")

print("\n=== Candydoll ext:jpg (原查询) ===")
r3 = es.search('Candydoll ext:jpg', apply_filters=False, max_results=10)
print(f"结果: {r3['total']}个")