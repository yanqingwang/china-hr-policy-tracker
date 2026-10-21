"""分片发现 CLI（超时防护：70 城拆 N 个 shard，每片独立运行不撞时长）。

用法（CI matrix 4 片示例）:
    python -m src.discover --shard 0 --num-shards 4
    python -m src.discover --shard 1 --num-shards 4 --limit-cities 40   # 测试

产物: data/discovery-shard-{i}.json（原始条目数组）+ data/discovery-cache-{i}.json（查询缓存）
分片 job 不写 git、不碰 state.json，只上传 artifact；汇总在 src.main --use-discovery。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml                     # noqa: E402
from src import search_discovery  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--num-shards", type=int, default=4)
    ap.add_argument("--limit-cities", type=int, default=0, help="测试：只看名单前 K 城")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "data" / "cities.yml").read_text(encoding="utf-8"))
    cities = cfg.get("cities") or []
    if args.limit_cities:
        cities = cities[: args.limit_cities]

    # 交错的分片切分：round-robin，保证每片城市分布均匀且相邻编号不相邻城市省域重叠低
    shard_cities = cities[args.shard :: args.num_shards]
    source = {"id": "search-70cities", "shard_tag": f"shard{args.shard}"}
    raws, cache = search_discovery._scan(shard_cities, source)
    search_discovery._write_cache(f"shard{args.shard}", cache)

    out_path = ROOT / "data" / f"discovery-shard-{args.shard}.json"
    out_path.write_text(json.dumps(raws, ensure_ascii=False), encoding="utf-8")
    print(f"[shard {args.shard}/{args.num_shards}] cities={len(shard_cities)} items={len(raws)} "
          f"queries_ok={sum(1 for c in cache if c.get('ok'))}/{len(cache)}", file=sys.stderr)


if __name__ == "__main__":
    main()
