#!/bin/bash
# 综合初始化：重置 state/items → 全源抓取（年度基数/比例等每年更新数据）→ 推送 main
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
export DETAIL_FETCH_CAP=100
export DETAIL_FETCH_MAX=300
REPO=/www/china-hr-si-phf-policy/repo
PY=/www/china-hr-si-phf-policy/venv/bin/python
TOKEN=$(cat /root/.config/hr-si-phf-policy/github_pat)
REMOTE="https://x-access-token:${TOKEN}@github.com/yanqingwang/china-hr-si-phf-policy-tracker.git"
LOG=/var/log/hr-policy-init-full.log

echo "=== $(date -u +%FT%TZ) init-full start ===" >> "$LOG"
cd "$REPO"

# 1) 同步到最新 main（含代码增强）
git fetch origin main >> "$LOG" 2>&1
git reset --hard origin/main >> "$LOG" 2>&1
git clean -fd >> "$LOG" 2>&1 || true
git checkout -f main >> "$LOG" 2>&1

# 2) 重置（在 main 上、运行前清空）
echo '{"seen": []}' > data/state.json
echo '[]' > data/items.json

# 3) 全源综合抓取（不带 --use-discovery → gov_search + gov_list + search_discovery + gov_city 内联全跑）
"$PY" -m src.main --detail --detail-cap 100 >> "$LOG" 2>&1

# 4) 提交 + 推送
git config user.name "hr-policy-bot"
git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "no changes" >> "$LOG"
else
  git commit -m "chore: 综合初始化——全源抓取年度基数/比例等每年更新数据" >> "$LOG" 2>&1
  git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true
  git push "$REMOTE" main >> "$LOG" 2>&1
  echo "main 推送完成" >> "$LOG"
fi

echo "=== $(date -u +%FT%TZ) init-full done ===" >> "$LOG"
