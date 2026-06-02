#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMA上传工具 - Python封装版本 v3.0

功能概览：
  笔记模块：create / upsert / append / search / list / read
  知识库模块：kb list / kb search / kb info / kb upload / kb add-url / kb media

增强特性：
  - --file 从文件读取内容
  - --json 纯JSON输出（便于自动化）
  - --log 记录 note_id 到本地文件
  - upsert 智能创建/追加（防重复）
  - --dedup 创建前检查同名笔记
  - 知识库文件上传（含 COS 上传）
  - 网页/微信文章添加到知识库

使用方法：
    # 笔记操作
    python ima_upload.py create "标题" "内容"
    python ima_upload.py upsert "标题" --file notes.md
    python ima_upload.py append note_id "追加内容"
    python ima_upload.py search "关键词"
    python ima_upload.py list                          # 列出笔记本
    python ima_upload.py list --nb notebook_id         # 列出笔记本中的笔记
    python ima_upload.py read note_id                  # 读取笔记内容

    # 知识库操作
    python ima_upload.py kb list                       # 列出知识库
    python ima_upload.py kb search "关键词" --kb kb_id # 搜索知识库
    python ima_upload.py kb info kb_id                 # 知识库详情
    python ima_upload.py kb upload file.pdf --kb kb_id # 上传文件
    python ima_upload.py kb add-url "https://..." --kb kb_id  # 添加网页
    python ima_upload.py kb media media_id             # 获取媒体信息
"""

import os
import sys
import json
import time
import hashlib
import hmac
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
_SKILL_DIR = _SCRIPT_DIR.parent
_CONFIG_DIR = Path.home() / ".config" / "ima"

# 凭证路径（支持多级回退）
_CONFIG_LOCATIONS = [
    _CONFIG_DIR,
    Path.home() / ".workbuddy" / "config" / "ima",
]

# 尝试导入requests，失败时使用urllib
# 注意：urllib.parse 始终需要（COS 签名用到 quote()）
import urllib.parse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

# ========== 文件类型映射（与官方 preflight-check.cjs 对齐） ==========

EXT_MAP = {
    "pdf": {"media_type": 1, "content_type": "application/pdf"},
    "doc": {"media_type": 3, "content_type": "application/msword"},
    "docx": {"media_type": 3, "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "ppt": {"media_type": 4, "content_type": "application/vnd.ms-powerpoint"},
    "pptx": {"media_type": 4, "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "xls": {"media_type": 5, "content_type": "application/vnd.ms-excel"},
    "xlsx": {"media_type": 5, "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "csv": {"media_type": 5, "content_type": "text/csv"},
    "md": {"media_type": 7, "content_type": "text/markdown"},
    "markdown": {"media_type": 7, "content_type": "text/markdown"},
    "png": {"media_type": 9, "content_type": "image/png"},
    "jpg": {"media_type": 9, "content_type": "image/jpeg"},
    "jpeg": {"media_type": 9, "content_type": "image/jpeg"},
    "webp": {"media_type": 9, "content_type": "image/webp"},
    "txt": {"media_type": 13, "content_type": "text/plain"},
    "xmind": {"media_type": 14, "content_type": "application/x-xmind"},
    "mp3": {"media_type": 15, "content_type": "audio/mpeg"},
    "m4a": {"media_type": 15, "content_type": "audio/x-m4a"},
    "wav": {"media_type": 15, "content_type": "audio/wav"},
    "aac": {"media_type": 15, "content_type": "audio/aac"},
}

MB = 1024 * 1024
SIZE_LIMITS = {
    5: 10 * MB,   # Excel/CSV
    7: 10 * MB,   # Markdown
    13: 10 * MB,  # TXT
    14: 10 * MB,  # Xmind
    9: 30 * MB,   # Image
}
DEFAULT_SIZE_LIMIT = 200 * MB  # PDF, Word, PPT, Audio 等

UNSUPPORTED_VIDEO_EXT = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v", "rmvb", "rm", "3gp"}


class IMAUploader:
    """IMA上传核心类 — 笔记 + 知识库"""

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
        env_map = {
            "client_id": ["IMA_CLIENT_ID", "IMA_OPENAPI_CLIENTID"],
            "api_key": ["IMA_API_KEY", "IMA_OPENAPI_APIKEY"]
        }
        for env_var in env_map.get(name, []):
            value = os.environ.get(env_var)
            if value:
                return value.strip()

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

    def _request(self, api_path, body, timeout=30):
        """发送API请求"""
        url = f"{self.BASE_URL}/{api_path}"

        if HAS_REQUESTS:
            resp = self.session.post(url, json=body, timeout=timeout)
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
            with urllib.request.urlopen(req, timeout=timeout) as response:
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

    # ==================== 笔记模块 ====================

    @staticmethod
    def _validate_utf8(text, field_name="content"):
        """校验字符串为合法 UTF-8（防乱码，与官方 ima-skill 规则对齐）"""
        if not isinstance(text, str):
            raise IMAError(-1, f"{field_name} 必须是字符串，收到 {type(text).__name__}")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as e:
            raise IMAError(-1, f"{field_name} 包含非法 UTF-8 字符: {e}")

    def create_note(self, title, content, folder_id=None):
        """创建新笔记"""
        self._validate_utf8(title, "title")
        self._validate_utf8(content, "content")
        body = {"title": title, "content": content, "content_format": 1}
        if folder_id:
            body["folder_id"] = folder_id
        result = self._request("openapi/note/v1/import_doc", body)
        note_id = result.get("data", {}).get("note_id", "")
        return {"note_id": note_id, "title": title}

    def append_note(self, note_id, content):
        """追加内容到已有笔记"""
        self._validate_utf8(content, "content")
        body = {"note_id": note_id, "content": content, "content_format": 1}
        self._request("openapi/note/v1/append_doc", body)
        return {"note_id": note_id, "ok": True}

    def search_notes(self, keyword, search_type=0):
        """搜索笔记。search_type: 0=标题, 1=正文"""
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
                "summary": n.get("note_book_info", {}).get("summary"),
                "create_time": n.get("note_book_info", {}).get("create_time"),
                "modify_time": n.get("note_book_info", {}).get("modify_time"),
                "folder_name": n.get("note_book_info", {}).get("note_ext_info", {}).get("folder_name"),
            }
            for n in notes
        ]

    def find_exact_title(self, title):
        """精确查找同名笔记"""
        results = self.search_notes(title, search_type=0)
        return [n for n in results if n.get("title") == title]

    def upsert_note(self, title, content, folder_id=None):
        """智能创建/追加：搜索同名笔记，存在则追加，不存在则新建"""
        existing = self.find_exact_title(title)
        if existing:
            target = existing[0]
            self.append_note(target["note_id"], content)
            return {
                "note_id": target["note_id"],
                "title": title,
                "action": "appended",
                "existing_count": len(existing)
            }
        else:
            result = self.create_note(title, content, folder_id=folder_id)
            result["action"] = "created"
            result["existing_count"] = 0
            return result

    def list_notebooks(self):
        """列出所有笔记本"""
        result = self._request("openapi/note/v1/list_notebook", {"cursor": "0", "limit": 20})
        folders = result.get("data", {}).get("note_folder_infos", [])
        return [
            {
                "folder_id": f.get("folder_id"),
                "name": f.get("name"),
                "note_count": f.get("note_number", 0),
                "folder_type": f.get("folder_type"),
            }
            for f in folders
        ]

    def list_notes(self, folder_id=None, limit=20):
        """列出笔记。folder_id=None 则列出全部笔记"""
        body = {"folder_id": folder_id or "", "sort_type": 0, "cursor": "", "limit": limit}
        result = self._request("openapi/note/v1/list_note", body)
        notes = result.get("data", {}).get("note_book_list", [])
        return [
            {
                "note_id": n.get("note_id"),
                "title": n.get("title"),
                "summary": n.get("summary"),
                "create_time": n.get("create_time"),
                "modify_time": n.get("modify_time"),
                "folder_name": n.get("note_ext_info", {}).get("folder_name"),
            }
            for n in notes
        ]

    def get_note_content(self, note_id):
        """读取笔记正文（纯文本格式）"""
        result = self._request("openapi/note/v1/get_doc_content", {
            "note_id": note_id,
            "target_content_format": 0  # 纯文本
        })
        return result.get("data", {}).get("content", "")

    # ==================== 知识库模块 ====================

    def list_knowledge_bases(self, limit=20):
        """列出所有知识库（空 query 搜索）"""
        result = self._request("openapi/wiki/v1/search_knowledge_base", {
            "query": "", "cursor": "", "limit": limit
        })
        infos = result.get("data", {}).get("info_list", [])
        return [{"id": kb.get("id"), "name": kb.get("name"), "cover_url": kb.get("cover_url")} for kb in infos]

    def search_knowledge_bases(self, keyword, limit=20):
        """按名称搜索知识库"""
        result = self._request("openapi/wiki/v1/search_knowledge_base", {
            "query": keyword, "cursor": "", "limit": limit
        })
        infos = result.get("data", {}).get("info_list", [])
        return [{"id": kb.get("id"), "name": kb.get("name"), "cover_url": kb.get("cover_url")} for kb in infos]

    def get_knowledge_base_info(self, kb_ids):
        """获取知识库详情（1-20个）"""
        if isinstance(kb_ids, str):
            kb_ids = [kb_ids]
        result = self._request("openapi/wiki/v1/get_knowledge_base", {"ids": kb_ids})
        return result.get("data", {}).get("infos", {})

    def get_knowledge_list(self, kb_id, folder_id=None, limit=50):
        """浏览知识库内容"""
        body = {"knowledge_base_id": kb_id, "cursor": "", "limit": limit}
        if folder_id:
            body["folder_id"] = folder_id
        result = self._request("openapi/wiki/v1/get_knowledge_list", body)
        data = result.get("data", {})
        return {
            "items": data.get("knowledge_list", []),
            "current_path": data.get("current_path", []),
            "is_end": data.get("is_end", True),
        }

    def search_knowledge(self, keyword, kb_id):
        """在知识库中搜索"""
        result = self._request("openapi/wiki/v1/search_knowledge", {
            "query": keyword, "knowledge_base_id": kb_id, "cursor": ""
        })
        data = result.get("data", {})
        return [
            {
                "media_id": item.get("media_id"),
                "title": item.get("title"),
                "folder_id": item.get("parent_folder_id"),
                "highlight": item.get("highlight_content"),
            }
            for item in data.get("info_list", [])
        ]

    def get_media_info(self, media_id):
        """获取媒体信息（用于查看原文/导出）"""
        result = self._request("openapi/wiki/v1/get_media_info", {"media_id": media_id})
        return result.get("data", {})

    def check_repeated_names(self, kb_id, file_names_and_types, folder_id=None):
        """检查文件名是否重复"""
        params = []
        for name, media_type in file_names_and_types:
            params.append({"name": name, "media_type": media_type})
        body = {"params": params, "knowledge_base_id": kb_id}
        if folder_id:
            body["folder_id"] = folder_id
        result = self._request("openapi/wiki/v1/check_repeated_names", body)
        return result.get("data", {}).get("results", [])

    def import_urls(self, kb_id, urls, folder_id=None):
        """添加网页/微信文章到知识库"""
        body = {"knowledge_base_id": kb_id, "urls": urls, "folder_id": folder_id or kb_id}
        result = self._request("openapi/wiki/v1/import_urls", body)
        return result.get("data", {}).get("results", {})

    def get_addable_knowledge_bases(self, limit=20):
        """获取用户有权限添加内容的知识库列表"""
        result = self._request("openapi/wiki/v1/get_addable_knowledge_base_list", {
            "cursor": "", "limit": limit
        })
        data = result.get("data", {})
        return [
            {"id": kb.get("id"), "name": kb.get("name")}
            for kb in data.get("addable_knowledge_base_list", [])
        ]

    def add_note_to_kb(self, note_id, title, kb_id):
        """将已有笔记关联到知识库（media_type=11）"""
        body = {
            "media_type": 11,
            "note_info": {"content_id": note_id},
            "title": title,
            "knowledge_base_id": kb_id,
        }
        result = self._request("openapi/wiki/v1/add_knowledge", body)
        return {"media_id": result.get("data", {}).get("media_id"), "title": title, "action": "linked"}

    def find_folder(self, kb_id, folder_name):
        """按名称搜索知识库中的文件夹"""
        results = self.search_knowledge(folder_name, kb_id)
        # 文件夹的特征：有 folder_id 且无 media_id，或 title 匹配
        folders = [r for r in results if r.get("folder_id") and folder_name in (r.get("title") or "")]
        return folders

    def get_knowledge_list_paged(self, kb_id, folder_id=None, limit=50):
        """浏览知识库内容（自动翻页，返回全部结果）"""
        all_items = []
        cursor = ""
        while True:
            body = {"knowledge_base_id": kb_id, "cursor": cursor, "limit": limit}
            if folder_id:
                body["folder_id"] = folder_id
            result = self._request("openapi/wiki/v1/get_knowledge_list", body)
            data = result.get("data", {})
            all_items.extend(data.get("knowledge_list", []))
            if data.get("is_end", True):
                break
            cursor = data.get("next_cursor", "")
            if not cursor:
                break
        return all_items

    def upload_file_to_kb(self, file_path, kb_id, folder_id=None):
        """
        上传文件到知识库（完整流程）。
        1. 文件类型/大小检查
        2. 重名检查
        3. create_media 获取 COS 凭证
        4. COS 上传
        5. add_knowledge 确认

        Returns:
            dict: {"media_id": "...", "title": "...", "action": "uploaded"}
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise IMAError(-1, f"文件不存在: {file_path}")

        # Step 1: 文件类型检查
        ext = file_path.suffix.lstrip(".").lower()
        if ext in UNSUPPORTED_VIDEO_EXT:
            raise IMAError(-1, f"不支持的视频文件类型: .{ext}。请使用 IMA 桌面端添加视频。")
        if ext not in EXT_MAP:
            raise IMAError(-1, f"不支持的文件类型: .{ext}。支持的类型: {', '.join(sorted(EXT_MAP.keys()))}")

        mapping = EXT_MAP[ext]
        media_type = mapping["media_type"]
        content_type = mapping["content_type"]
        file_size = file_path.stat().st_size
        file_name = file_path.name

        # Step 2: 大小检查
        size_limit = SIZE_LIMITS.get(media_type, DEFAULT_SIZE_LIMIT)
        if file_size > size_limit:
            limit_mb = size_limit / MB
            size_mb = file_size / MB
            raise IMAError(-1, f"文件大小 {size_mb:.1f} MB 超过限制 {limit_mb:.0f} MB")

        # Step 3: 重名检查
        dup_results = self.check_repeated_names(kb_id, [(file_name, media_type)], folder_id)
        for r in dup_results:
            if r.get("is_repeated"):
                raise IMAError(-1, f"知识库中已存在同名文件「{file_name}」。请重命名后重试。")

        # Step 4: create_media
        create_body = {
            "file_name": file_name,
            "file_size": file_size,
            "content_type": content_type,
            "knowledge_base_id": kb_id,
            "file_ext": ext,
        }
        create_result = self._request("openapi/wiki/v1/create_media", create_body)
        create_data = create_result.get("data", {})
        media_id = create_data.get("media_id")
        cred = create_data.get("cos_credential", {})

        if not media_id or not cred:
            raise IMAError(-1, "create_media 未返回有效凭证")

        # Step 5: COS 上传
        self._cos_upload(
            file_path=str(file_path),
            secret_id=cred["secret_id"],
            secret_key=cred["secret_key"],
            token=cred["token"],
            bucket=cred["bucket_name"],
            region=cred["region"],
            cos_key=cred["cos_key"],
            content_type=content_type,
            start_time=cred.get("start_time"),
            expired_time=cred.get("expired_time"),
        )

        # Step 6: add_knowledge
        add_body = {
            "media_type": media_type,
            "media_id": media_id,
            "title": file_name,
            "knowledge_base_id": kb_id,
            "file_info": {
                "cos_key": cred["cos_key"],
                "file_size": file_size,
                "file_name": file_name,
            },
        }
        if folder_id:
            add_body["folder_id"] = folder_id

        self._request("openapi/wiki/v1/add_knowledge", add_body)
        return {"media_id": media_id, "title": file_name, "action": "uploaded"}

    def _cos_upload(self, file_path, secret_id, secret_key, token, bucket, region,
                    cos_key, content_type, start_time=None, expired_time=None, timeout=300):
        """
        COS 上传（纯 Python 实现，与官方 cos-upload.cjs 对齐）。
        使用 PUT Object + 临时凭证签名。
        """
        file_data = Path(file_path).read_bytes()
        hostname = f"{bucket}.cos.{region}.myqcloud.com"
        pathname = f"/{cos_key}"

        now = int(time.time())
        st = str(start_time or now)
        et = str(expired_time or now + 3600)

        # 构建签名
        sign_headers = {"content-length": str(len(file_data)), "host": hostname}
        authorization = self._build_cos_authorization(
            secret_id, secret_key, "PUT", pathname, sign_headers, st, et
        )

        # 上传头（requests/urllib 共用同一组 header）
        upload_headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(file_data)),
            "Authorization": authorization,
            "x-cos-security-token": token,
        }
        url = f"https://{hostname}{pathname}"

        if HAS_REQUESTS:
            resp = requests.put(url, data=file_data, headers=upload_headers, timeout=timeout)
            if resp.status_code < 200 or resp.status_code >= 300:
                raise IMAError(-1, f"COS 上传失败 (HTTP {resp.status_code}): {resp.text[:200]}")
        else:
            req = urllib.request.Request(url, data=file_data, method="PUT", headers=upload_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status < 200 or response.status >= 300:
                    raise IMAError(-1, f"COS 上传失败 (HTTP {response.status})")

    @staticmethod
    def _build_cos_authorization(secret_id, secret_key, method, pathname, headers, start_time, expired_time):
        """构建 COS Authorization header（与官方 cos-upload.cjs 对齐）"""
        key_time = f"{start_time};{expired_time}"
        sign_key = _hmac_sha1(secret_key, key_time)

        header_keys = sorted(headers.keys())
        http_headers = "&".join(f"{k.lower()}={urllib.parse.quote(str(headers[k]), safe='')}" for k in header_keys)
        http_string = f"{method.lower()}\n{pathname}\n\n{http_headers}\n"
        string_to_sign = f"sha1\n{key_time}\n{_sha1_hex(http_string)}\n"

        signature = hmac.new(
            sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
        ).hexdigest()

        header_list = ";".join(k.lower() for k in header_keys)
        return "&".join([
            "q-sign-algorithm=sha1",
            f"q-ak={secret_id}",
            f"q-sign-time={key_time}",
            f"q-key-time={key_time}",
            f"q-header-list={header_list}",
            "q-url-param-list=",
            f"q-signature={signature}",
        ])


def _hmac_sha1(key, data):
    """HMAC-SHA1 签名（模块级，供 COS 签名复用）"""
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).hexdigest()


def _sha1_hex(data):
    """SHA1 哈希（模块级，供 COS 签名复用）"""
    return hashlib.sha1(data.encode("utf-8")).hexdigest()


class IMAError(Exception):
    """IMA API错误"""
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg
        super().__init__(f"[IMA Error {code}] {msg}")


# ========== CLI 入口 ==========

def _build_parser():
    parser = argparse.ArgumentParser(
        description="IMA笔记上传工具 v3.0（笔记+知识库）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
笔记操作：
  python ima_upload.py create "标题" "内容"
  python ima_upload.py upsert "标题" --file notes.md
  python ima_upload.py append note_id "追加内容"
  python ima_upload.py search "关键词"
  python ima_upload.py list                        # 列出笔记本
  python ima_upload.py list --nb nb_id             # 列出笔记本中的笔记
  python ima_upload.py read note_id                # 读取笔记内容

知识库操作：
  python ima_upload.py kb list                     # 列出知识库
  python ima_upload.py kb search "关键词"           # 搜索知识库
  python ima_upload.py kb info kb_id               # 知识库详情
  python ima_upload.py kb ls kb_id                 # 浏览知识库内容
  python ima_upload.py kb upload file.pdf --kb id  # 上传文件到知识库
  python ima_upload.py kb add-url "https://..." --kb id  # 添加网页
  python ima_upload.py kb media media_id           # 获取媒体信息
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
    p_create.add_argument("--dedup", action="store_true", help="创建前检查同名笔记，存在则警告并跳过")

    # upsert
    p_upsert = sub.add_parser("upsert", help="智能创建：同名存在则追加，不存在则新建")
    p_upsert.add_argument("title", help="笔记标题")
    p_upsert.add_argument("content", nargs="?", default=None, help="笔记内容（省略时用 --file）")
    p_upsert.add_argument("--file", "-f", dest="file", help="从文件读取内容")
    p_upsert.add_argument("--json", "-j", action="store_true", help="JSON纯输出")
    p_upsert.add_argument("--log", "-l", dest="log_file", help="将 note_id 追加记录到文件")

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

    # list（新增）
    p_list = sub.add_parser("list", help="列出笔记本或笔记")
    p_list.add_argument("--nb", dest="nb_id", help="笔记本ID（省略则列出所有笔记本）")
    p_list.add_argument("--limit", type=int, default=20, help="返回数量（默认20）")
    p_list.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # read（新增）
    p_read = sub.add_parser("read", help="读取笔记正文")
    p_read.add_argument("note_id", help="笔记ID")
    p_read.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb（新增 — 知识库模块）
    p_kb = sub.add_parser("kb", help="知识库操作")
    kb_sub = p_kb.add_subparsers(dest="kb_command", help="知识库子命令")

    # kb list
    p_kb_list = kb_sub.add_parser("list", help="列出知识库")
    p_kb_list.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb search
    p_kb_search = kb_sub.add_parser("search", help="搜索知识库或知识库内容")
    p_kb_search.add_argument("keyword", help="搜索关键词")
    p_kb_search.add_argument("--kb", dest="kb_id", help="知识库ID（指定则搜索内容，否则搜索知识库列表）")
    p_kb_search.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb info
    p_kb_info = kb_sub.add_parser("info", help="知识库详情")
    p_kb_info.add_argument("kb_id", help="知识库ID")
    p_kb_info.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb ls
    p_kb_ls = kb_sub.add_parser("ls", help="浏览知识库内容")
    p_kb_ls.add_argument("kb_id", help="知识库ID")
    p_kb_ls.add_argument("--folder", dest="folder_id", help="文件夹ID")
    p_kb_ls.add_argument("--limit", type=int, default=50, help="返回数量")
    p_kb_ls.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb upload
    p_kb_upload = kb_sub.add_parser("upload", help="上传文件到知识库")
    p_kb_upload.add_argument("file", help="文件路径")
    p_kb_upload.add_argument("--kb", dest="kb_id", required=True, help="知识库ID")
    p_kb_upload.add_argument("--folder", dest="folder_id", help="文件夹ID")
    p_kb_upload.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb add-url
    p_kb_url = kb_sub.add_parser("add-url", help="添加网页/微信文章到知识库")
    p_kb_url.add_argument("urls", nargs="+", help="URL列表")
    p_kb_url.add_argument("--kb", dest="kb_id", required=True, help="知识库ID")
    p_kb_url.add_argument("--folder", dest="folder_id", help="文件夹ID")
    p_kb_url.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb media
    p_kb_media = kb_sub.add_parser("media", help="获取媒体信息")
    p_kb_media.add_argument("media_id", help="媒体ID")
    p_kb_media.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb addable
    p_kb_addable = kb_sub.add_parser("addable", help="列出可添加内容的知识库")
    p_kb_addable.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb add-note
    p_kb_addnote = kb_sub.add_parser("add-note", help="将已有笔记关联到知识库")
    p_kb_addnote.add_argument("note_id", help="笔记ID")
    p_kb_addnote.add_argument("title", help="笔记标题（用于在知识库中显示）")
    p_kb_addnote.add_argument("--kb", dest="kb_id", required=True, help="目标知识库ID")
    p_kb_addnote.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb find-folder
    p_kb_findfolder = kb_sub.add_parser("find-folder", help="按名称搜索知识库中的文件夹")
    p_kb_findfolder.add_argument("name", help="文件夹名称")
    p_kb_findfolder.add_argument("--kb", dest="kb_id", required=True, help="知识库ID")
    p_kb_findfolder.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    return parser


def _read_file(file_path):
    """读取文件内容，自动处理编码"""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return p.read_text(encoding="gbk")
        except UnicodeDecodeError:
            return p.read_text(encoding="latin-1")


def _log_note(log_file, title, note_id):
    """将 note_id 记录到本地文件（JSONL格式）"""
    import datetime
    entry = {"title": title, "note_id": note_id, "created_at": datetime.datetime.now().isoformat()}
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


def _ts_to_str(ts_ms):
    """Unix 毫秒时间戳转可读字符串"""
    if not ts_ms:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")


# ========== CLI 命令处理器 ==========

def _cmd_create(uploader, args):
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")
    if getattr(args, 'dedup', False):
        existing = uploader.find_exact_title(args.title)
        if existing:
            if args.json:
                print(json.dumps({
                    "error": True, "code": "DUPLICATE",
                    "msg": f"已存在 {len(existing)} 个同名笔记，跳过创建",
                    "existing": [{"note_id": n["note_id"], "title": n["title"]} for n in existing]
                }, ensure_ascii=False))
            else:
                print(f"⚠️ 已存在 {len(existing)} 个同名笔记「{args.title}」，跳过创建：")
                for n in existing:
                    print(f"   [{n['note_id']}] {n['title']}")
                print("   使用 upsert 命令可自动追加到已有笔记")
            sys.exit(2)
    result = uploader.create_note(args.title, content)
    if args.log_file:
        _log_note(args.log_file, args.title, result["note_id"])
    _output(result, args.json, "笔记创建成功")


def _cmd_upsert(uploader, args):
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")
    result = uploader.upsert_note(args.title, content)
    if args.log_file:
        _log_note(args.log_file, args.title, result["note_id"])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["action"] == "appended":
            print(f"✅ 内容已追加到已有笔记（发现 {result['existing_count']} 个同名笔记）")
        else:
            print("✅ 笔记创建成功（无同名笔记）")
        print(f"   note_id: {result['note_id']}")
        print(f"   title:   {result['title']}")


def _cmd_append(uploader, args):
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")
    result = uploader.append_note(args.note_id, content)
    _output(result, args.json, f"内容已追加到笔记 {args.note_id}")


def _cmd_search(uploader, args):
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
                ts = _ts_to_str(n.get("modify_time"))
                print(f"  [{n['note_id']}] {n['title']}" + (f"  ({ts})" if ts else ""))
                if n.get("folder_name"):
                    print(f"       📁 {n['folder_name']}")
                if n.get("summary"):
                    print(f"       {n['summary'][:80]}")


def _cmd_list(uploader, args):
    if args.nb_id:
        notes = uploader.list_notes(args.nb_id, args.limit)
        if args.json:
            print(json.dumps(notes, ensure_ascii=False, indent=2))
        else:
            if not notes:
                print("该笔记本下暂无笔记")
            else:
                print(f"📋 笔记列表（共 {len(notes)} 篇）：")
                for n in notes:
                    ts = _ts_to_str(n.get("modify_time"))
                    print(f"  [{n['note_id']}] {n['title']}" + (f"  ({ts})" if ts else ""))
    else:
        notebooks = uploader.list_notebooks()
        if args.json:
            print(json.dumps(notebooks, ensure_ascii=False, indent=2))
        else:
            if not notebooks:
                print("暂无笔记本")
            else:
                print(f"📓 笔记本列表（共 {len(notebooks)} 个）：")
                for nb in notebooks:
                    type_label = {0: "用户自建", 1: "全部笔记", 2: "未分类"}.get(nb.get("folder_type"), "")
                    print(f"  [{nb['folder_id']}] {nb['name']}  ({nb['note_count']} 篇)" + (f"  [{type_label}]" if type_label else ""))


def _cmd_read(uploader, args):
    content = uploader.get_note_content(args.note_id)
    if args.json:
        print(json.dumps({"note_id": args.note_id, "content": content}, ensure_ascii=False, indent=2))
    else:
        print(content)


def _cmd_kb_list(uploader, args):
    kbs = uploader.list_knowledge_bases()
    if args.json:
        print(json.dumps(kbs, ensure_ascii=False, indent=2))
    else:
        if not kbs:
            print("暂无知识库")
        else:
            print(f"📚 知识库列表（共 {len(kbs)} 个）：")
            for kb in kbs:
                print(f"  [{kb['id']}] {kb['name']}")


def _cmd_kb_search(uploader, args):
    if args.kb_id:
        results = uploader.search_knowledge(args.keyword, args.kb_id)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            if not results:
                print(f"未找到匹配「{args.keyword}」的内容")
            else:
                print(f"🔍 搜索结果（共 {len(results)} 条）：")
                for r in results:
                    print(f"  [{r['media_id']}] {r['title']}")
                    if r.get("highlight"):
                        print(f"       {r['highlight'][:80]}")
    else:
        kbs = uploader.search_knowledge_bases(args.keyword)
        if args.json:
            print(json.dumps(kbs, ensure_ascii=False, indent=2))
        else:
            if not kbs:
                print(f"未找到匹配「{args.keyword}」的知识库")
            else:
                print(f"📚 搜索到 {len(kbs)} 个知识库：")
                for kb in kbs:
                    print(f"  [{kb['id']}] {kb['name']}")


def _cmd_kb_info(uploader, args):
    info = uploader.get_knowledge_base_info(args.kb_id)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        for kb_id, kb in info.items():
            print(f"📚 {kb.get('name', kb_id)}")
            if kb.get("description"):
                print(f"   📝 {kb['description']}")
            if kb.get("recommended_questions"):
                print("   💡 推荐问题：")
                for q in kb["recommended_questions"]:
                    print(f"      - {q}")


def _cmd_kb_ls(uploader, args):
    result = uploader.get_knowledge_list(args.kb_id, args.folder_id, args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        items = result.get("items", [])
        path_info = result.get("current_path", [])
        if path_info:
            crumbs = " / ".join(p.get("name", "?") for p in path_info)
            print(f"📂 路径: {crumbs}")
        if not items:
            print("该目录下暂无内容")
        else:
            for item in items:
                folder_id = item.get("folder_id")
                if folder_id:
                    # 文件夹
                    fnum = item.get("file_number", 0)
                    snum = item.get("folder_number", 0)
                    print(f"  📁 {item.get('name', '?')}/  ({fnum} 个文件, {snum} 个子文件夹)")
                else:
                    # 文件
                    print(f"  📄 {item.get('title', '?')}  [{item.get('media_id', '')}]")
        if not result.get("is_end"):
            print("  --- 还有更多内容 ---")


def _cmd_kb_upload(uploader, args):
    result = uploader.upload_file_to_kb(args.file, args.kb_id, args.folder_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✅ 文件已上传到知识库")
        print(f"   文件: {result['title']}")
        print(f"   media_id: {result['media_id']}")


def _cmd_kb_add_url(uploader, args):
    results = uploader.import_urls(args.kb_id, args.urls, args.folder_id)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        success = sum(1 for r in results.values() if r.get("ret_code") == 0)
        fail = len(results) - success
        print(f"✅ {success} 个 URL 添加成功" + (f"，{fail} 个失败" if fail else ""))
        for url, r in results.items():
            if r.get("ret_code") != 0:
                print(f"   ❌ {url}: ret_code={r.get('ret_code')}")


def _cmd_kb_media(uploader, args):
    info = uploader.get_media_info(args.media_id)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        mt = info.get("media_type")
        print(f"媒体类型: {mt}")
        if info.get("url_info", {}).get("url"):
            print(f"访问链接: {info['url_info']['url']}")
        elif info.get("notebook_ext_info", {}).get("notebook_id"):
            nb_id = info["notebook_ext_info"]["notebook_id"]
            print(f"关联笔记 ID: {nb_id}")
            print("提示: 使用 `read` 命令读取笔记内容")
        else:
            print("提示: 请使用 IMA 客户端查看原文")


def _cmd_kb_addable(uploader, args):
    kbs = uploader.get_addable_knowledge_bases()
    if args.json:
        print(json.dumps(kbs, ensure_ascii=False, indent=2))
    else:
        if not kbs:
            print("暂无可添加内容的知识库")
        else:
            print(f"📚 可添加内容的知识库（共 {len(kbs)} 个）：")
            for kb in kbs:
                print(f"  [{kb['id']}] {kb['name']}")


def _cmd_kb_add_note(uploader, args):
    result = uploader.add_note_to_kb(args.note_id, args.title, args.kb_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✅ 笔记已关联到知识库")
        print(f"   笔记: {result['title']}")
        print(f"   media_id: {result['media_id']}")


def _cmd_kb_find_folder(uploader, args):
    folders = uploader.find_folder(args.kb_id, args.name)
    if args.json:
        print(json.dumps(folders, ensure_ascii=False, indent=2))
    else:
        if not folders:
            print(f"未找到名为「{args.name}」的文件夹")
        else:
            print(f"📁 找到 {len(folders)} 个匹配文件夹：")
            for f in folders:
                print(f"  [{f['folder_id']}] {f['title']}")


def main():
    parser = _build_parser()

    # 兼容旧用法：两个位置参数即 create
    if len(sys.argv) >= 3 and not any(a in sys.argv for a in [
        "create", "upsert", "append", "search", "list", "read", "kb", "-h", "--help"
    ]):
        title_argv = [sys.argv[0], "create", sys.argv[1]] + sys.argv[2:]
        sys.argv = title_argv

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        uploader = IMAUploader()

        if args.command == "create":
            _cmd_create(uploader, args)
        elif args.command == "upsert":
            _cmd_upsert(uploader, args)
        elif args.command == "append":
            _cmd_append(uploader, args)
        elif args.command == "search":
            _cmd_search(uploader, args)
        elif args.command == "list":
            _cmd_list(uploader, args)
        elif args.command == "read":
            _cmd_read(uploader, args)
        elif args.command == "kb":
            if args.kb_command is None:
                parser.parse_args(["kb", "-h"])
            elif args.kb_command == "list":
                _cmd_kb_list(uploader, args)
            elif args.kb_command == "search":
                _cmd_kb_search(uploader, args)
            elif args.kb_command == "info":
                _cmd_kb_info(uploader, args)
            elif args.kb_command == "ls":
                _cmd_kb_ls(uploader, args)
            elif args.kb_command == "upload":
                _cmd_kb_upload(uploader, args)
            elif args.kb_command == "add-url":
                _cmd_kb_add_url(uploader, args)
            elif args.kb_command == "media":
                _cmd_kb_media(uploader, args)
            elif args.kb_command == "addable":
                _cmd_kb_addable(uploader, args)
            elif args.kb_command == "add-note":
                _cmd_kb_add_note(uploader, args)
            elif args.kb_command == "find-folder":
                _cmd_kb_find_folder(uploader, args)

    except IMAError as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": True, "code": e.code, "msg": e.msg}, ensure_ascii=False))
        else:
            print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": True, "msg": str(e)}, ensure_ascii=False))
        else:
            print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
