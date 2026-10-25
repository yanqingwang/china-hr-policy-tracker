#!/bin/bash
# 每小时抓取尝试（72 小时窗口）：城市门户分页扫描 + Bing 尝试 + 汇总 → 推送 GitHub
# 含并发锁（上一轮未结束则跳过）与 72 小时自动过期
# 保险数据规则：
#   - 以已核实权威基准为准，绝不覆盖原始数据
#   - 仅当 基数/比例/上下限 发生变化时，增量更新对应条目+日期，并生成「社保公积金政策_日期」新版本
#   - 无变化 → 只刷新当前「社保公积金政策.md」（含日期），不产生新版本、不产生提交
set -uo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
REPO=/www/china-si-phf-policy/repo
PY=/www/china-si-phf-policy/venv/bin/python
[ -x "$PY" ] || PY=$(command -v python3)
LOG=/var/log/hr-policy-hourly.log
START=/var/run/hr-policy-hourly-start
CRON=/etc/cron.d/china-si-phf-policy-hourly
LOCK=/var/run/hr-policy-hourly.lock
CHANGED=/tmp/hr-insurance-changed
TOKEN=$(cat /root/.config/hr-policy/github_pat)
REMOTE="https://x-access-token:${TOKEN}@github.com/yanqingwang/china-si-phf-policy.git"

# 并发锁
exec 9>"$LOCK"
flock -n 9 || { echo "$(date '+%F %T') 上轮仍在运行，跳过本次" >> "$LOG"; exit 0; }

# 72 小时过期检查
if [ -f "$START" ]; then
  start=$(cat "$START"); now=$(date +%s)
  if [ $((now - start)) -gt 259200 ]; then
    rm -f "$CRON" 2>/dev/null
    echo "$(date '+%F %T') 72小时窗口结束，已移除定时任务 $CRON" >> "$LOG"
    exit 0
  fi
else
  date +%s > "$START"
  echo "$(date '+%F %T') 启动72小时抓取窗口，每小时一次" >> "$LOG"
fi

echo "=== $(date -u +%FT%TZ) 开始抓取 ===" >> "$LOG"
cd "$REPO"
rm -f "$CHANGED"

# 1) 同步最新代码（保险基准已入库，reset 后仍为权威版本）
git fetch origin main >> "$LOG" 2>&1
git reset --hard origin/main >> "$LOG" 2>&1
git clean -fd >> "$LOG" 2>&1 || true
git checkout -f main >> "$LOG" 2>&1

# 2) 城市门户全量扫描（分页，抓年度基数/比例历史）
"$PY" -m src.discover --full >> "$LOG" 2>&1
cp data/discovery-aliyun.json /tmp/aliyun-hourly.json
echo "city-portal: $(wc -c < data/discovery-aliyun.json) bytes" >> "$LOG"

# 3) 推送 aliyun-data 分支
git fetch origin aliyun-data:refs/remotes/origin/aliyun-data >> "$LOG" 2>&1 || true
git branch -f aliyun-data origin/aliyun-data >> "$LOG" 2>&1 || git branch aliyun-data origin/main
git checkout -f aliyun-data >> "$LOG" 2>&1
cp /tmp/aliyun-hourly.json data/discovery-aliyun.json
cp /tmp/aliyun-hourly.json .aliyun-data.json
git add -f data/discovery-aliyun.json .aliyun-data.json
git diff --cached --quiet || git commit -m "aliyun scan $(date -u +%Y-%m-%d_%H%M) [hourly]" >> "$LOG" 2>&1
git push "$REMOTE" aliyun-data >> "$LOG" 2>&1 || git push --force "$REMOTE" aliyun-data >> "$LOG" 2>&1
echo "aliyun-data 已推送" >> "$LOG"

# 4) 回 main，全量抓取（含 Bing 尝试，限流时优雅降级）+ 汇总生成
git checkout -f main >> "$LOG" 2>&1
cp /tmp/aliyun-hourly.json data/discovery-aliyun.json
rm -f /tmp/aliyun-hourly.json
"$PY" -m src.main --detail --detail-cap 60 >> "$LOG" 2>&1

# 5) 保险数据增量更新（仅变化才改基准；变化时写 $CHANGED 标记）
[ -f "$REPO/scripts/update_insurance.py" ] || { echo "❌ 缺少 update_insurance.py" >> "$LOG"; exit 1; }
"$PY" "$REPO/scripts/update_insurance.py" >> "$LOG" 2>&1

# 6) 生成社保公积金政策报告（当前版始终刷新；变化时生成带日期的新版本）
[ -f "$REPO/scripts/gen_insurance_report.py" ] || { echo "❌ 缺少 gen_insurance_report.py" >> "$LOG"; exit 1; }
"$PY" "$REPO/scripts/gen_insurance_report.py" >> "$LOG" 2>&1
if [ -f "$CHANGED" ]; then
  "$PY" "$REPO/scripts/gen_insurance_report.py" --dated >> "$LOG" 2>&1
  echo "检测到变化，已生成带日期新版本" >> "$LOG"
fi

# 7) 提交 + 推送 main（含保险增量变更与报告）
git config user.name "hr-policy-bot"
git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "no changes" >> "$LOG"
else
  git commit -m "hourly refresh $(date -u +%Y-%m-%d_%H%M)" >> "$LOG" 2>&1
  git pull --rebase --autostash origin main >> "$LOG" 2>&1 || true
  git push "$REMOTE" main >> "$LOG" 2>&1
  echo "main 已推送" >> "$LOG"
fi
rm -f "$CHANGED"

echo "=== $(date -u +%FT%TZ) 完成 ===" >> "$LOG"
