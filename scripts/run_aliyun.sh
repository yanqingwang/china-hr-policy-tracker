#!/bin/bash
# Aliyun HR-policy 采集包装脚本（周一 01:00 CST 由 cron 触发）
# 策略：
#   1) 抓取最多尝试 2 次（失败自动重试），每次成功立即落盘
#   2) 两次尝试全部结束后，若至少一次成功，一次性推送到 GitHub aliyun-data 分支
#   3) 本地备份最多保留 2 份

set -euo pipefail

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

REPO=/www/hr-policy-tracker/repo
PY=/www/hr-policy-tracker/venv/bin/python
BACKUP=/www/hr-policy-tracker/backup
TOKEN=$(cat /root/.config/hr-policy/github_pat)
BRANCH=aliyun-data
LOG=/var/log/china-hr-policy-aliyun.log
REMOTE="https://x-access-token:${TOKEN}@github.com/yanqingwang/china-hr-policy-tracker.git"

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

log "=== run start ==="

# 1) 同步仓库到 origin/main
cd "$REPO"
git fetch --depth 50 origin main >> "$LOG" 2>&1
git reset --hard origin/main >> "$LOG" 2>&1
git clean -fd >> "$LOG" 2>&1 || true
git checkout -f main >> "$LOG" 2>&1 || true

# 2) 抓取：最多 2 次尝试，每次成功立即落盘
SUCCESS=0
for attempt in 1 2; do
  log "[attempt $attempt/2] full scrape (discover --full --detail)"
  if "$PY" -m src.discover --full --detail >> "$LOG" 2>&1 && [ -s data/discovery-aliyun.json ]; then
    SUCCESS=$attempt
    ts=$(date +%Y%m%d_%H%M%S)
    mkdir -p "$BACKUP"
    cp data/discovery-aliyun.json "$BACKUP/hr-data-$ts.json"
    # 只留最近 2 份
    ls -1t "$BACKUP"/hr-data-*.json 2>/dev/null | tail -n +3 | xargs -r rm -f
    log "[attempt $attempt] OK, $(wc -c < data/discovery-aliyun.json) bytes saved"
    break
  else
    log "[attempt $attempt] FAILED"
  fi
done

if [ "$SUCCESS" = "0" ]; then
  log "both attempts failed — skip push, keep disk snapshots"
  log "=== run end (failed) ==="
  exit 1
fi

# 3) 两次尝试结束，统一推送（本地备份已在第 2 步完成）
cp data/discovery-aliyun.json /tmp/aliyun-data.json
git config user.name "aliyun-collector"
git config user.email "aliyun-collector@users.noreply.github.com"

git fetch origin "$BRANCH" >> "$LOG" 2>&1 || true
if git show-ref --verify --quiet refs/remotes/origin/"$BRANCH"; then
  git branch -f "$BRANCH" origin/"$BRANCH" >> "$LOG" 2>&1
else
  git branch -f "$BRANCH" origin/main >> "$LOG" 2>&1
fi
git checkout -f "$BRANCH" >> "$LOG" 2>&1
cp /tmp/aliyun-data.json data/discovery-aliyun.json
cp /tmp/aliyun-data.json .aliyun-data.json
rm -f /tmp/aliyun-data.json

git add -f data/discovery-aliyun.json .aliyun-data.json
if git diff --cached --quiet; then
  log "no changes (skip commit)"
else
  git commit -m "aliyun scan $(date -u +%Y-%m-%d) [attempt $SUCCESS]" >> "$LOG" 2>&1
fi

if git push "$REMOTE" "$BRANCH" >> "$LOG" 2>&1; then
  log "push OK ($BRANCH)"
else
  log "push FAILED (retry once)"
  sleep 5
  git push "$REMOTE" "$BRANCH" >> "$LOG" 2>&1 || log "push FAILED twice"
fi

git checkout -f main >> "$LOG" 2>&1 || true

log "=== run end ==="
