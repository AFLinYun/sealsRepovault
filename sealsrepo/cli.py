"""命令行入口：sealsrepo <command> [options]。

命令：
  init               初始化项目库目录结构
  add <url>          添加 GitHub 项目（生成记录）
  grade <id>         评级（candidate -> evaluated/retained/rejected）
  list               列出全部记录
  search <keyword>   搜索记录
  validate           校验全部记录
  rebuild            重建派生索引
  trending-import    从每日热榜 JSON 导入新项目（candidate）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import core


def cmd_init(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    if (root / "config.json").exists():
        print(f"已初始化: {root}")
        return 0
    (core.records_dir(root)).mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    cfg = dict(core.DEFAULT_CONFIG)
    if args.weights:
        cfg["weights"] = json.loads(args.weights)
    (core.config_path(root)).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    core.write_index(root)
    core.append_event(root, {"type": "init", "root": str(root)})
    print(f"初始化完成: {root}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    if not (core.config_path(root)).exists():
        print("未初始化，先运行: sealsrepo init", file=sys.stderr)
        return 1
    recs = {r["id"]: r for r in core.all_records(root)}
    rec = core.new_record(args.url, desc=args.desc or "", source=args.source)
    rid = rec["id"]
    existed = rid in recs
    if existed:
        # 已有记录且未显式提供新描述时，保留原 desc，避免空覆盖
        if not rec["desc"] and recs[rid].get("desc"):
            rec["desc"] = recs[rid]["desc"]
    rec["updated_at"] = core.now_iso()
    core.save_record(root, rec)
    core.write_index(root)
    core.append_event(root, {"type": "upsert", "id": rid, "existed": existed})
    verb = "更新已有记录" if existed else "添加新项目"
    print(f"[{verb}] {rid} -> {rec['url']}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    rec = core.load_record(root, args.id)
    if args.grade not in core.VALID_GRADES:
        print(f"grade 必须是 {'/'.join(sorted(core.VALID_GRADES))}", file=sys.stderr)
        return 1
    if args.grade in ("S", "A", "B") and not args.summary:
        print("S/A/B 评级必须提供 --summary（能力摘要）", file=sys.stderr)
        return 1
    rec["grade"] = args.grade
    if args.summary:
        rec["capability_summary"] = args.summary
    if args.direction:
        rec["hit_directions"] = [d.strip() for d in args.direction.split(",") if d.strip()]
    if args.evidence:
        rec["evidence"] = args.evidence
    if rec["status"] == "candidate":
        rec["status"] = "evaluated"
    rec["updated_at"] = core.now_iso()
    core.save_record(root, rec)
    core.write_index(root)
    core.append_event(root, {"type": "grade", "id": rec["id"], "grade": args.grade})
    print(f"[评级] {rec['id']} -> {args.grade} (status={rec['status']})")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    recs = core.all_records(root)
    if args.status:
        recs = [r for r in recs if r.get("status") == args.status]
    if args.grade:
        recs = [r for r in recs if r.get("grade") == args.grade]
    if not recs:
        print("(空)")
        return 0
    print(f"{'ID':42s} {'状态':10s} {'评级':5s} 命中方向")
    for r in sorted(recs, key=lambda x: x["id"]):
        print(f"{r['id']:42s} {r['status']:10s} {(r.get('grade') or '-'):5s} "
              f"{', '.join(r.get('hit_directions', []))}")
    print(f"\n共 {len(recs)} 条")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    kw = args.keyword.lower()
    hits = []
    for r in core.all_records(root):
        hay = " ".join([
            r.get("id", ""), r.get("url", ""), r.get("desc", ""),
            r.get("capability_summary", ""), " ".join(r.get("hit_directions", [])),
        ]).lower()
        if kw in hay:
            hits.append(r)
    if not hits:
        print(f"无匹配: {args.keyword}")
        return 0
    for r in sorted(hits, key=lambda x: x["id"]):
        print(f"{r['id']}  [{r.get('status')}] {(r.get('grade') or '-')}  {r.get('desc', '')[:60]}")
    print(f"\n命中 {len(hits)} 条")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    total, issues = core.validate_all(root)
    recs = core.all_records(root)
    idx = core.rebuild_index(root)
    if (core.index_path(root)).read_text(encoding="utf-8") != idx:
        print("索引漂移：index.md 与记录不一致，运行 sealsrepo rebuild", file=sys.stderr)
        total += 1
    print(f"记录 {len(recs)} 条，错误 {total} 个")
    for rid, errs in issues:
        print(f"  {rid}: {'; '.join(errs)}", file=sys.stderr)
    return 1 if total else 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    core.write_index(root)
    print(f"索引已重建: {core.index_path(root)}")
    return 0


def cmd_trending_import(args: argparse.Namespace) -> int:
    root = core.root_path(args.root)
    if not (core.config_path(root)).exists():
        print("未初始化，先运行: sealsrepo init", file=sys.stderr)
        return 1
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    items = data.get("items", [])
    seen: set[str] = set()  # 本批次内去重
    recs = {r["id"]: r for r in core.all_records(root)}
    added = skipped = 0
    for it in items:
        url = it.get("url", "")
        try:
            rid = core.make_id(url)
        except ValueError:
            continue
        if rid in recs or rid in seen:
            skipped += 1
            continue
        seen.add(rid)
        rec = core.new_record(url, desc=it.get("desc", ""), source="trending")
        rec["stars"] = it.get("stars")
        rec["today_stars"] = it.get("today_stars")
        core.save_record(root, rec)
        added += 1
    core.write_index(root)
    core.append_event(root, {"type": "trending-import", "date": data.get("date"), "added": added, "skipped": skipped})
    print(f"导入完成: 新增 {added}，跳过已有 {skipped}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sealsrepo", description="GitHub 项目入库体检工具")
    p.add_argument("--version", action="version", version=f"sealsrepo {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_root(sp):
        sp.add_argument("--root", default=".", help="项目库根目录（默认当前目录）")

    sp = sub.add_parser("init", help="初始化项目库")
    add_root(sp)
    sp.add_argument("--weights", help="JSON 格式权重覆盖，如 '{\"agent_capability\": 40}'")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("add", help="添加 GitHub 项目")
    add_root(sp)
    sp.add_argument("url")
    sp.add_argument("--desc", default="")
    sp.add_argument("--source", default="manual", choices=["manual", "trending"])
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("grade", help="评级")
    add_root(sp)
    sp.add_argument("id")
    sp.add_argument("--grade", required=True, choices=sorted(core.VALID_GRADES))
    sp.add_argument("--summary", default="", help="能力摘要（S/A/B 必填）")
    sp.add_argument("--direction", default="", help="命中方向，逗号分隔")
    sp.add_argument("--evidence", default="", help="证据级别")
    sp.set_defaults(func=cmd_grade)

    sp = sub.add_parser("list", help="列出记录")
    add_root(sp)
    sp.add_argument("--status", choices=sorted(core.VALID_STATUS))
    sp.add_argument("--grade", choices=sorted(core.VALID_GRADES))
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("search", help="搜索")
    add_root(sp)
    sp.add_argument("keyword")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("validate", help="校验全部记录")
    add_root(sp)
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("rebuild", help="重建索引")
    add_root(sp)
    sp.set_defaults(func=cmd_rebuild)

    sp = sub.add_parser("trending-import", help="从热榜 JSON 导入")
    add_root(sp)
    sp.add_argument("--json", required=True, help="Job A 输出的 JSON 文件")
    sp.set_defaults(func=cmd_trending_import)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
