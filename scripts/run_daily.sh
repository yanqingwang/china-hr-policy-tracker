#!/bin/bash
# 每日社保公积金抓取（每天 03:00 CST）
# 逻辑（按沟通要求）：
#   - 城市门户分页扫描 + 汇总 → 推送 aliyun-data 与 main
#   - 保险数据严格增量更新：仅当 基数/比例/上下限 变化才更新+日期，绝不覆盖权威基准
#   - 变化时生成「社保公积金政策_日期」新版本；无变化只刷新当前报告
#   - 无补充公积金/双0/并入医保的险种行一律省略（统一规则 src/insurance_rules.py）
set -uo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
REPO=/www/china-si-phf-policy/repo
PY=/www/china-si-phf-policy/venv/bin/python
[ -x "$PY" ] || PY=$(command -v python3)
LOG=/var/log/hr-policy-daily.log
LOCK=/var/run/hr-policy-daily.lock
CHANGED=/tmp/hr-insurance-changed
TOKEN=$(cat /root/.config/si-phf-policy/github_pat)
REMOTE="https://x-access-token:${TOKEN}@github.com/yanqingwang/china-si-phf-policy.git"

# 并发锁（上轮未结束则跳过）
exec 9>"$LOCK"
flock -n 9 || { echo "$(date '+%F %T') 上轮仍在运行，跳过本次" >> "$LOG"; exit 0; }

echo "=== $(date -u +%FT%TZ) 每日抓取开始 ===" >> "$LOG"
cd "$REPO"
rm -f "$CHANGED"

# 1) 同步最新代码
git fetch origin main >> "$LOG" 2>&1
git reset --hard origin/main >> "$LOG" 2>&1
git clean -fd >> "$LOG" 2>&1 || true
git checkout -f main >> "$LOG" 2>&1

# 2) 城市门户全量扫描（分页，抓年度基数/比例历史）
"$PY" -m src.discover --full >> "$LOG" 2>&1
cp data/discovery-aliyun.json /tmp/aliyun-daily.json
echo "city-portal: $(wc -c < data/discovery-aliyun.json) bytes" >> "$LOG"

# 3) 推送 aliyun-data 分支
git fetch origin aliyun-data:refs/remotes/origin/aliyun-data >> "$LOG" 2>&1 || true
git branch -f aliyun-data origin/aliyun-data >> "$LOG" 2>&1 || git branch aliyun-data origin/main
git checkout -f aliyun-data >> "$LOG" 2>&1
cp /tmp/aliyun-daily.json data/discovery-aliyun.json
cp /tmp/aliyun-daily.json .aliyun-data.json
git add -f data/discovery-aliyun.json .aliyun-data.json
git diff --cached --quiet || git commit -m "aliyun scan $(date -u +%Y-%m-%d) [daily]" >> "$LOG" 2>&1
git push "$REMOTE" aliyun-data >> "$LOG" 2>&1 || git push --force "$REMOTE" aliyun-data >> "$LOG" 2>&1
echo "aliyun-data 已推送" >> "$LOG"

# 4) 回 main，全量抓取（含 Bing 尝试，限流时优雅降级）+ 汇总生成
git checkout -f main >> "$LOG" 2>&1
cp /tmp/aliyun-daily.json data/discovery-aliyun.json
rm -f /tmp/aliyun-daily.json
"$PY" -m src.main --detail --detail-cap 60 >> "$LOG" 2>&1

# 5) 保险数据严格增量更新（仅变化才改基准；变化时写标记）
[ -f "$REPO/scripts/update_insurance.py" ] || { echo "❌ 缺少 update_insurance.py" >> "$LOG"; exit 1; }
"$PY" "$REPO/scripts/update_insurance.py" >> "$LOG" 2>&1

# 6) 生成社保公积金政策报告（当前版刷新；变化时生成带日期新版本）
[ -f "$REPO/scripts/gen_insurance_report.py" ] || { echo "❌ 缺少 gen_insurance_report.py" >> "$LOG"; exit 1; }
"$PY" "$REPO/scripts/gen_insurance_report.py" >> "$LOG" 2>&1
if [ -f "$CHANGED" ]; then
  "$PY" "$REPO/scripts/gen_insurance_report.py" --dated >> "$LOG" 2>&1
  echo "检测到变化，已生成带日期新版本" >> "$LOG"
fi

# 7) 提交 + 推送 main
git config user.name "hr-policy-bot"
git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "no changes" >> "$LOG"
else
  git commit -m "daily refresh $(date -u +%Y-%m-%d)" >> "$LOG" 2>&1
  git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true
  git push "$REMOTE" main >> "$LOG" 2>&1
  echo "main 已推送" >> "$LOG"
fi
rm -f "$CHANGED"

echo "=== $(date -u +%FT%TZ) 每日抓取完成 ===" >> "$LOG"
