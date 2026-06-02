#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMA 官方技能更新检测工具

对比本地 ima-upload 技能与官方 ima-skill 的功能差异，
输出可整合的新功能报告。

使用方法：
    python check_official_skill.py           # 完整对比报告
    python check_official_skill.py --json    # JSON 输出
    python check_official_skill.py --brief   # 精简模式（仅列出差异）
"""

import os
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

# 路径配置
LOCAL_SKILL_DIR = Path.home() / ".workbuddy" / "skills" / "ima-upload"
OFFICIAL_SKILL_DIR = Path.home() / ".workbuddy" / "skills" / "skill_2053082144792322048"
LOCAL_META_FILE = LOCAL_SKILL_DIR / "_meta.json"
OFFICIAL_META_FILE = OFFICIAL_SKILL_DIR / "_skillhub_meta.json"

# 我们已整合的功能清单（手动维护）
# 格式: "api_path" 或 "feature_key": {"status": "integrated"|"not_integrated"|"partial", "since": "v3.0"}
INTEGRATED_FEATURES = {
    # 笔记模块
    "note/create": {"status": "integrated", "since": "v1.0"},
    "note/append": {"status": "integrated", "since": "v1.0"},
    "note/search": {"status": "integrated", "since": "v1.0"},
    "note/upsert": {"status": "integrated", "since": "v2.0", "note": "本地独有，官方无此功能"},
    "note/dedup": {"status": "integrated", "since": "v2.0", "note": "本地独有"},
    "note/list_notebook": {"status": "integrated", "since": "v3.0"},
    "note/list_note": {"status": "integrated", "since": "v3.0"},
    "note/get_doc_content": {"status": "integrated", "since": "v3.0"},
    # 知识库模块
    "kb/list": {"status": "integrated", "since": "v3.0"},
    "kb/search_kb": {"status": "integrated", "since": "v3.0"},
    "kb/info": {"status": "integrated", "since": "v3.0"},
    "kb/list_content": {"status": "integrated", "since": "v3.0"},
    "kb/search_content": {"status": "integrated", "since": "v3.0"},
    "kb/upload_file": {"status": "integrated", "since": "v3.0"},
    "kb/add_url": {"status": "integrated", "since": "v3.0"},
    "kb/media_info": {"status": "integrated", "since": "v3.0"},
    "kb/check_repeated": {"status": "integrated", "since": "v3.0"},
    "kb/addable_list": {"status": "not_integrated"},
    "kb/add_note_to_kb": {"status": "not_integrated"},
    "kb/folder_ops": {"status": "not_integrated"},
}


def read_json_file(path):
    """安全读取 JSON 文件"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def get_local_version():
    """获取本地技能版本"""
    meta = read_json_file(LOCAL_META_FILE)
    return meta.get("version", "unknown")


def get_official_version():
    """获取官方技能版本"""
    meta = read_json_file(OFFICIAL_META_FILE)
    return meta.get("latest_version", meta.get("version", "unknown"))


def scan_official_features():
    """扫描官方技能的功能列表"""
    features = []

    # 扫描 SKILL.md 中的接口
    skill_md = OFFICIAL_SKILL_DIR / "SKILL.md"
    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")

        # 提取模块
        if "notes" in content.lower():
            features.append({"module": "notes", "path": "notes/SKILL.md"})
        if "knowledge" in content.lower():
            features.append({"module": "knowledge-base", "path": "knowledge-base/SKILL.md"})

    # 扫描子模块的 API
    notes_api = OFFICIAL_SKILL_DIR / "notes" / "references" / "api.md"
    if notes_api.exists():
        content = notes_api.read_text(encoding="utf-8")
        # 提取接口名
        for line in content.split("\n"):
            if line.startswith("### ") and "POST" in line:
                features.append({
                    "module": "notes",
                    "api": line.replace("### ", "").strip(),
                })

    kb_api = OFFICIAL_SKILL_DIR / "knowledge-base" / "references" / "api.md"
    if kb_api.exists():
        content = kb_api.read_text(encoding="utf-8")
        for line in content.split("\n"):
            if line.startswith("### ") and "POST" in line:
                features.append({
                    "module": "knowledge-base",
                    "api": line.replace("### ", "").strip(),
                })

    return features


def check_scripts():
    """检查官方技能的脚本文件"""
    scripts = []
    scripts_dir = OFFICIAL_SKILL_DIR / "knowledge-base" / "scripts"
    if scripts_dir.exists():
        for f in scripts_dir.iterdir():
            if f.is_file():
                scripts.append({
                    "name": f.name,
                    "path": str(f.relative_to(OFFICIAL_SKILL_DIR)),
                    "size": f.stat().st_size,
                })

    # 检查根目录的 ima_api.cjs
    ima_api = OFFICIAL_SKILL_DIR / "ima_api.cjs"
    if ima_api.exists():
        scripts.append({
            "name": "ima_api.cjs",
            "path": "ima_api.cjs",
            "size": ima_api.stat().st_size,
            "note": "官方 API 封装脚本，含自动更新检查",
        })

    return scripts


def generate_report(as_json=False, brief=False):
    """生成对比报告"""
    local_ver = get_local_version()
    official_ver = get_official_version()

    # 分类功能
    integrated = {k: v for k, v in INTEGRATED_FEATURES.items() if v["status"] == "integrated"}
    not_integrated = {k: v for k, v in INTEGRATED_FEATURES.items() if v["status"] == "not_integrated"}
    partial = {k: v for k, v in INTEGRATED_FEATURES.items() if v["status"] == "partial"}

    official_features = scan_official_features()
    official_scripts = check_scripts()

    report = {
        "local_version": local_ver,
        "official_version": official_ver,
        "integrated_count": len(integrated),
        "not_integrated_count": len(not_integrated),
        "partial_count": len(partial),
        "not_integrated": list(not_integrated.keys()),
        "partial": list(partial.keys()),
        "official_scripts": [s["name"] for s in official_scripts],
        "local_exclusive": ["upsert", "dedup", "--json", "--log", "Python API"],
    }

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    # 文本报告
    print("=" * 60)
    print("  IMA 技能对比报告")
    print("=" * 60)
    print(f"  本地版本:   v{local_ver}")
    print(f"  官方版本:   v{official_ver}")
    print(f"  已整合:     {len(integrated)} 项")
    print(f"  未整合:     {len(not_integrated)} 项")
    print(f"  部分整合:   {len(partial)} 项")
    print()

    if not_integrated:
        print("📋 未整合的功能（可考虑接入）：")
        for key, info in not_integrated.items():
            print(f"  ❌ {key}")
            if info.get("note"):
                print(f"      {info['note']}")
        print()

    if partial:
        print("⚠️ 部分整合的功能：")
        for key, info in partial.items():
            print(f"  🔶 {key}")
            if info.get("note"):
                print(f"      {info['note']}")
        print()

    if not brief:
        print("✅ 已整合的功能：")
        for key, info in integrated.items():
            note = f" ({info['note']})" if info.get("note") else ""
            print(f"  ✅ {key} [since {info['since']}]{note}")
        print()

        print("🔧 本地独有优势（官方没有）：")
        for feat in report["local_exclusive"]:
            print(f"  ⭐ {feat}")
        print()

        print("📦 官方脚本文件：")
        for s in official_scripts:
            note = f" — {s['note']}" if s.get("note") else ""
            print(f"  📄 {s['path']} ({s['size']} bytes){note}")
        print()

    # 建议
    if not_integrated:
        print("💡 整合建议：")
        if "kb/addable_list" in not_integrated:
            print("  → kb/addable_list: 列出用户可添加的知识库，当用户不确定目标时使用")
        if "kb/add_note_to_kb" in not_integrated:
            print("  → kb/add_note_to_kb: 将笔记关联到知识库（media_type=11）")
        if "kb/folder_ops" in not_integrated:
            print("  → kb/folder_ops: 知识库文件夹管理（创建/定位/浏览）")
        print()

    return report


def main():
    parser = argparse.ArgumentParser(description="IMA 官方技能更新检测工具")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--brief", action="store_true", help="精简模式")
    args = parser.parse_args()

    if not OFFICIAL_SKILL_DIR.exists():
        print("❌ 未找到官方技能目录:")
        print(f"   {OFFICIAL_SKILL_DIR}")
        print("   请先安装官方 ima-skill")
        sys.exit(1)

    generate_report(as_json=args.json, brief=args.brief)


if __name__ == "__main__":
    main()
