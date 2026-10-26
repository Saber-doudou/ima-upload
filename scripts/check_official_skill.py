#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMA 官方技能更新检测工具 v2

对比本地 ima-upload 与官方 ima-skills，输出差异报告。

设计要点（v2 重构）：
  - 官方目录动态定位，兼容 skills/ima-skills 与旧版 skills/skill_<id>
  - 端点比对改为自动提取（官方 references/api.md vs 本地 ima_upload.py），
    不再依赖手工维护的功能清单，官方新增端点会被自动发现
  - check_config.json 作为唯一配置源，只保留「本地独有能力」与
    「非端点类待整合能力」（如插图换链、签名校验）

使用方法：
    python check_official_skill.py              # 完整对比报告
    python check_official_skill.py --brief      # 精简模式
    python check_official_skill.py --json       # JSON 输出
    python check_official_skill.py --strict     # 存在未整合项时退出码 1
    python check_official_skill.py --official-dir <path>   # 指定官方目录
"""

import re
import sys
import json
import argparse
from pathlib import Path

# Windows终端编码修复
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SKILLS_DIR = Path.home() / ".workbuddy" / "skills"
LOCAL_SKILL_DIR = SKILLS_DIR / "ima-upload"
LOCAL_META_FILE = LOCAL_SKILL_DIR / "_meta.json"
LOCAL_SCRIPT = LOCAL_SKILL_DIR / "scripts" / "ima_upload.py"
LOCAL_CONFIG = LOCAL_SKILL_DIR / "scripts" / "check_config.json"
# 上次检查时看到的官方版本（用于判断官方链是否发生更新）
SEEN_VERSION_FILE = LOCAL_SKILL_DIR / "scripts" / ".official_version_seen.json"

# 官方目录候选（按优先级）
OFFICIAL_DIR_CANDIDATES = [
    SKILLS_DIR / "ima-skills",
    SKILLS_DIR / "skill_2053082144792322048",
]

ENDPOINT_RE = re.compile(r"POST\s+(/openapi/[a-zA-Z0-9_/]+)")
LOCAL_ENDPOINT_RE = re.compile(r'["\'](openapi/[a-zA-Z0-9_/]+)["\']')


# ---------- 基础工具 ----------

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"__error__": str(e)}


def find_official_dir(explicit=None):
    """定位官方 ima-skills 目录，返回 (Path|None, 已尝试列表)"""
    if explicit:
        p = Path(explicit)
        return (p if p.exists() else None), [p]

    tried = []
    for cand in OFFICIAL_DIR_CANDIDATES:
        tried.append(cand)
        if cand.exists():
            return cand, tried

    # 兜底：目录名包含 ima-skill
    if SKILLS_DIR.exists():
        for child in sorted(SKILLS_DIR.iterdir()):
            if child.is_dir() and "ima-skill" in child.name.lower():
                tried.append(child)
                return child, tried

    return None, tried


def get_local_version():
    meta = read_json(LOCAL_META_FILE)
    return str(meta.get("version", "unknown"))


def get_official_version(official_dir):
    if not official_dir:
        return "unknown"
    for name in ("meta.json", "_skillhub_meta.json"):
        meta = read_json(official_dir / name)
        ver = meta.get("latest_version") or meta.get("version")
        if ver:
            return str(ver)
    return "unknown"


def query_remote_latest_version(official_dir):
    """
    调用官方 check_skill_update 查询线上最新版本。
    依赖 node 与 ~/.config/ima 凭证；任一不可用时返回 None（静默降级）。
    """
    if not official_dir:
        return None
    api_js = official_dir / "ima_api.cjs"
    if not api_js.exists():
        return None

    current = get_official_version(official_dir)
    try:
        import subprocess
        proc = subprocess.run(
            ["node", str(api_js), "openapi/check_skill_update",
             json.dumps({"version": current})],
            capture_output=True, text=True, timeout=25, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            return None
        resp = json.loads(proc.stdout or "{}")
        return (resp.get("data") or {}).get("latest_version") or None
    except Exception:
        return None


def read_config():
    """读取 check_config.json（唯一配置源）"""
    cfg = read_json(LOCAL_CONFIG)
    if "__error__" in cfg:
        return {"local_exclusive": [], "pending_capabilities": [], "__error__": cfg["__error__"]}
    return cfg


def read_seen_version():
    data = read_json(SEEN_VERSION_FILE)
    return data.get("official_version") if "__error__" not in data else None


def save_seen_version(version):
    if not version or version == "unknown":
        return
    try:
        SEEN_VERSION_FILE.write_text(
            json.dumps({"official_version": version,
                        "checked_at": __import__("datetime").datetime.now().isoformat()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ---------- 端点提取 ----------

def extract_official_endpoints(official_dir):
    """从官方 references/api.md 提取端点集合 {endpoint: module}"""
    endpoints = {}
    if not official_dir:
        return endpoints

    for api_md in official_dir.glob("*/references/api.md"):
        module = api_md.parent.parent.name
        try:
            content = api_md.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in ENDPOINT_RE.finditer(content):
            path = m.group(1).lstrip("/")
            endpoints[path] = module

    # 根目录 SKILL.md 也可能内联端点（旧版本结构）
    root_skill = official_dir / "SKILL.md"
    if root_skill.exists():
        try:
            for m in ENDPOINT_RE.finditer(root_skill.read_text(encoding="utf-8")):
                endpoints.setdefault(m.group(1).lstrip("/"), "root")
        except Exception:
            pass

    return endpoints


def extract_local_endpoints():
    """从本地 ima_upload.py 提取已实现的端点集合"""
    if not LOCAL_SCRIPT.exists():
        return set()
    try:
        content = LOCAL_SCRIPT.read_text(encoding="utf-8")
    except Exception:
        return set()
    return set(LOCAL_ENDPOINT_RE.findall(content))


def scan_official_modules(official_dir):
    """列出官方模块目录与关键脚本"""
    modules = []
    if not official_dir:
        return modules
    for child in sorted(official_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            scripts = []
            sdir = child / "scripts"
            if sdir.exists():
                scripts = [f.name for f in sorted(sdir.iterdir()) if f.is_file()]
            modules.append({"name": child.name, "scripts": scripts})
    return modules


def is_official_package_complete(official_dir):
    """
    官方包完整性判断。
    官方 SKILL.md 是路由层，正文明确要求读取 notes/SKILL.md 与
    knowledge-base/SKILL.md；缺这两个目录即视为残缺安装，路由会失效。
    """
    if not official_dir:
        return False
    required = ["notes/SKILL.md", "knowledge-base/SKILL.md", "ima_api.cjs"]
    return all((official_dir / rel).exists() for rel in required)


def missing_required_files(official_dir):
    if not official_dir:
        return []
    required = ["SKILL.md", "meta.json", "ima_api.cjs",
                "notes/SKILL.md", "notes/references/api.md",
                "knowledge-base/SKILL.md", "knowledge-base/references/api.md"]
    return [rel for rel in required if not (official_dir / rel).exists()]


# ---------- 报告 ----------

def generate_report(as_json=False, brief=False, official_dir=None):
    official, tried = find_official_dir(official_dir)
    local_ver = get_local_version()
    official_ver = get_official_version(official)
    cfg = read_config()

    official_eps = extract_official_endpoints(official)
    local_eps = extract_local_endpoints()

    missing = sorted(set(official_eps) - local_eps)
    extra = sorted(local_eps - set(official_eps))
    covered = sorted(set(official_eps) & local_eps)

    pending = [p for p in cfg.get("pending_capabilities", [])
               if p.get("status") in ("not_integrated", "partial")]
    # 本地 ima-upload 与官方 ima-skills 是两条独立版本链，不跨链比较；
    # 只判断官方链相对上次检查是否发生更新
    last_seen = read_seen_version()
    online_latest = query_remote_latest_version(official)
    latest_known = online_latest or official_ver
    official_updated = bool(last_seen) and latest_known != "unknown" and last_seen != latest_known
    installed_outdated = bool(online_latest and official_ver != "unknown"
                              and online_latest != official_ver)
    package_complete = is_official_package_complete(official)
    absent_files = missing_required_files(official)

    report = {
        "local_version": local_ver,
        "official_version": official_ver,
        "official_latest_online": online_latest,
        "official_version_last_seen": last_seen,
        "official_updated": official_updated,
        "official_dir": str(official) if official else None,
        "official_dir_found": bool(official),
        "official_package_complete": package_complete,
        "official_installed_outdated": installed_outdated,
        "official_missing_files": absent_files,
        "official_endpoint_count": len(official_eps),
        "local_endpoint_count": len(local_eps),
        "covered_count": len(covered),
        "missing_endpoints": missing,
        "extra_endpoints": extra,
        "pending_capabilities": pending,
        "local_exclusive": cfg.get("local_exclusive", []),
        "official_modules": scan_official_modules(official),
        "config_error": cfg.get("__error__"),
        "needs_attention": bool(missing or pending or official_updated or installed_outdated
                                or (official and not package_complete)),
    }

    if as_json:
        save_seen_version(latest_known)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    print("=" * 62)
    print("  IMA 技能对比报告")
    print("=" * 62)
    print(f"  本地技能:   ima-upload v{local_ver}")
    if online_latest and online_latest != official_ver:
        print(f"  官方技能:   v{official_ver}（线上最新 v{online_latest}，本地安装落后）")
    elif online_latest:
        print(f"  官方技能:   v{official_ver}（线上已是最新）")
    else:
        print(f"  官方技能:   v{official_ver}（未能查询线上版本）")
    print(f"  官方目录:   {official if official else '❌ 未找到'}")
    print()
    print(f"  官方端点:   {len(official_eps)} 个")
    print(f"  本地端点:   {len(local_eps)} 个")
    print(f"  已覆盖:     {len(covered)} 个")
    print(f"  缺失:       {len(missing)} 个")
    print()

    if not official:
        print("❌ 未找到官方技能目录，已尝试：")
        for p in tried:
            print(f"   - {p}")
        print("   请安装官方 ima-skills，或用 --official-dir 指定路径")
        print()
    elif not package_complete:
        print("❌ 官方包含不完整（缺子模块，路由会失效）：")
        for rel in absent_files:
            print(f"   缺 {rel}")
        print("   修复：重新下载官方 zip 完整解压，或运行 ima-skills 的更新流程")
        print()

    if missing:
        print("📋 官方有、本地未实现（需跟进）：")
        for ep in missing:
            print(f"  ❌ {ep}   [{official_eps[ep]}]")
        print()

    if pending:
        print("⚠️ 待整合能力（非端点类）：")
        for p in pending:
            mark = "🔶" if p.get("status") == "partial" else "❌"
            print(f"  {mark} {p.get('key')}  {p.get('name', '')}")
            if p.get("note"):
                print(f"      {p['note']}")
        print()

    if installed_outdated:
        print(f"⬆️ 本地安装的官方包落后：v{official_ver} → 线上 v{online_latest}")
        print(f"   更新：下载 https://app-dl.ima.qq.com/skills/ima-skills-{online_latest}.zip 完整解压覆盖")
        print()

    if official_updated:
        print(f"⬆️ 官方技能相对上次检查已更新：v{last_seen} → v{latest_known}")
        print()
    elif latest_known != "unknown" and not last_seen:
        print(f"ℹ️ 已建立官方版本基线 v{latest_known}（下次检查起对比更新）")
        print()

    if not brief:
        print("✅ 已覆盖端点：")
        for ep in covered:
            print(f"  ✅ {ep}")
        print()

        if extra and package_complete:
            print("⭐ 本地独有端点（官方文档未列）：")
            for ep in extra:
                note = ""
                if ep.startswith("openapi/mcp_cloud_agent/"):
                    note = "  （官方 note-images.cjs 实际使用）"
                print(f"  ⭐ {ep}{note}")
            print()

        if report["local_exclusive"]:
            print("⭐ 本地独有能力（官方无对应实现）：")
            for feat in report["local_exclusive"]:
                print(f"  ⭐ {feat}")
            print()

        if report["official_modules"]:
            print("📦 官方模块：")
            for mod in report["official_modules"]:
                scripts = f"  scripts: {', '.join(mod['scripts'])}" if mod["scripts"] else ""
                print(f"  📁 {mod['name']}/{scripts}")
            print()

    save_seen_version(latest_known)
    print(f"结论：{'需要关注' if report['needs_attention'] else '已对齐'}")
    return report


def main():
    parser = argparse.ArgumentParser(description="IMA 官方技能更新检测工具 v2")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--brief", action="store_true", help="精简模式")
    parser.add_argument("--strict", action="store_true", help="存在未整合项时退出码 1")
    parser.add_argument("--official-dir", help="手动指定官方技能目录")
    args = parser.parse_args()

    if not LOCAL_SKILL_DIR.exists():
        print(f"❌ 未找到本地技能目录: {LOCAL_SKILL_DIR}")
        sys.exit(1)

    report = generate_report(
        as_json=args.json, brief=args.brief, official_dir=args.official_dir
    )

    if not report["official_dir_found"] and not args.json:
        sys.exit(1)
    if args.strict and report["needs_attention"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
