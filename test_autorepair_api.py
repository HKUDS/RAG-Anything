"""制造智能体 API 全面测试"""
import urllib.request
import json
import sys

BASE = "http://localhost:8001"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoyLCJ1c2VybmFtZSI6InRlc3RlciIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzgxMzMxNzg1LCJpYXQiOjE3ODEyNDUzODV9.qs5tiI--KVwKbSQDNAyG0JOtKDI65qZ9c6AGVW9NDy0"

def api(path, method="GET", body=None, timeout=30):
    try:
        url = f"{BASE}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

results = {}

# 1. KB List
print("=== 1. KB List ===")
status, data = api("/api/kb/list")
results["kb_list"] = {"status": status, "data": data}
if "knowledge_bases" in data:
    print(f"  Status: {status}")
    print(f"  活跃KB: {data.get('active', '?')}")
    for kb in data.get("knowledge_bases", []):
        print(f"  - {kb['name']}: {kb.get('doc_count','?')} 文档, {kb.get('status','?')}")
else:
    print(f"  ERROR: {data}")

# 2. Manufacturing QA (AgenticRAG multi-step reasoning)
print("\n=== 2. Manufacturing QA (kb=default) ===")
status, data = api("/api/autorepair/qa?kb=default", "POST",
    {"query": "请介绍一下智能制造中的五大核心模块", "context": {}}, timeout=120)
results["qa"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "answer" in data:
    ans = data["answer"]
    print(f"  Answer: {ans[:200]}..." if len(ans) > 200 else f"  Answer: {ans}")
    print(f"  Citations: {len(data.get('citations', []))}")
    print(f"  Images: {len(data.get('related_images', []))}")
    trace = data.get('trace', [])
    print(f"  Trace steps: {len(trace)}")
    for step in trace[:3]:
        print(f"    Step {step.get('step')}: action={step.get('action')} ({step.get('elapsed_ms', 0):.0f}ms)")
    print(f"  Confidence: {round(data.get('confidence', 0) * 100)}%")
    print(f"  Time: {data.get('processing_time_ms', '?')}ms")
    # Verify new fields exist
    assert 'trace' in data, "Missing 'trace' in AgenticRAG response"
    print("  ✅ AgenticRAG trace field verified")
else:
    print(f"  ERROR: {data}")

# 3. Manufacturing QA with kb=111 (if exists)
print("\n=== 3. Manufacturing QA (kb=111) ===")
status, data = api("/api/autorepair/qa?kb=111", "POST",
    {"query": "基于MobileNetV3的系统包含哪些功能", "context": {}}, timeout=120)
results["qa_111"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "answer" in data:
    ans = data["answer"]
    print(f"  Answer: {ans[:200]}..." if len(ans) > 200 else f"  Answer: {ans}")
    trace = data.get('trace', [])
    print(f"  Trace steps: {len(trace)}")
    print(f"  Confidence: {round(data.get('confidence', 0) * 100)}%")
else:
    print(f"  ERROR: {data}")

# 4. Code Parse
print("\n=== 4. Code Parse ===")
status, data = api("/api/autorepair/code/parse?kb=default", "POST",
    {"query": "G00 X10 Y20 Z5\nG01 Z-15 F500", "language": "gcode"}, timeout=30)
results["code"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "analysis" in data:
    print(f"  Analysis: {data.get('analysis', '')[:150]}")
    print(f"  Risks: {data.get('risks', [])}")
else:
    print(f"  Response keys: {list(data.keys())}")
    print(f"  Response: {json.dumps(data, ensure_ascii=False)[:300]}")

# 5. Fault Diagnosis
print("\n=== 5. Fault Diagnosis ===")
status, data = api("/api/autorepair/fault-diagnosis?kb=default", "POST",
    {"query": "数控机床主轴启动后剧烈振动，加工精度超标", "context": {}}, timeout=30)
results["diagnosis"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "diagnosis" in data:
    diag = data["diagnosis"]
    print(f"  Diagnosis: {diag[:200]}..." if len(diag) > 200 else f"  Diagnosis: {diag}")
    print(f"  Possible causes: {data.get('possible_causes', [])}")
    print(f"  Suggestions: {data.get('suggestions', [])}")
else:
    print(f"  Response keys: {list(data.keys())}")
    print(f"  Response: {json.dumps(data, ensure_ascii=False)[:300]}")

# 6. Dashboard
print("\n=== 6. Dashboard ===")
status, data = api("/api/autorepair/dashboard?kb=default", timeout=15)
results["dashboard"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "usage_stats" in data:
    u = data["usage_stats"]
    print(f"  Usage: total={u.get('total_queries','?')}, today={u.get('today','?')}")
elif "detail" in data:
    print(f"  ERROR: {data['detail']}")
else:
    print(f"  Keys: {list(data.keys())[:8]}")

# 7. Knowledge Graph Summary
print("\n=== 7. Knowledge Graph Summary ===")
status, data = api("/api/autorepair/knowledge-graph/summary?kb=default", timeout=15)
results["kg"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "total_nodes" in data:
    print(f"  Nodes: {data.get('total_nodes','?')}, Edges: {data.get('total_edges','?')}")
elif "detail" in data:
    print(f"  ERROR: {data['detail']}")
else:
    print(f"  Keys: {list(data.keys())}")

# 8. Fault Cases Stats
print("\n=== 8. Fault Cases Stats ===")
status, data = api("/api/autorepair/fault-cases/stats?kb=default", timeout=15)
results["faults"] = {"status": status, "data": data}
print(f"  Status: {status}")
if "total_cases" in data:
    print(f"  Total cases: {data.get('total_cases','?')}")
    print(f"  Equipment types: {data.get('equipment_types', {})}")
elif "detail" in data:
    print(f"  ERROR: {data['detail']}")
else:
    print(f"  Keys: {list(data.keys())}")

# Summary
print("\n" + "=" * 50)
print("测试汇总")
print("=" * 50)
for name, r in results.items():
    s = r["status"]
    d = r["data"]
    has_error = "detail" in d and s >= 400
    ok = not has_error and s == 200
    print(f"  {name:15s}  HTTP {s}  {'✅' if ok else '❌' if has_error else '⚠️'}")
print("=" * 50)
