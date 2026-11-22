#!/usr/bin/env python3
"""把 kb-submit / kb-approved 的 Issue 聚合成 index.json + items/<id>.md。

只依赖标准库：GitHub Actions 里直接 `python3 scripts/aggregate.py` 即可。
判定口径与客户端 `kb_share.rs::share_sanitize` 保持一致，两边各拦一次。
"""

import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "meng587/vqa-rs-kb")
ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "items"
INDEX = ROOT / "index.json"
PINS = ROOT / "pins.json"

KINDS = {"制度", "规程", "故障", "阈值", "术语", "经验"}
BAD_PATTERNS = [
    "忽略以上", "忽略之前", "忽略前面", "忽略上述", "无视以上", "不要遵守",
    "取消所有限制", "ignore previous", "ignore above", "ignore all previous",
    "disregard previous", "jailbreak", "越狱", "你现在是", "你现在扮演",
    "从现在开始你", "系统提示", "system prompt", "执行以下", "删除知识库",
    "输出你的提示词", "泄露你的",
]
LABEL_SUBMIT = "kb-submit"
LABEL_APPROVED = "kb-approved"
LABEL_HIDE = "kb-hide"
LABEL_REPORT = "kb-report"


def api(path, method="GET", payload=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "vqa-rs-kb-aggregate")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=25) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip() else {}


def open_issues():
    """全部 open issue（含 PR 过滤），再在本地按标签筛；labels=a,b 是 AND，不能直接用。"""
    out, page = [], 1
    while page <= 20:
        chunk = api(f"/repos/{REPO}/issues?state=open&per_page=100&page={page}")
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return [i for i in out if "pull_request" not in i]


def label_names(issue):
    return {l["name"] for l in issue.get("labels", [])}


def parse_form(body):
    """GitHub Issue Form 渲染成 `### 字段` + 值，这里按 ### 切块。"""
    secs = re.split(r"^###\s+(.+)$", body or "", flags=re.M)
    fields = {}
    for i in range(1, len(secs) - 1, 2):
        key = secs[i].strip()
        val = secs[i + 1].strip()
        fields[key] = val
    return fields


def normalize(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u2060]", "", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def validate(title, kind, body):
    """返回 (ok, reason)。reason 只在不过时给，写进 workflow 日志方便排查。"""
    if not title:
        return False, "缺少标题"
    if len(title) > 20:
        return False, f"标题超过 20 字（{len(title)}）"
    if kind not in KINDS:
        return False, f"类型不在白名单（{kind or '空'}）"
    if len(body) < 20:
        return False, f"正文太短（{len(body)} 字）"
    if len(body) > 600:
        return False, f"正文太长（{len(body)} 字）"
    if "```" in body:
        return False, "正文含代码块"
    low = body.lower()
    if "http://" in low or "https://" in low or "www." in low:
        return False, "正文含链接"
    for p in BAD_PATTERNS:
        if p in low:
            return False, f"正文含指令类表述（{p}）"
    return True, ""


def score(stars, comments, created_at):
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    age = (datetime.now(timezone.utc) - dt).days
    raw = 1.0 + stars + 0.5 * comments
    return round(math.log(raw) / (1.0 + max(age, 0) / 45.0), 4)


def prev_index():
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"approved": [], "pending": []}


def main():
    if not TOKEN:
        print("缺少 GITHUB_TOKEN", file=sys.stderr)
        return 1
    pins = []
    try:
        pins = json.loads(PINS.read_text(encoding="utf-8")).get("ids", [])
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    prev = prev_index()
    prev_by_id = {it["id"]: it for it in prev.get("approved", []) + prev.get("pending", [])}
    approved, pending = [], []
    touched = []

    for issue in open_issues():
        labels = label_names(issue)
        if LABEL_HIDE in labels or LABEL_REPORT in labels:
            continue
        if not (labels & {LABEL_SUBMIT, LABEL_APPROVED}):
            continue
        f = parse_form(issue.get("body", ""))
        title = normalize(f.get("标题", ""))
        kind = normalize(f.get("类型", ""))
        body = normalize(f.get("正文", ""))
        source = normalize(f.get("来源", ""))
        tags = [t.strip() for t in re.split(r"[,，、]", normalize(f.get("标签", ""))) if t.strip()][:4]
        ok, reason = validate(title, kind, body)
        if not ok:
            print(f"#{issue['number']} 不过闸：{reason}")

        if ok and LABEL_SUBMIT in labels:
            try:
                api(f"/repos/{REPO}/issues/{issue['number']}/labels", "POST", {"labels": [LABEL_APPROVED]})
            except urllib.error.HTTPError as e:
                print(f"#{issue['number']} 打标签失败：{e}")
        elif not ok and LABEL_APPROVED in labels:
            try:
                api(f"/repos/{REPO}/issues/{issue['number']}/labels/{LABEL_APPROVED}", "DELETE")
            except urllib.error.HTTPError as e:
                print(f"#{issue['number']} 撤标签失败：{e}")

        if not (title and kind in KINDS):
            # 表单没填全（或不是表单发的），先进 pending 让人看一眼
            ok = False

        created = issue.get("created_at", "")
        year = created[:4] if created[:4].isdigit() else str(datetime.now().year)
        item_id = f"kb-{year}-{issue['number']:04d}"
        stars = int((issue.get("reactions") or {}).get("+1", 0))
        comments = int(issue.get("comments", 0))
        url = issue.get("html_url", f"https://github.com/{REPO}/issues/{issue['number']}")

        old = prev_by_id.get(item_id)
        # 先按 v1 算指纹，与上一版不同就说明正文改过，版本号 +1
        probe = hashlib.sha256(
            f"## {title}\n\n{body}\n\n> 来源：{source or '社区投稿'} · id {item_id} · v1\n".encode("utf-8")
        ).hexdigest()
        version = 1
        if old and old.get("sha256") and old["sha256"] != probe:
            version = int(old.get("version", 1)) + 1

        text = (
            f"## {title}\n\n{body}\n\n"
            f"> 来源：{source or '社区投稿'} · id {item_id} · v{version} · 采纳 {stars}\n"
        )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

        item = {
            "id": item_id,
            "title": title,
            "kind": kind if kind in KINDS else "经验",
            "tags": tags,
            "source": source or "社区投稿",
            "sha256": digest,
            "version": version,
            "created_at": created[:10],
            "updated_at": issue.get("updated_at", "")[:10],
            "stars": stars,
            "comments": comments,
            "score": score(stars, comments, created),
            "pinned": item_id in pins,
            "preview": body[:60],
            "url": url,
        }
        (approved if ok else pending).append(item)
        touched.append((item_id, text))

    ITEMS.mkdir(exist_ok=True)
    for item_id, text in touched:
        (ITEMS / f"{item_id}.md").write_text(text, encoding="utf-8")

    approved.sort(key=lambda x: (not x["pinned"], -x["score"]))
    pending.sort(key=lambda x: x["id"])
    doc = {
        "v": 2,
        "updated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(approved),
        "approved": approved,
        "pending": pending,
    }
    INDEX.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"聚合完成：approved {len(approved)} / pending {len(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
