#!/usr/bin/env bash
# 一键跑全部检查：核心用例 + 服务自测 + MCP 协议冒烟
# 用法: bash tests/run_all.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
fail=0

echo "== 1/3 核心用例 =="
python3 tests/run_tests.py || fail=1

echo
echo "== 2/3 服务自测 =="
python3 -m chemworkbench_mcp.server --selftest || fail=1

echo
echo "== 3/3 MCP 协议冒烟 =="
python3 tests/mcp_smoke.py 2>&1 | grep -v -E '^\s*(INFO|WARNING)' || fail=1

echo
if [ "$fail" -eq 0 ]; then echo "全部检查通过 ✅"; else echo "有检查未通过 ❌"; fi
exit "$fail"
