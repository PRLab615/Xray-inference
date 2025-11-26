#!/bin/bash
# 快速查看 JSON 文件的脚本

JSON_FILE="test_ceph_output.json"

if [ ! -f "$JSON_FILE" ]; then
    echo "错误: 文件 $JSON_FILE 不存在"
    echo ""
    echo "请先运行测试脚本生成 JSON 文件:"
    echo "  python test_ceph_json.py <taskId>"
    exit 1
fi

echo "=" | head -c 80
echo ""
echo "查看 JSON 文件: $JSON_FILE"
echo "=" | head -c 80
echo ""

# 检查是否有 jq 命令（JSON 格式化工具）
if command -v jq &> /dev/null; then
    echo "使用 jq 格式化显示:"
    echo ""
    # 只显示 CephalometricMeasurements 部分
    jq '.data.CephalometricMeasurements' "$JSON_FILE"
else
    echo "使用 cat 显示（建议安装 jq 以获得更好的格式化）:"
    echo ""
    cat "$JSON_FILE"
fi

echo ""
echo "=" | head -c 80
echo ""
echo "提示:"
echo "  - 安装 jq 以获得更好的 JSON 格式化: apt-get install jq 或 yum install jq"
echo "  - 查看完整文件: cat $JSON_FILE"
echo "  - 查看并编辑: vi $JSON_FILE 或 nano $JSON_FILE"

