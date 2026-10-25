#!/bin/bash
# 聚焦初始化：城市门户分页扫描(年度基数/比例) → 高详情提取 → 推送
# 跳过被限流的 Bing，专注可靠的城市门户 + gov.cn 政策库
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
export DETAIL_FETCH_CAP=120
export DETAIL_FETCH_MAX=400
REPO=/www/china-si-phf-policy/repo
PY=/www/china-si-phf-policy/venv/bin/python
TOKEN=$(cat /root/.config/si-phf-policy/github_pat)
REMOTE="https://x-access-token:${TOKEN}@github.com/yanqingwang/china-hr-policy-tracker.git"
LOG=/var/log/hr-policy-init-base.log

echo "=== $(date -u +%FT%TZ) init-base start ===" >> "$LOG"
cd "$REPO"

# 1) 同步最新代码
git fetch origin main >> "$LOG" 2>&1
git reset --hard origin/main >> "$LOG" 2>&1
git clean -fd >> "$LOG" 2>&1 || true
git checkout -f main >> "$LOG" 2>&1

# 2) 重置 state/items
echo '{"seen": []}' > data/state.json
echo '[]' > data/items.json

# 3) 城市门户全量扫描（含分页，追年度基数调整历史）+ 详情
"$PY" -m src.discover --full --detail >> "$LOG" 2>&1
cp data/discovery-aliyun.json /tmp/aliyun-base.json

# 4) 推送 discovery-aliyun.json 到 aliyun-data
git fetch origin aliyun-data:refs/remotes/origin/aliyun-data >> "$LOG" 2>&1 || true
git branch -f aliyun-data origin/aliyun-data >> "$LOG" 2>&1 || git branch aliyun-data origin/main
git checkout -f aliyun-data >> "$LOG" 2>&1
cp /tmp/aliyun-base.json data/discovery-aliyun.json
cp /tmp/aliyun-base.json .aliyun-data.json
git add -f data/discovery-aliyun.json .aliyun-data.json
git diff --cached --quiet || git commit -m "aliyun scan $(date -u +%Y-%m-%d) [pagination]" >> "$LOG" 2>&1
git push "$REMOTE" aliyun-data >> "$LOG" 2>&1 || git push --force "$REMOTE" aliyun-data >> "$LOG" 2>&1
echo "aliyun-data 推送: $(wc -c < data/discovery-aliyun.json) bytes" >> "$LOG"

# 5) 回 main，恢复数据文件
git checkout -f main >> "$LOG" 2>&1
cp /tmp/aliyun-base.json data/discovery-aliyun.json
rm -f /tmp/aliyun-base.json
# 在 checkout 之后重新清空 state/items（避免被分支恢复覆盖）
echo '{"seen": []}' > data/state.json
echo '[]' > data/items.json
# 汇总生成（高详情提取，聚焦新基数）
"$PY" -m src.main --use-discovery --detail --detail-cap 120 >> "$LOG" 2>&1

# 6) 提交 + 推送 main
git config user.name "hr-policy-bot"
git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "no changes" >> "$LOG"
else
  git commit -m "chore: 聚焦初始化——城市门户分页扫描抓年度基数/比例(4月/7月调整高峰)" >> "$LOG" 2>&1
  git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true
  git push "$REMOTE" main >> "$LOG" 2>&1
  echo "main 推送完成" >> "$LOG"
fi

echo "=== $(date -u +%FT%TZ) init-base done ===" >> "$LOG"
