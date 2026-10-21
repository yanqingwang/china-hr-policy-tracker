"""分片发现 CLI（超时防护：70 城通道拆 N 个 shard，每片独立运行不撞时长）。

用法（CI matrix 4 片示例）:
    python -m src.discover --shard 0 --num-shards 4
    python -m src.discover --shard 1 --num-shards 4 --limit-cities 40   # 测试

直接扫城市官方门户（data/city_channels.yml），不依赖外部搜索引擎，
因此 GitHub Actions（拦 DDG/bing/mojeek）可用；城市站个别被拦时该城降级为空。

产物: data/discovery-shard-{i}.json（原始条目数组）
分片 job 不写 git、不碰 state.json，只上传 artifact；汇总在 src.main --use-discovery。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import gov_city  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--num-shards", type=int, default=4)
    ap.add_argument("--limit-cities", type=int, default=0, help="测试：只看名单前 K 城")
    args = ap.parse_args()

    channels = gov_city.load_channels()
    cities = list(channels.keys())
    if args.limit_cities:
        cities = cities[: args.limit_cities]

    # round-robin 分片：编号相邻的城市分布在不同省域，降低同片 WAF 集中命中
    shard_cities = cities[args.shard :: args.num_shards]
    raws = gov_city.scan_many([(c, channels[c]) for c in shard_cities])

    out_path = ROOT / "data" / f"discovery-shard-{args.shard}.json"
    out_path.write_text(json.dumps(raws, ensure_ascii=False), encoding="utf-8")
    print(f"[shard {args.shard}/{args.num_shards}] cities={len(shard_cities)} items={len(raws)}", file=sys.stderr)


if __name__ == "__main__":
    main()
