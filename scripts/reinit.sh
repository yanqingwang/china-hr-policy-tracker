#!/bin/bash
# 数据重新初始化：清空 state/items → 全量采集 → 生成干净数据 → 推送 GitHub
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
REPO=/www/china-hr-si-phf-policy/repo
PY=/www/china-hr-si-phf-policy/venv/bin/python
TOKEN=$(cat /root/.config/hr-si-phf-policy/github_pat)
REMOTE="https://x-access-token:${TOKEN}@github.com/yanqingwang/china-hr-si-phf-policy-tracker.git"
LOG=/var/log/hr-policy-reinit.log

echo "=== $(date -u +%FT%TZ) reinit start ===" >> "$LOG"
cd "$REPO"

# 1) 同步到最新 main
git fetch origin main >> "$LOG" 2>&1
git reset --hard origin/main >> "$LOG" 2>&1
git clean -fd >> "$LOG" 2>&1 || true
git checkout -f main >> "$LOG" 2>&1

# 2) 初始化：清空 dedup state 与 items（旧噪声数据不再进 state，避免污染）
echo '{"seen": []}' > data/state.json
echo '[]' > data/items.json
echo "state/items 已清空" >> "$LOG"

# 3) 全量采集（多页扫描 + 详情）
"$PY" -m src.discover --full --detail >> "$LOG" 2>&1
cp data/discovery-aliyun.json /tmp/aliyun-reinit.json

# 4) 推送 discovery-aliyun.json 到 aliyun-data 分支（CI 合并数据源）
git branch -f aliyun-data origin/aliyun-data 2>/dev/null || git branch aliyun-data origin/main
git checkout -f aliyun-data >> "$LOG" 2>&1
cp /tmp/aliyun-reinit.json data/discovery-aliyun.json
cp /tmp/aliyun-reinit.json .aliyun-data.json
git add -f data/discovery-aliyun.json .aliyun-data.json
git diff --cached --quiet || git commit -m "aliyun scan $(date -u +%Y-%m-%d) [reinit]" >> "$LOG" 2>&1
git push "$REMOTE" aliyun-data >> "$LOG" 2>&1
echo "aliyun-data 推送完成: $(wc -c < data/discovery-aliyun.json) bytes" >> "$LOG"

# 5) 回到 main，恢复 aliyun 数据文件，生成干净数据
git checkout -f main >> "$LOG" 2>&1
cp /tmp/aliyun-reinit.json data/discovery-aliyun.json
rm -f /tmp/aliyun-reinit.json
"$PY" -m src.main --use-discovery --detail >> "$LOG" 2>&1

# 6) 提交 + 推送 main
git config user.name "hr-policy-bot"
git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "no changes" >> "$LOG"
else
  git commit -m "weekly digest $(date -u +%Y-%m-%d) [reinit]" >> "$LOG" 2>&1
  git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true
  git push "$REMOTE" main >> "$LOG" 2>&1
  echo "main 推送完成" >> "$LOG"
fi

echo "=== $(date -u +%FT%TZ) reinit done ===" >> "$LOG"
