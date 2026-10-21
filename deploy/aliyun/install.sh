#!/usr/bin/env bash
# 阿里云部署安装脚本：建 venv、装依赖、配 cron
# 用法：bash install.sh /opt/china-hr-policy-tracker
# 前提：仓库代码已就位（服务器访问不了 GitHub 时用 scp 打包上传，见 README）
set -euo pipefail

REPO_DIR="${1:-/opt/china-hr-policy-tracker}"
CRON_HOUR="${ALIYUN_CRON_HOUR:-23}"   # 默认 UTC 23:00（周一 CI 02:30 之前完成推送）

echo "[1/3] 建 venv + 依赖"
cd "$REPO_DIR"
python3 -m venv .venv
"$REPO_DIR/.venv/bin/pip" install -q pyyaml requests

echo "[2/3] 配置 cron（每周日/一 UTC ${CRON_HOUR}:00 全量采集）"
# 周一 02:30 CI 会拉阿里云数据，因此这里安排在周日 23:00 与周一 01:00 各跑一次，双保险
cat > /etc/cron.d/china-hr-policy <<EOF
0 ${CRON_HOUR} * * 0   root ${REPO_DIR}/deploy/aliyun/run_aliyun.sh >> /var/log/china-hr-policy-aliyun.log 2>&1
0 1 * * 1              root ${REPO_DIR}/deploy/aliyun/run_aliyun.sh >> /var/log/china-hr-policy-aliyun.log 2>&1
EOF
chmod 644 /etc/cron.d/china-hr-policy
service cron reload 2>/dev/null || systemctl restart cron 2>/dev/null || true

echo "[3/3] 手工跑一次验证（输出会很长，建议重定向日志）"
echo "      试运行：${REPO_DIR}/deploy/aliyun/run_aliyun.sh"
echo "      完成后：若走 web 目录模式，把文件 URL 设为仓库 Secret ALIYUN_DATA_URL；"
echo "      若走 git push 模式，需在服务器环境变量设置 GH_PAT（GitHub 个人访问令牌，仅仓库写权限）"
