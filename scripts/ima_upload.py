#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMA上传工具 - Python封装版本

增强版功能：
- 支持 --file 从文件读取内容
- 支持 --json 纯JSON输出（便于自动化）
- 支持 --log 记录 note_id 到本地文件
- 路径自定位，无惧换目录执行

使用方法：
    # 创建笔记
    python ima_upload.py create "标题" "内容"
    python ima_upload.py create "标题" --file README.md
    python ima_upload.py create "标题" --file README.md --json --log id_map.json

    # 追加到已有笔记
    python ima_upload.py append "note_id_here" "追加内容"
    python ima_upload.py append "note_id_here" --file update.md --json

    # 搜索笔记
    python ima_upload.py search "关键词"

    # 一句话创建（兼容旧用法）
    python ima_upload.py "标题" "内容"
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

# 自定位：脚本所在目录作为基路径
_SCRIPT_DIR = Path(__file__).resolve().parent
_CONFIG_DIR = Path.home() / ".config" / "ima"

# 凭证路径（支持多级回退）
_CONFIG_LOCATIONS = [
    _CONFIG_DIR,
    Path.home() / ".config" / "ima",
    Path.home() / ".workbuddy" / "config" / "ima",
]

# 尝试导入requests，失败时使用urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.parse
    import urllib.error
    HAS_REQUESTS = False


class IMAUploader:
    """IMA上传核心类"""

    BASE_URL = "https://ima.qq.com"

    def __init__(self, client_id=None, api_key=None):
        self.client_id = client_id or self._load_credential("client_id")
        self.api_key = api_key or self._load_credential("api_key")

        if not self.client_id or not self.api_key:
            raise IMAError(1,
                "未找到IMA凭证。请确保以下文件存在：\n"
                "  ~/.config/ima/client_id\n"
                "  ~/.config/ima/api_key\n"
                "或设置环境变量：IMA_CLIENT_ID / IMA_API_KEY"
            )

        self.session = None
        if HAS_REQUESTS:
            self.session = requests.Session()
            self.session.headers.update({
                "ima-openapi-clientid": self.client_id,
                "ima-openapi-apikey": self.api_key,
                "Content-Type": "application/json; charset=utf-8"
            })

    def _load_credential(self, name):
        """从多个可能的位置加载凭证"""
        # 尝试环境变量
        env_map = {
            "client_id": ["IMA_CLIENT_ID", "IMA_OPENAPI_CLIENTID"],
            "api_key": ["IMA_API_KEY", "IMA_OPENAPI_APIKEY"]
        }
        for env_var in env_map.get(name, []):
            value = os.environ.get(env_var)
            if value:
                return value.strip()

        # 尝试配置文件
        for config_dir in _CONFIG_LOCATIONS:
            config_file = config_dir / name
            if config_file.exists():
                content = config_file.read_bytes()
                if content.startswith(b'\xef\xbb\xbf'):
                    content = content[3:]
                decoded = content.decode('utf-8').strip()
                if decoded:
                    return decoded
        return None

    def _request(self, api_path, body):
        """发送API请求"""
        url = f"{self.BASE_URL}/{api_path}"

        if HAS_REQUESTS:
            resp = self.session.post(url, json=body, timeout=30)
            return self._parse_response(resp)
        else:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "ima-openapi-clientid": self.client_id,
                    "ima-openapi-apikey": self.api_key,
                    "Content-Type": "application/json; charset=utf-8"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))

    def _parse_response(self, resp):
        """解析API响应"""
        try:
            result = resp.json()
        except json.JSONDecodeError:
            result = {"code": -1, "msg": f"响应解析失败: {resp.text[:200]}"}

        if result.get("code") != 0:
            raise IMAError(result.get("code", -1), result.get("msg", "未知错误"))
        return result

    def create_note(self, title, content, folder_id=None):
        """
        创建新笔记。content 直接作为笔记正文，不自动加标题前缀。

        Args:
            title: 笔记标题
            content: 笔记内容（Markdown格式，直接写入）
            folder_id: 可选，笔记本ID

        Returns:
            dict: {"note_id": "xxx", "title": "xxx"}
        """
        body = {
            "title": title,
            "content": content,
            "content_format": 1
        }
        if folder_id:
            body["folder_id"] = folder_id

        result = self._request("openapi/note/v1/import_doc", body)
        note_id = result.get("data", {}).get("note_id", "")
        return {"note_id": note_id, "title": title}

    def append_note(self, note_id, content):
        """
        追加内容到已有笔记。

        Args:
            note_id: 笔记ID
            content: 追加的 Markdown 内容

        Returns:
            dict: {"note_id": note_id, "ok": True}
        """
        body = {
            "note_id": note_id,
            "content": content,
            "content_format": 1
        }
        result = self._request("openapi/note/v1/append_doc", body)
        return {"note_id": note_id, "ok": True}

    def search_notes(self, keyword, search_type=0):
        """
        搜索笔记。

        Args:
            keyword: 搜索关键词
            search_type: 0=标题搜索, 1=正文搜索

        Returns:
            list: 匹配的笔记列表
        """
        body = {
            "search_type": search_type,
            "query_info": {"title": keyword} if search_type == 0 else {"content": keyword},
            "start": 0,
            "end": 20
        }
        result = self._request("openapi/note/v1/search_note", body)

        notes = result.get("data", {}).get("search_note_infos", [])
        return [
            {
                "note_id": n.get("note_book_info", {}).get("note_id"),
                "title": n.get("note_book_info", {}).get("title"),
                "summary": n.get("note_book_info", {}).get("summary")
            }
            for n in notes
        ]


class IMAError(Exception):
    """IMA API错误"""
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg
        super().__init__(f"[IMA Error {code}] {msg}")


# ========== CLI 入口 ==========

def _build_parser():
    parser = argparse.ArgumentParser(
        description="IMA笔记上传工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python ima_upload.py create "我的笔记" "正文内容"
  python ima_upload.py create "标题" --file notes.md --json --log id_map.json
  python ima_upload.py append note_id_here "追加内容"
  python ima_upload.py append note_id_here --file update.md
  python ima_upload.py search "关键词"
  python ima_upload.py "标题" "内容"   # 兼容旧用法（位置参数）
"""
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # create
    p_create = sub.add_parser("create", help="创建新笔记")
    p_create.add_argument("title", help="笔记标题")
    p_create.add_argument("content", nargs="?", default=None, help="笔记内容（省略时用 --file）")
    p_create.add_argument("--file", "-f", dest="file", help="从文件读取内容")
    p_create.add_argument("--json", "-j", action="store_true", help="JSON纯输出")
    p_create.add_argument("--log", "-l", dest="log_file", help="将 note_id 追加记录到文件")

    # append
    p_append = sub.add_parser("append", help="追加内容到已有笔记")
    p_append.add_argument("note_id", help="笔记ID")
    p_append.add_argument("content", nargs="?", default=None, help="追加内容（省略时用 --file）")
    p_append.add_argument("--file", "-f", dest="file", help="从文件读取内容")
    p_append.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # search
    p_search = sub.add_parser("search", help="搜索笔记")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--type", "-t", choices=["title", "content"], default="title",
                          help="搜索类型（默认：标题）")
    p_search.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    return parser


def _read_file(file_path):
    """读取文件内容，自动处理编码"""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 尝试 UTF-8
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 回退 GBK（Windows 常见）
        try:
            return p.read_text(encoding="gbk")
        except UnicodeDecodeError:
            # 回退 Latin-1（最宽松）
            return p.read_text(encoding="latin-1")


def _log_note(log_file, title, note_id):
    """将 note_id 记录到本地文件（JSONL格式）"""
    entry = {
        "title": title,
        "note_id": note_id,
        "created_at": Path(__file__).stat().st_ctime  # 近似时间
    }
    # 追加到文件
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _output(result, as_json, success_msg):
    """统一输出格式"""
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(success_msg)
        if "note_id" in result:
            print(f"   note_id: {result['note_id']}")
        if "title" in result:
            print(f"   title:   {result['title']}")


def _auto_create(uploader, args):
    """自动创建笔记"""
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")

    result = uploader.create_note(args.title, content)
    if args.log_file:
        _log_note(args.log_file, args.title, result["note_id"])
    _output(result, args.json, "笔记创建成功")
    return result


def _auto_append(uploader, args):
    """自动追加内容"""
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")

    result = uploader.append_note(args.note_id, content)
    _output(result, args.json, f"内容已追加到笔记 {args.note_id}")
    return result


def _auto_search(uploader, args):
    """自动搜索笔记"""
    search_type = 0 if args.type == "title" else 1
    notes = uploader.search_notes(args.keyword, search_type)

    if args.json:
        print(json.dumps(notes, ensure_ascii=False, indent=2))
    else:
        if not notes:
            print(f"未找到匹配「{args.keyword}」的笔记")
        else:
            print(f"找到 {len(notes)} 条笔记：")
            for n in notes:
                print(f"  [{n['note_id']}] {n['title']}")
                if n.get("summary"):
                    print(f"       {n['summary'][:80]}")
    return notes


def main():
    parser = _build_parser()

    # 兼容旧用法：两个位置参数即 create
    if len(sys.argv) >= 3 and not any(a in sys.argv for a in ["create", "append", "search", "-h", "--help"]):
        # 旧用法：ima_upload.py "标题" "内容"
        title_argv = [sys.argv[0], "create", sys.argv[1]] + sys.argv[2:]
        sys.argv = title_argv

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        uploader = IMAUploader()

        if args.command == "create":
            _auto_create(uploader, args)
        elif args.command == "append":
            _auto_append(uploader, args)
        elif args.command == "search":
            _auto_search(uploader, args)

    except IMAError as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": True, "code": e.code, "msg": e.msg}, ensure_ascii=False))
        else:
            print(f"上传失败: {e}")
        sys.exit(1)
    except Exception as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": True, "msg": str(e)}, ensure_ascii=False))
        else:
            print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
