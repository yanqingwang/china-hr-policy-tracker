#!/usr/bin/env bash
# 阿里云侧采集脚本：全量扫描城市官方门户 → 数字提取 → 产出 discovery-aliyun.json
# 然后按可用通道交付给 GitHub：
#   Mode 1 (git push): 服务器能访问 GitHub 时，推到 aliyun-data 分支（需配 GH_PAT）
#   Mode 2 (web dir) : 服务器访问不了 GitHub 时，把 JSON 放到 web 目录，由 CI 直接 HTTP 拉取
#                      （需要你在 repo 设置 Secret: ALIYUN_DATA_URL）
set -euo pipefail

REPO_DIR="${ALIYUN_REPO_DIR:-/opt/china-hr-policy-tracker}"
WEB_DIR="${ALIYUN_WEB_DIR:-/var/www/html/hr-data}"
PY="${ALIYUN_PY:-$REPO_DIR/.venv/bin/python}"
BRANCH="aliyun-data"

echo "[1/4] 进入仓库 ${REPO_DIR}"
cd "$REPO_DIR"

echo "[2/4] 全量采集 + 数字提取（城市官方门户）"
# --detail 抓详情页提取数字（慢但值得，覆盖 CI 拉不到的城）；若不想每次全量抓详情可去掉 --detail
timeout 1500 "$PY" -m src.discover --full --detail
test -f data/discovery-aliyun.json || { echo "采集失败：未产出 discovery-aliyun.json"; exit 1; }
echo "      产出 $(wc -c < data/discovery-aliyun.json) bytes"

echo "[3/4] 交付：优先 git push，失败则写 web 目录"
PUSHED=0
if [ -n "${GH_PAT:-}" ]; then
  # 用独立分支推送，避免与 CI 的 main 快照提交冲突
  git config user.name "aliyun-collector" || true
  git config user.email "aliyun-collector@users.noreply.github.com" || true
  git fetch origin "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" 2>/dev/null || true
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
  cp data/discovery-aliyun.json .aliyun-data.json
  git add -f .aliyun-data.json data/discovery-aliyun.json 2>/dev/null || git add data/discovery-aliyun.json .aliyun-data.json
  if git diff --cached --quiet; then
    echo "      无变化（skip commit）"
  else
    git commit -m "aliyun scan $(date -u +%Y-%m-%d)" || true
  fi
  if git push "https://x-access-token:${GH_PAT}@github.com/yanqingwang/china-hr-policy-tracker.git" "$BRANCH" 2>/dev/null; then
    echo "      ✅ git push 成功（分支 $BRANCH）"
    PUSHED=1
  else
    echo "      ⚠️ git push 失败（GitHub 不可达？），尝试 web 目录"
  fi
  git checkout main 2>/dev/null || true
fi

if [ "$PUSHED" != "1" ]; then
  mkdir -p "$WEB_DIR"
  cp data/discovery-aliyun.json "$WEB_DIR/discovery-aliyun.json"
  echo "      ✅ 已写入 web 目录：$WEB_DIR/discovery-aliyun.json"
  echo "      👉 请把该文件的公网 URL 设为仓库 Secret: ALIYUN_DATA_URL"
fi

echo "[4/4] 完成"
