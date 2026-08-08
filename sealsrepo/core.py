"""核心数据模型与文件操作：记录读写、URL 规范化、ID 生成、索引。

全部使用标准库，不依赖第三方包。目录结构：
  <root>/
    projects/records/<id>.md    # 项目记录（事实源）
    projects/index.md           # 派生索引（可重建）
    config.json                 # 方向权重配置
    logs/events.jsonl           # 追加式事件日志
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------- 常量

VALID_STATUS = {"candidate", "evaluated", "retained", "rejected", "archived"}
VALID_GRADES = {"S", "A", "B", "C", "D"}
DEFAULT_CONFIG = {
    "weights": {
        "agent_capability": 30,
        "game_dev": 30,
        "business_validation": 15,
        "productivity": 10,
        "overseas": 10,
        "content": 5,
    },
    "min_evidence_for_retain": "online-check",
}

GITHUB_RE = re.compile(r"^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?$")
# GitHub owner/repo 合法字符：字母、数字、连字符、下划线、点
ID_RE = re.compile(r"^gh-[a-z0-9][a-z0-9._-]*$")

TZ = timezone.utc


def now_iso() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 路径

def root_path(root: str | Path) -> Path:
    p = Path(root).expanduser().resolve()
    return p


def records_dir(root: str | Path) -> Path:
    return root_path(root) / "projects" / "records"


def config_path(root: str | Path) -> Path:
    return root_path(root) / "config.json"


def index_path(root: str | Path) -> Path:
    return root_path(root) / "projects" / "index.md"


def log_path(root: str | Path) -> Path:
    return root_path(root) / "logs" / "events.jsonl"


# ---------------------------------------------------------------- URL / ID

def canonicalize_url(url: str) -> str:
    """规范化 GitHub URL：去协议差异、去尾斜杠，统一小写 owner/repo。"""
    m = GITHUB_RE.match(url.strip())
    if not m:
        raise ValueError(f"不是合法的 GitHub 仓库 URL: {url}")
    owner, repo = m.group(1).lower(), m.group(2).lower()
    return f"https://github.com/{owner}/{repo}"


def make_id(url: str) -> str:
    """从规范化 URL 生成稳定 ID：gh-<owner>-<repo>，重复链接命中同一记录。"""
    c = canonicalize_url(url)
    _, _, path = c.rpartition("github.com/")
    owner, repo = path.split("/", 1)
    return f"gh-{owner}-{repo}"


def url_from_id(rid: str) -> str:
    """从 ID 反推 URL。注意：owner/repo 本身可能含连字符，无法无歧义还原；
    该函数只用于 ID 格式校验场景，实际 URL 以记录字段为准。"""
    if not ID_RE.match(rid):
        raise ValueError(f"非法 ID: {rid}")
    # 去掉前缀 gh- 后剩余为 owner-repo，按第一个连字符切分（owner 通常不含连字符）
    rest = rid[3:]
    owner, _, repo = rest.partition("-")
    return f"https://github.com/{owner}/{repo}"


# ---------------------------------------------------------------- 记录读写

REQUIRED_FIELDS = ("id", "url", "status", "added_at", "desc", "hit_directions")


def new_record(url: str, desc: str = "", source: str = "manual") -> dict[str, Any]:
    rid = make_id(url)
    return {
        "id": rid,
        "url": canonicalize_url(url),
        "status": "candidate",
        "grade": None,
        "desc": desc,
        "hit_directions": [],
        "capability_summary": "",
        "evidence": None,
        "source": source,
        "added_at": now_iso(),
        "updated_at": now_iso(),
    }


def record_to_md(rec: dict[str, Any]) -> str:
    """记录序列化为 Markdown 项目卡（YAML frontmatter + 正文）。"""
    lines = ["---"]
    for k in ("id", "url", "status", "grade", "added_at", "updated_at", "source"):
        v = rec.get(k)
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v}")
    lines.append(f"desc: {_yaml_scalar(rec.get('desc', ''))}")
    lines.append(f"hit_directions: {json.dumps(rec.get('hit_directions', []), ensure_ascii=False)}")
    lines.append(f"capability_summary: {_yaml_scalar(rec.get('capability_summary', ''))}")
    lines.append(f"evidence: {rec.get('evidence') or 'null'}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {rec['id']}")
    lines.append("")
    lines.append(f"**URL**: {rec['url']}")
    lines.append("")
    lines.append(f"**描述**: {rec.get('desc', '')}")
    lines.append("")
    lines.append("## 评估")
    lines.append("")
    lines.append(f"- 能力摘要：{rec.get('capability_summary', '') or '待补充'}")
    lines.append(f"- 命中方向：{', '.join(rec.get('hit_directions', [])) or '待补充'}")
    lines.append(f"- 评级：{rec.get('grade') or '未评级'}")
    lines.append(f"- 证据级别：{rec.get('evidence') or '未提供'}")
    lines.append("")
    lines.append("## 原始文案")
    lines.append("")
    lines.append("> 待补充")
    lines.append("")
    return "\n".join(lines)


def _yaml_scalar(s: str) -> str:
    s = (s or "").replace("\n", " ").strip()
    if any(ch in s for ch in ':#"\'{}[]&*!|>%@`') or s.startswith(("-", "?", " ")) or s == "":
        return f'"{s}"'
    return s


def parse_record_md(text: str) -> dict[str, Any]:
    """解析 Markdown 项目卡为 dict。frontmatter 用极简解析（键: 值）。"""
    if not text.startswith("---"):
        raise ValueError("记录缺少 frontmatter 分隔符")
    body = text.split("---", 2)[1]
    rec: dict[str, Any] = {}
    for line in body.strip().splitlines():
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if k in ("desc", "capability_summary"):
            rec[k] = v.strip('"')
        elif k == "hit_directions":
            try:
                rec[k] = json.loads(v)
            except json.JSONDecodeError:
                rec[k] = []
        elif k in ("grade", "evidence"):
            rec[k] = None if v == "null" else v
        else:
            rec[k] = v
    return rec


def load_record(root: str | Path, rid: str) -> dict[str, Any]:
    p = records_dir(root) / f"{rid}.md"
    if not p.exists():
        raise FileNotFoundError(f"记录不存在: {rid}")
    return parse_record_md(p.read_text(encoding="utf-8"))


def save_record(root: str | Path, rec: dict[str, Any]) -> Path:
    d = records_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rec['id']}.md"
    p.write_text(record_to_md(rec), encoding="utf-8")
    return p


def all_records(root: str | Path) -> list[dict[str, Any]]:
    d = records_dir(root)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("gh-*.md")):
        try:
            out.append(parse_record_md(p.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- 索引

def rebuild_index(root: str | Path) -> str:
    """从事实源重建派生索引（projects/index.md）。"""
    recs = all_records(root)
    recs.sort(key=lambda r: (r.get("status", ""), r.get("id", "")))
    lines = ["# 项目索引", "", f"共 {len(recs)} 条记录（自动生成，勿手改）", ""]
    lines.append("| ID | 状态 | 评级 | 命中方向 | 描述 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in recs:
        grade = r.get("grade") or "-"
        dirs = ", ".join(r.get("hit_directions", [])) or "-"
        desc = (r.get("desc", "") or "")[:40]
        lines.append(f"| {r['id']} | {r['status']} | {grade} | {dirs} | {desc} |")
    return "\n".join(lines) + "\n"


def write_index(root: str | Path) -> Path:
    p = index_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rebuild_index(root), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 日志

def append_event(root: str | Path, event: dict[str, Any]) -> None:
    p = log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    event.setdefault("ts", now_iso())
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 校验

def validate_record(rec: dict[str, Any]) -> list[str]:
    errors = []
    for f in ("id", "url", "status", "added_at", "desc"):
        if not rec.get(f):
            errors.append(f"缺少必填字段 {f}")
    if not ID_RE.match(rec.get("id", "")):
        errors.append(f"ID 格式非法: {rec.get('id')}")
    if rec.get("status") not in VALID_STATUS:
        errors.append(f"status 非法: {rec.get('status')}")
    g = rec.get("grade")
    if g is not None and g not in VALID_GRADES:
        errors.append(f"grade 非法: {g}")
    try:
        canonicalize_url(rec.get("url", ""))
    except ValueError as e:
        errors.append(str(e))
    if make_id(rec.get("url", "")) != rec.get("id"):
        errors.append(f"ID 与 URL 不一致: {rec.get('id')}")
    return errors


def validate_all(root: str | Path) -> tuple[int, list[tuple[str, list[str]]]]:
    """校验全部记录，返回 (错误总数, [(id, errors)])。"""
    recs = all_records(root)
    total_err = 0
    issues: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for r in recs:
        rid = r.get("id", "?")
        if rid in seen:
            issues.append((rid, ["重复 ID"]))
            total_err += 1
        seen.add(rid)
        errs = validate_record(r)
        if errs:
            issues.append((rid, errs))
            total_err += len(errs)
    return total_err, issues
