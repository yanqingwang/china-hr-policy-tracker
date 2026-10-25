# 服务器自动抓取脚本

> 本目录已纳入版本管理。此前脚本仅存在于服务器 `/www/china-hr-si-phf-policy/scripts/`，
> 而 `run_daily.sh` 在 `git reset --hard` 后以 `$REPO/scripts/...` 相对路径调用，
> 导致 `update_insurance.py` / `gen_insurance_report.py` **长期未被执行**（报 No such file or directory）。
> 现脚本随仓库分发，路径问题已修复。

## 脚本清单

| 脚本 | 作用 | 触发 |
|---|---|---|
| `run_daily.sh` | 每日全量采集 + 增量更新 + 报告 + 推送 | cron `0 3 * * *` |
| `run_hourly.sh` | 72 小时窗口内每小时抓取（含自动过期） | 手动/临时 cron |
| `run_aliyun.sh` | 每周城市门户扫描 → 推送 aliyun-data 分支 | cron `0 1 * * 1` |
| `update_insurance.py` | **严格增量更新**（核心规则见下） | 由 run_daily/hourly 调用 |
| `gen_insurance_report.py` | 按 [`docs/OUTPUT_FORMAT.md`](../docs/OUTPUT_FORMAT.md) 生成总表 | 同上 |
| `merge_batches.sh` | 多批次 AI 抓取结果合并（中间落盘） | 人工 |

## 增量更新核心规则（强制）

**只有 `基数上限` / `基数下限` / `个人比例%` / `公司比例%` 发生真实变化时，才改动数据。**

- 无变化 → **原始数据完全不动**：不刷新 `_date`、不改 `_src_type`、不重写文件（幂等）
- 有变化 → 仅改动变化字段，并写入 `_date=抓取日`、`_src_type=script`
- 三重防误覆盖：
  1. 仅接受 `publish_date` 以 `2026` 开头的记录（防旧年数据降级）
  2. 标题含 4 位年份且 < 2026 → 拒绝
  3. 基数新值须在基准值 ±50% 内（防月缴存额/年缴额误提取）
- 险种映射严格：公积金记录只更新公积金，社保记录只更新五险

## 已修复的缺陷

| 缺陷 | 影响 | 修复 |
|---|---|---|
| 脚本不在仓库内，路径 `$REPO/scripts/` 不存在 | 增量更新与报告生成**从未执行** | 脚本纳入仓库；路径改为脚本自身位置 |
| 年份正则 `20(2[0-9])` 从「2026」取到 `26` | 所有 2026 记录被误判为旧数据丢弃，增量更新**完全失效** | 改为 `(20\\d{2})` 精确匹配 |
| 比例字段不参与变更检测 | 与「比例变化才更新」要求不符 | 比例纳入 `WATCH_FIELDS` |
| `8` 与 `8.0` 被判定为不同 | 误报变化、重复刷新日期 | 新增 `same()` 数值等价比较 |
| 脚本缺失时静默失败 | 日志无告警，问题被掩盖 | 增加存在性检查，缺失即 `exit 1` |

## 运行

```bash
# 服务器（必须用 venv python，系统 python 过旧不支持 list[dict]）
/www/china-hr-si-phf-policy/venv/bin/python scripts/update_insurance.py
/www/china-hr-si-phf-policy/venv/bin/python scripts/gen_insurance_report.py --dated

# 手动跑完整日更
/www/china-hr-si-phf-policy/scripts/run_daily.sh
```
