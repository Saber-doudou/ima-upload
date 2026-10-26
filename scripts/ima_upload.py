#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMA上传工具 - Python封装版本 v3.3.0

功能概览：
  笔记模块：create / upsert / append / search / list / read / image-url
  知识库模块：kb list / kb search / kb info / kb upload / kb add-url / kb media（含 --download）

增强特性：
  - --file 从文件读取内容
  - --json 纯JSON输出（便于自动化）
  - --log 记录 note_id 到本地文件
  - upsert 智能创建/追加（防重复）
  - --dedup 创建前检查同名笔记
  - --transform-images 笔记插图校验后内嵌 data URL（超限自动降级分批 append_doc）
  - --dry-run 插图批次报告（只检查不写入）
  - 知识库文件上传（含 COS 上传；--on-duplicate keep-copy 时间戳副本；--content-type 显式声明）
  - kb media --download 原文落盘（保留原文件名）
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
    python ima_upload.py upsert "标题" --file n.md --transform-images   # 插图内嵌
    python ima_upload.py image-url /path/img.png       # 单图换链（需云端会话）

    # 知识库操作
    python ima_upload.py kb list                       # 列出知识库
    python ima_upload.py kb search "关键词" --kb kb_id # 搜索知识库
    python ima_upload.py kb info kb_id                 # 知识库详情
    python ima_upload.py kb upload file.pdf --kb kb_id # 上传文件
    python ima_upload.py kb upload a.pdf --kb kb_id --on-duplicate keep-copy
    python ima_upload.py kb add-url "https://..." --kb kb_id  # 添加网页
    python ima_upload.py kb media media_id             # 获取媒体信息
    python ima_upload.py kb media media_id --download --out ./dl  # 原文落盘
"""

import os
import sys
import json
import time
import hmac
import hashlib
import argparse
import tempfile
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
    "html": {"media_type": 20, "content_type": "text/html"},
    "epub": {"media_type": 21, "content_type": "application/epub+zip"},
}

MB = 1024 * 1024
SIZE_LIMITS = {
    5: 10 * MB,   # Excel/CSV
    7: 10 * MB,   # Markdown
    13: 10 * MB,  # TXT
    14: 10 * MB,  # Xmind
    20: 10 * MB,  # HTML
    9: 30 * MB,   # Image
    21: 50 * MB,  # EPUB
}
DEFAULT_SIZE_LIMIT = 200 * MB  # PDF, Word, PPT, Audio 等

UNSUPPORTED_VIDEO_EXT = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v", "rmvb", "rm", "3gp"}

# 官方 preflight-check.cjs UNSUPPORTED_VIDEO_CT：视频 MIME 黑名单（--content-type 命中即拒）
UNSUPPORTED_VIDEO_CT = {
    "video/mp4", "video/x-msvideo", "video/quicktime", "video/x-matroska",
    "video/x-ms-wmv", "video/x-flv", "video/webm",
}

# 媒体类型展示标签（与官方 MediaType 枚举对齐，仅用于人类可读输出）
MEDIA_TYPE_LABELS = {
    1: "PDF", 2: "网页", 3: "Word", 4: "PPT", 5: "Excel",
    6: "公众号", 7: "Markdown", 9: "图片", 11: "笔记", 12: "AI会话",
    13: "TXT", 14: "Xmind", 15: "录音", 16: "视频", 20: "HTML", 21: "EPUB",
    99: "文件夹",
}

# content-type → media_type 反查表（与官方 preflight-check.cjs 优先级对齐：
# 显式 content-type 优先于扩展名）。首个条目为准。
CONTENT_TYPE_MAP = {}
for _v in EXT_MAP.values():
    CONTENT_TYPE_MAP.setdefault(_v["content_type"], _v["media_type"])
CONTENT_TYPE_MAP.update({
    "text/x-markdown": 7,
    "application/md": 7,
    "application/markdown": 7,
})


def _detect_image_type(head):
    """
    识别图片真实签名（魔数），只吃文件头 12 字节。
    与官方 preflight-check.cjs detectImageType 一致：
      PNG: 89 50 4E 47 0D 0A 1A 0A / JPEG: FF D8 FF / WEBP: RIFF....WEBP
    """
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _validate_image_signature(head, expected_type="", source="image"):
    """
    校验图片头字节签名，返回真实 MIME；失败抛 IMAError。
    expected_type 非空时同时校验签名与声明类型一致（上传预检与笔记插图共用）。
    """
    detected = _detect_image_type(head)
    if not detected:
        raise IMAError(-1, f"图片文件签名无效或不受支持（仅支持 PNG/JPEG/WebP）: {source}")
    if expected_type and detected != expected_type:
        raise IMAError(-1, f"文件签名与声明类型（扩展名/content-type）不符：实际 {detected}，声明 {expected_type}: {source}")
    return detected


# Windows 保留设备名（写入会导向设备并静默吞数据，P2-6）
_WINDOWS_RESERVED_NAMES = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def _safe_filename(raw_name, fallback="download"):
    """
    收敛文件名为安全 basename（防路径穿越，P0-1；防保留设备名吞数据，P2-6）。
    1. 剔除目录分量（兼容 / 与 \\ 两种分隔符，防跨平台绕过）
    2. 剔除 Windows 非法字符 <>:"/\\|?* 与控制字符
    3. 剔除结尾点与空格；清洗后为空则回退 fallback
    4. Windows 保留设备名（CON/PRN/AUX/NUL/COM1-9/LPT1-9，含 CON.md 形式）
       加 safe_ 前缀改写（不拒绝，保证下载仍可用）
    """
    name = str(raw_name or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name)
    name = name.rstrip(". ")
    if not name:
        return fallback
    stem = name.split(".", 1)[0].lower()
    if stem in _WINDOWS_RESERVED_NAMES:
        name = "safe_" + name
    return name


def _is_content_related_error(err):
    """
    降级错误分类（P2-7 方案 A）：仅疑似 content 相关错误才值得分批降级重试。
    业务错误码（非 -1，如敏感词/权限/配额）与标题/权限/配额/敏感词类消息直接原样抛出，不做白重试。
    """
    if err.code != -1:
        return False
    msg = err.msg or ""
    msg_l = msg.lower()
    unrelated = ("标题", "权限", "配额", "敏感词", "违规",
                 "title", "permission", "quota", "sensitive", "forbidden", "unauthorized")
    if any(k in msg_l or k in msg for k in unrelated):
        return False
    return True


# ========== 笔记插图转存（与官方 note-images.cjs 对齐） ==========
# 官方行为：图片校验后转 base64 data URL 内嵌，按 text/image 分批写入；
# 换链仅限 --url 单图模式（mcp_cloud_agent 双端点，实测需云端会话）。

import re
import base64
import shutil

NOTE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$", re.I)
MAX_NOTE_IMAGE_SIZE = 3 * 1024 * 1024  # 官方严格小于 3MiB
BATCH_INLINE_LIMIT = 2 * 1024 * 1024   # 超过则降级官方分批 append_doc 模式
_NOTE_IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _local_image_path(source):
    """识别本地路径来源（file:// 或绝对路径），否则返回空串"""
    if source.startswith("file://"):
        return urllib.parse.unquote(source[7:])
    if source.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", source):
        return source
    return ""


def _load_note_image(source, timeout=30):
    """
    读取图片源（本地文件 / http(s) URL / data URL），
    校验魔数与 <3MiB 限制，返回 (mime, bytes)。
    """
    # data URL
    if source.startswith("data:"):
        match = DATA_URL_RE.match(source)
        if not match:
            raise IMAError(-1, "不支持的 data URL：仅接受 base64 的 PNG/JPEG/WebP")
        data = base64.b64decode(match.group(2))
        declared = match.group(1).lower()
        if len(data) >= MAX_NOTE_IMAGE_SIZE:
            raise IMAError(-1, f"图片必须小于 3MiB: data URL（{len(data)} 字节）")
        mime = _validate_image_signature(data[:12], declared, "data URL")
        return mime, data

    # 本地文件
    local = _local_image_path(source)
    if local:
        p = Path(local)
        if not p.is_file():
            raise IMAError(-1, f"图片文件不存在: {local}")
        if p.stat().st_size >= MAX_NOTE_IMAGE_SIZE:
            raise IMAError(-1, f"图片必须小于 3MiB: {local}（{p.stat().st_size} 字节）")
        data = p.read_bytes()
        if len(data) >= MAX_NOTE_IMAGE_SIZE:
            raise IMAError(-1, f"图片必须小于 3MiB: {local}")
        mime = _validate_image_signature(data[:12], "", local)
        return mime, data

    # 网络 URL（边下边计数，超限即断）
    if source.startswith("http://") or source.startswith("https://"):
        try:
            if HAS_REQUESTS:
                resp = requests.get(source, timeout=timeout,
                                    headers={"Accept": "image/png,image/jpeg,image/webp,image/*;q=0.8"},
                                    stream=True)
                if resp.status_code != 200:
                    raise IMAError(-1, f"网络图片下载失败 (HTTP {resp.status_code}): {source}")
                chunks = []
                total = 0
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total >= MAX_NOTE_IMAGE_SIZE:
                        raise IMAError(-1, f"网络图片必须小于 3MiB: {source}")
                    chunks.append(chunk)
                data = b"".join(chunks)
            else:
                req = urllib.request.Request(
                    source, headers={"Accept": "image/png,image/jpeg,image/webp,image/*;q=0.8"})
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    if response.status != 200:
                        raise IMAError(-1, f"网络图片下载失败 (HTTP {response.status}): {source}")
                    data = response.read(MAX_NOTE_IMAGE_SIZE + 1)
                if len(data) >= MAX_NOTE_IMAGE_SIZE:
                    raise IMAError(-1, f"网络图片必须小于 3MiB: {source}")
        except IMAError:
            raise
        except Exception as e:
            raise IMAError(-1, f"网络图片下载失败: {source}（{e}）")
        mime = _validate_image_signature(data[:12], "", source)
        return mime, data

    raise IMAError(-1, f"不支持的图片来源: {source}")


def transform_note_images(markdown, timeout=30):
    """
    将 markdown 中的图片链接校验后内嵌为 data URL（官方内嵌模式）。
    返回 (新markdown, 统计列表)。
    """
    out = []
    stats = []
    last = 0
    for match in NOTE_IMAGE_RE.finditer(markdown):
        alt, src = match.group(1), match.group(2).strip()
        mime, data = _load_note_image(src, timeout=timeout)
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        out.append(markdown[last:match.start()])
        out.append(f"![{alt}]({data_url})")
        stats.append({"source": src, "mime": mime, "bytes": len(data)})
        last = match.end()
    out.append(markdown[last:])
    return "".join(out), stats


def split_note_batches(markdown):
    """
    按 text / image 切批（官方 createBatches 语义），
    供大内容降级为 append_doc 逐批写入。返回 [{type, content}]。
    """
    batches = []
    text = ""
    last = 0

    def flush():
        nonlocal text
        if text.strip():
            batches.append({"type": "text", "content": text})
        text = ""

    for match in NOTE_IMAGE_RE.finditer(markdown):
        text += markdown[last:match.start()]
        flush()
        batches.append({"type": "image", "content": match.group(0)})
        last = match.end()
    text += markdown[last:]
    flush()
    return batches


def _apply_transform(content, transform_images):
    """
    图片转存处理：返回 (content, batches, report)。
    - 未开启：原样返回
    - 开启且内联体积 <= BATCH_INLINE_LIMIT：inline（batches=None）
    - 超限：降级官方分批 append_doc 模式（D2）
    report 含图片统计与批次结构（--dry-run 直接输出）。
    """
    if not transform_images:
        return content, None, None
    transformed, stats = transform_note_images(content)
    size = len(transformed.encode("utf-8"))
    batches = split_note_batches(transformed) if size > BATCH_INLINE_LIMIT else None
    report = {
        "images": stats,
        "total_bytes": size,
        "mode": "batched" if batches else "inline",
        # 降级可读标记（P0-3）：体积超限已降级 / inline 写入报错时自动降级
        "degrade": "inline→batched (size)" if batches else "inline→batched (on-error)",
        "batches": [
            {"index": i + 1, "type": b["type"], "bytes": len(b["content"].encode("utf-8"))}
            for i, b in enumerate(split_note_batches(transformed))
        ],
    }
    return transformed, batches, report


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

    def create_note(self, title, content, folder_id=None, transform_images=False):
        """创建新笔记。transform_images=True 时先内嵌图片；超限或写入报错自动降级分批"""
        self._validate_utf8(title, "title")
        self._validate_utf8(content, "content")
        if not transform_images:
            body = {"title": title, "content": content, "content_format": 1}
            if folder_id:
                body["folder_id"] = folder_id
            result = self._request("openapi/note/v1/import_doc", body)
            note_id = result.get("data", {}).get("note_id", "")
            return {"note_id": note_id, "title": title}

        transformed, batches, _ = _apply_transform(content, True)
        if batches:
            return self.create_note_batched(title, batches, folder_id=folder_id)
        body = {"title": title, "content": transformed, "content_format": 1}
        if folder_id:
            body["folder_id"] = folder_id
        try:
            result = self._request("openapi/note/v1/import_doc", body)
        except IMAError as e:
            # D2 报错降级：仅 content 相关错误值得分批重试（P2-7）
            fallback = split_note_batches(transformed)
            if len(fallback) > 1 and _is_content_related_error(e):
                try:
                    r = self.create_note_batched(title, fallback, folder_id=folder_id)
                    r["degraded"] = "inline→batched"
                    return r
                except IMAError as e2:
                    raise IMAError(e2.code, f"inline 与 batched 均失败: inline（{e.msg}） batched（{e2.msg}）")
            raise
        note_id = result.get("data", {}).get("note_id", "")
        return {"note_id": note_id, "title": title}

    def append_note(self, note_id, content, transform_images=False):
        """追加内容到已有笔记。transform_images=True 时先内嵌图片；超限或写入报错自动降级分批"""
        self._validate_utf8(content, "content")
        if not transform_images:
            body = {"note_id": note_id, "content": content, "content_format": 1}
            self._request("openapi/note/v1/append_doc", body)
            return {"note_id": note_id, "ok": True}

        transformed, batches, _ = _apply_transform(content, True)
        if batches:
            return self._write_note_batches(note_id, batches)
        body = {"note_id": note_id, "content": transformed, "content_format": 1}
        try:
            self._request("openapi/note/v1/append_doc", body)
        except IMAError as e:
            # D2 报错降级：仅 content 相关错误值得分批重试（P2-7）
            fallback = split_note_batches(transformed)
            if len(fallback) > 1 and _is_content_related_error(e):
                try:
                    r = self._write_note_batches(note_id, fallback)
                    r["degraded"] = "inline→batched"
                    return r
                except IMAError as e2:
                    raise IMAError(e2.code, f"inline 与 batched 均失败: inline（{e.msg}） batched（{e2.msg}）")
            raise
        return {"note_id": note_id, "ok": True}

    def _write_note_batches(self, note_id, batches):
        """按官方 createBatches 语义逐批 append_doc，任一批失败即停并报批次号"""
        if not batches:
            raise IMAError(-1, "batches 不能为空（无可写入内容）")
        total = len(batches)
        for i, batch in enumerate(batches, 1):
            try:
                self._request("openapi/note/v1/append_doc", {
                    "note_id": note_id,
                    "content": batch["content"],
                    "content_format": 1,
                })
            except IMAError as e:
                raise IMAError(e.code, f"batch {i}/{total}（{batch['type']}）写入失败: {e.msg}")
        return {"note_id": note_id, "ok": True, "batches": total}

    def append_note_batched(self, note_id, batches):
        """降级路径：内容按批追加（D2）"""
        return self._write_note_batches(note_id, batches)

    def create_note_batched(self, title, batches, folder_id=None):
        """降级路径：首批走 import_doc 创建，其余批 append_doc（D2）"""
        self._validate_utf8(title, "title")
        if not batches:
            raise IMAError(-1, "batches 不能为空（无可写入内容）")
        first, rest = batches[0], batches[1:]
        body = {"title": title, "content": first["content"], "content_format": 1}
        if folder_id:
            body["folder_id"] = folder_id
        result = self._request("openapi/note/v1/import_doc", body)
        note_id = result.get("data", {}).get("note_id", "")
        if rest:
            self._write_note_batches(note_id, rest)
        return {"note_id": note_id, "title": title, "batches": len(batches)}

    def upload_note_image(self, image_source, timeout=30):
        """
        单图转存换链（官方 note-images --url 模式）：
        upload_temp_file → get_access_url 返回 download_url。
        实测该双端点（mcp_cloud_agent 前缀）需要 MCP 云代理会话，
        本地 client_id 调用会报「session ID is required」，失败时给出明确降级指引。
        """
        mime, data = _load_note_image(image_source, timeout=timeout)
        ext = _NOTE_IMAGE_EXT[mime]
        tmpdir = tempfile.mkdtemp(prefix="ima-note-image-")
        try:
            normalized = Path(tmpdir) / f"image{ext}"
            normalized.write_bytes(data)
            try:
                up = self._request("openapi/mcp_cloud_agent/upload_temp_file",
                                   {"file_path": str(normalized)})
            except IMAError as e:
                if e.code == 100001 or "session" in (e.msg or "").lower():
                    raise IMAError(e.code,
                                   f"图片换链暂不可用（{e.msg}）。该端点需要 MCP 云代理会话，"
                                   f"本地直连不支持，且重试必然同样失败，请勿重复调用。出口三选一："
                                   f"①改用 --transform-images 内嵌图片（推荐，本地可完成）；"
                                   f"②换官方 ima-skills 的 notes/scripts/note-images.cjs --url 模式"
                                   f"（须在 Agent/MCP 云代理会话环境运行）；③使用 ima 客户端。")
                raise
            coskey = up.get("data", {}).get("coskey")
            if not coskey:
                raise IMAError(-1, "upload_temp_file 未返回 coskey")
            acc = self._request("openapi/mcp_cloud_agent/get_access_url", {"coskey": coskey})
            url = acc.get("data", {}).get("download_url")
            if not url:
                raise IMAError(-1, "get_access_url 未返回 download_url")
            return {"url": url, "mime": mime}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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

    def upsert_note(self, title, content, folder_id=None, transform_images=False):
        """智能创建/追加：搜索同名笔记，存在则追加，不存在则新建"""
        existing = self.find_exact_title(title)
        if existing:
            target = existing[0]
            self.append_note(target["note_id"], content, transform_images=transform_images)
            return {
                "note_id": target["note_id"],
                "title": title,
                "action": "appended",
                "existing_count": len(existing)
            }
        else:
            result = self.create_note(title, content, folder_id=folder_id,
                                      transform_images=transform_images)
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
        """
        列出笔记。folder_id=None 则列出全部笔记。

        实测约束：
          - limit 单页上限 20，超过会返回空列表且 code=0（静默失败）
          - cursor 是偏移量（已取条数），不是不透明游标
          - 响应只有 is_end，没有 next_cursor
        因此这里按偏移量自动翻页，直到取满 limit 或列表结束。
        """
        target = max(1, int(limit))
        collected = []
        offset = 0

        while len(collected) < target:
            page = min(20, target - len(collected))
            body = {"folder_id": folder_id or "", "sort_type": 0,
                    "cursor": str(offset), "limit": page}
            result = self._request("openapi/note/v1/list_note", body)
            data = result.get("data", {})
            batch = data.get("note_book_list", [])
            if not batch:
                break
            collected.extend(batch)
            if data.get("is_end", True) or len(batch) < page:
                break
            offset += len(batch)

        return [
            {
                "note_id": n.get("note_id"),
                "title": n.get("title"),
                "summary": n.get("summary"),
                "create_time": n.get("create_time"),
                "modify_time": n.get("modify_time"),
                "folder_name": n.get("note_ext_info", {}).get("folder_name"),
            }
            for n in collected[:target]
        ]

    def get_note_content(self, note_id):
        """读取笔记正文（纯文本格式）"""
        result = self._request("openapi/note/v1/get_doc_content", {
            "note_id": note_id,
            "target_content_format": 0  # 纯文本
        })
        return result.get("data", {}).get("content", "")

    # ==================== 知识库模块 ====================

    @staticmethod
    def _normalize_kb(item):
        """
        知识库字段归一化。
        实测差异（官方 api.md 未反映）：
          - search_knowledge_base 返回 kb_id / kb_name
          - get_addable_knowledge_base_list 返回 id / name
        统一输出 id / name，避免下游再判断。
        """
        return {
            "id": item.get("kb_id") or item.get("id"),
            "name": item.get("kb_name") or item.get("name"),
            "cover_url": item.get("cover_url", ""),
            "content_count": item.get("content_count"),
            "role_type": item.get("role_type"),
            "base_type": item.get("base_type"),
        }

    def list_knowledge_bases(self, limit=20):
        """列出所有知识库（空 query 搜索）"""
        result = self._request("openapi/wiki/v1/search_knowledge_base", {
            "query": "", "cursor": "", "limit": limit
        })
        infos = result.get("data", {}).get("info_list", [])
        return [self._normalize_kb(kb) for kb in infos]

    def search_knowledge_bases(self, keyword, limit=20):
        """按名称搜索知识库"""
        result = self._request("openapi/wiki/v1/search_knowledge_base", {
            "query": keyword, "cursor": "", "limit": limit
        })
        infos = result.get("data", {}).get("info_list", [])
        return [self._normalize_kb(kb) for kb in infos]

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
                # 保留原名字段，不要映射成 folder_id：本字段是父目录，不是条目自身 ID
                "parent_folder_id": item.get("parent_folder_id"),
                "media_type": item.get("media_type"),
                "highlight": item.get("highlight_content"),
            }
            for item in data.get("info_list", [])
        ]

    def get_media_info(self, media_id):
        """获取媒体信息（用于查看原文/导出）"""
        result = self._request("openapi/wiki/v1/get_media_info", {"media_id": media_id})
        return result.get("data", {})

    def _http_download(self, url, headers, dest_path, timeout=120):
        """HTTP GET 流式下载到本地（抽离便于测试拦截；两分支错误口径统一为 IMAError）"""
        if HAS_REQUESTS:
            try:
                resp = requests.get(url, headers=headers, stream=True, timeout=timeout)
            except Exception as e:
                raise IMAError(-1, f"原文下载失败（{e}），请使用ima客户端查看原文")
            if resp.status_code != 200:
                raise IMAError(-1, f"原文下载失败 (HTTP {resp.status_code})，请使用ima客户端查看原文")
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        else:
            req = urllib.request.Request(url, headers=headers or {}, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    if response.status != 200:
                        raise IMAError(-1, f"原文下载失败 (HTTP {response.status})，请使用ima客户端查看原文")
                    with open(dest_path, "wb") as f:
                        while True:
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
            except urllib.error.HTTPError as e:
                raise IMAError(-1, f"原文下载失败 (HTTP {e.code})，请使用ima客户端查看原文")
            except urllib.error.URLError as e:
                raise IMAError(-1, f"原文下载失败（{e.reason}），请使用ima客户端查看原文")

    def download_media(self, media_id, output_dir=None, file_name=None):
        """
        下载知识库原文并落盘。
        实测注意：url_info.url 是带 sign 的预签名链接，查询串已含
        response-content-type / media_title，追加任何参数都会破坏签名（403），
        因此签名 URL 原样使用；仅未签名 URL 才按官方约定追加
        response-content-type + response-content-disposition=attachment;filename。
        返回 {"media_id", "file_name", "path"}。
        """
        info = self.get_media_info(media_id)
        if not info or info.get("media_type") is None:
            raise IMAError(-1, f"未查到媒体 {media_id}；请确认 media_id 是否正确（可用 `kb ls` 获取）")
        if info.get("media_type") == 11:
            raise IMAError(-1, "该媒体是笔记类型，请使用 `read` 命令读取笔记内容")
        url_info = info.get("url_info") or {}
        url = url_info.get("url") or ""
        if not url:
            raise IMAError(-1, "该媒体无可下载链接，请使用ima客户端查看原文")
        headers = url_info.get("headers") or {}

        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        is_signed = any(k in query for k in ("sign", "q-signature", "x-cos-signature", "signature"))

        # 确定落盘文件名：显式指定 > URL 的 media_title > URL 末段 > media_id 兜底
        if not file_name:
            title = (query.get("media_title") or [""])[0]
            url_name = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
            file_name = title or url_name or f"{media_id}"

        # P0-1 路径穿越防护：强制 basename 收敛 + 非法字符清洗 + 保留设备名改写（P2-6），空则回退 media_id 兜底名
        fallback = _safe_filename(media_id, "download")
        file_name = _safe_filename(file_name, fallback)

        download_url = url
        if not is_signed:
            # 官方强制下载约定（仅适用于未签名 URL；签名 URL 不能动查询串）
            disposition = f'attachment;filename="{file_name}"'
            sep = "&" if "?" in url else "?"
            download_url = (
                f"{url}{sep}response-content-type=application/octet-stream"
                f"&response-content-disposition={urllib.parse.quote(disposition, safe='')}"
            )

        out_dir = Path(output_dir) if output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / file_name
        if dest.exists():
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            dest = out_dir / f"{dest.stem}_{ts}{dest.suffix}"

        # 落点必须收敛在 out_dir 之内（resolve 后校验，防符号链接/绝对路径绕过）
        out_root = out_dir.resolve()
        try:
            dest.resolve().relative_to(out_root)
        except ValueError:
            raise IMAError(-1, f"文件名非法（落点越出目标目录），已拒绝: {file_name}")

        self._http_download(download_url, headers, str(dest))
        return {"media_id": media_id, "file_name": file_name, "path": str(dest)}

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
        """
        按名称搜索知识库中的文件夹。
        文件夹特征：media_type=99 且 media_id 以 folder 开头；其 media_id 即 folder_id。
        """
        results = self.search_knowledge(folder_name, kb_id)
        return [
            {
                "folder_id": r["media_id"],
                "title": r.get("title"),
                "parent_folder_id": r.get("parent_folder_id"),
            }
            for r in results
            if r.get("media_type") == 99
            and str(r.get("media_id", "")).startswith("folder")
            and folder_name in (r.get("title") or "")
        ]

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

    def upload_file_to_kb(self, file_path, kb_id, folder_id=None, content_type=None, on_duplicate="cancel"):
        """
        上传文件到知识库（完整流程）。
        1. 文件类型/大小/图片签名校验
        2. 重名检查（on_duplicate: cancel=拒绝并提示重命名 / keep-copy=追加时间戳副本）
        3. create_media 获取 COS 凭证
        4. COS 上传（失败即中止，不调 add_knowledge）
        5. add_knowledge 确认（title 恒等于最终文件名）

        content_type 显式传入时优先于扩展名（与官方 preflight 优先级一致）。
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise IMAError(-1, f"文件不存在: {file_path}")

        # Step 1: 文件类型检查（显式 content-type 优先于扩展名）
        ext = file_path.suffix.lstrip(".").lower()
        if ext in UNSUPPORTED_VIDEO_EXT:
            raise IMAError(-1, f"不支持的视频文件类型: .{ext}。请使用 IMA 桌面端添加视频。")
        if content_type and content_type.split(";", 1)[0].strip().lower() in UNSUPPORTED_VIDEO_CT:
            raise IMAError(-1, f"不支持的视频内容类型: {content_type}。请使用 IMA 桌面端添加视频。")

        mapping = None
        if content_type:
            ct_mt = CONTENT_TYPE_MAP.get(content_type)
            if ct_mt is not None:
                mapping = {"media_type": ct_mt, "content_type": content_type}
        if mapping is None:
            if ext not in EXT_MAP:
                raise IMAError(-1, f"不支持的文件类型: .{ext}。支持的类型: {', '.join(sorted(EXT_MAP.keys()))}")
            mapping = EXT_MAP[ext]

        media_type = mapping["media_type"]
        content_type = mapping["content_type"]
        file_size = file_path.stat().st_size
        file_name = file_path.name

        # Step 1b: 图片签名校验（魔数与扩展名/声明类型一致性）
        if media_type == 9:
            with open(file_path, "rb") as fh:
                head = fh.read(12)
            _validate_image_signature(head, content_type, source=file_name)

        # Step 2: 大小检查
        size_limit = SIZE_LIMITS.get(media_type, DEFAULT_SIZE_LIMIT)
        if file_size > size_limit:
            limit_mb = size_limit / MB
            size_mb = file_size / MB
            raise IMAError(-1, f"文件大小 {size_mb:.1f} MB 超过限制 {limit_mb:.0f} MB")

        # Step 3: 重名检查（只允许取消或时间戳副本，不支持覆盖）
        dup_results = self.check_repeated_names(kb_id, [(file_name, media_type)], folder_id)
        for r in dup_results:
            if r.get("is_repeated"):
                if on_duplicate == "keep-copy":
                    import datetime
                    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    stem = file_path.stem
                    suffix = file_path.suffix
                    # P2-8 序号棘轮：秒级时间戳同秒碰撞时追加序号，每个候选名都复查，最多 3 次序号重试
                    candidates = [f"{stem}_{ts}{suffix}"] + [f"{stem}_{ts}_{i}{suffix}" for i in range(1, 4)]
                    chosen = None
                    for cand in candidates:
                        recheck = self.check_repeated_names(kb_id, [(cand, media_type)], folder_id)
                        if not any(r2.get("is_repeated") for r2 in recheck):
                            chosen = cand
                            break
                    if chosen is None:
                        raise IMAError(-1, f"时间戳副本名连试 {len(candidates)} 次均与现有文件重复，已取消上传（不支持覆盖）。")
                    file_name = chosen
                else:
                    raise IMAError(-1, f"知识库中已存在同名文件「{file_name}」。请重命名后重试，或使用 --on-duplicate keep-copy 保留副本。")

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
        description="IMA笔记上传工具 v3.3.0（笔记+知识库）",
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
  python ima_upload.py kb media media_id --download --out ./dl  # 原文落盘
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
    p_create.add_argument("--transform-images", dest="transform_images", action="store_true",
                          help="将 markdown 图片（本地/URL/data URL）校验后内嵌为 data URL（<3MiB，PNG/JPEG/WebP）")
    p_create.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="配合 --transform-images：只校验并输出批次报告，不写入")

    # upsert
    p_upsert = sub.add_parser("upsert", help="智能创建：同名存在则追加，不存在则新建")
    p_upsert.add_argument("title", help="笔记标题")
    p_upsert.add_argument("content", nargs="?", default=None, help="笔记内容（省略时用 --file）")
    p_upsert.add_argument("--file", "-f", dest="file", help="从文件读取内容")
    p_upsert.add_argument("--json", "-j", action="store_true", help="JSON纯输出")
    p_upsert.add_argument("--log", "-l", dest="log_file", help="将 note_id 追加记录到文件")
    p_upsert.add_argument("--transform-images", dest="transform_images", action="store_true",
                          help="将 markdown 图片校验后内嵌为 data URL")
    p_upsert.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="配合 --transform-images：只校验并输出批次报告，不写入")

    # append
    p_append = sub.add_parser("append", help="追加内容到已有笔记")
    p_append.add_argument("note_id", help="笔记ID")
    p_append.add_argument("content", nargs="?", default=None, help="追加内容（省略时用 --file）")
    p_append.add_argument("--file", "-f", dest="file", help="从文件读取内容")
    p_append.add_argument("--json", "-j", action="store_true", help="JSON纯输出")
    p_append.add_argument("--transform-images", dest="transform_images", action="store_true",
                          help="将 markdown 图片校验后内嵌为 data URL")
    p_append.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="配合 --transform-images：只校验并输出批次报告，不写入")

    # image-url（官方 note-images --url 换链模式）
    p_imgurl = sub.add_parser("image-url", help="单图转存换链（需 MCP 云代理会话，本地调用会明确报不支持）")
    p_imgurl.add_argument("src", help="图片源：本地路径 / file:// / data URL")
    p_imgurl.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # search
    p_search = sub.add_parser("search", help="搜索笔记")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--type", "-t", choices=["title", "content"], default="title",
                          help="搜索类型（默认：标题）")
    p_search.add_argument("--limit", type=int, default=20,
                          help="最多返回条数（默认20；需要全量时调大）")
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
    p_kb_upload.add_argument("--content-type", dest="content_type",
                             help="显式声明 MIME（优先于扩展名，如 text/markdown）")
    p_kb_upload.add_argument("--on-duplicate", dest="on_duplicate",
                             choices=["cancel", "keep-copy"], default="cancel",
                             help="重名处理：cancel=拒绝并提示重命名（默认）；keep-copy=追加时间戳保留副本（不支持覆盖）")
    p_kb_upload.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb add-url
    p_kb_url = kb_sub.add_parser("add-url", help="添加网页/微信文章到知识库")
    p_kb_url.add_argument("urls", nargs="+", help="URL列表")
    p_kb_url.add_argument("--kb", dest="kb_id", required=True, help="知识库ID")
    p_kb_url.add_argument("--folder", dest="folder_id", help="文件夹ID")
    p_kb_url.add_argument("--json", "-j", action="store_true", help="JSON纯输出")

    # kb media
    p_kb_media = kb_sub.add_parser("media", help="获取媒体信息（--download 下载原文落盘）")
    p_kb_media.add_argument("media_id", help="媒体ID")
    p_kb_media.add_argument("--download", action="store_true", help="下载原文到本地（保留原文件名）")
    p_kb_media.add_argument("--out", dest="out_dir", help="下载目录（默认当前目录）")
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
    """Unix 毫秒时间戳转可读字符串（实测 API 返回字符串，需容错）"""
    if not ts_ms:
        return ""
    try:
        ts_ms = int(ts_ms)
    except (TypeError, ValueError):
        return ""
    import datetime
    try:
        return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


# ========== CLI 命令处理器 ==========

def _cmd_create(uploader, args):
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")
    transform = getattr(args, "transform_images", False)
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        if not transform:
            raise ValueError("--dry-run 需配合 --transform-images 使用")
        _, _, report = _apply_transform(content, True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
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
    result = uploader.create_note(args.title, content, transform_images=transform)
    if args.log_file:
        _log_note(args.log_file, args.title, result["note_id"])
    _output(result, args.json, "笔记创建成功")


def _cmd_upsert(uploader, args):
    content = args.content
    if args.file:
        content = _read_file(args.file)
    if not content:
        raise ValueError("必须提供内容（位置参数或 --file）")
    transform = getattr(args, "transform_images", False)
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        if not transform:
            raise ValueError("--dry-run 需配合 --transform-images 使用")
        _, _, report = _apply_transform(content, True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    result = uploader.upsert_note(args.title, content, transform_images=transform)
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
    transform = getattr(args, "transform_images", False)
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        if not transform:
            raise ValueError("--dry-run 需配合 --transform-images 使用")
        _, _, report = _apply_transform(content, True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    result = uploader.append_note(args.note_id, content, transform_images=transform)
    _output(result, args.json, f"内容已追加到笔记 {args.note_id}")


def _cmd_image_url(uploader, args):
    result = uploader.upload_note_image(args.src)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✅ 图片已转存")
        print(f"   URL:  {result['url']}")
        print(f"   MIME: {result['mime']}")


def _cmd_search(uploader, args):
    search_type = 0 if args.type == "title" else 1
    notes = uploader.search_notes(args.keyword, search_type)
    # 实测服务端会忽略 start/end 上限返回全量，这里按 --limit 截断，避免淹没上下文
    total = len(notes)
    shown = notes[:max(1, args.limit)]
    if args.json:
        print(json.dumps(shown, ensure_ascii=False, indent=2))
    else:
        if not notes:
            print(f"未找到匹配「{args.keyword}」的笔记")
        else:
            head = f"找到 {total} 条笔记"
            if total > len(shown):
                head += f"，显示前 {len(shown)} 条（--limit 可调整）"
            print(head + "：")
            for n in shown:
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
    elif not content:
        # API 对无效 note_id 返回 code=0 + 空内容，需在应用层提示，避免静默无输出
        print(f"⚠️ 笔记 {args.note_id} 内容为空；请确认 note_id 是否正确、是否为本人笔记")
        sys.exit(2)
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
        return
    if not info:
        # API 对无效 ID 返回空 infos 且 code=0，需显式提示
        print(f"⚠️ 未查到知识库 {args.kb_id}；请确认 ID 是否存在、是否有访问权限")
        sys.exit(2)
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
                media_id = item.get("media_id") or ""
                media_type = item.get("media_type")
                title = item.get("title") or "?"
                # 实测：文件夹靠 media_type=99 识别，其 media_id 以 folder 开头；
                # knowledge_list 不返回 folder_id，也没有 file_number/folder_number
                if media_type == 99 or str(media_id).startswith("folder"):
                    print(f"  📁 {title}/  [{media_id}]")
                else:
                    label = MEDIA_TYPE_LABELS.get(media_type, "")
                    suffix = f"  ({label})" if label else ""
                    print(f"  📄 {title}  [{media_id}]{suffix}")
        if not result.get("is_end"):
            print("  --- 还有更多内容 ---")


def _cmd_kb_upload(uploader, args):
    result = uploader.upload_file_to_kb(
        args.file, args.kb_id, args.folder_id,
        content_type=getattr(args, "content_type", None),
        on_duplicate=getattr(args, "on_duplicate", "cancel"),
    )
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
    if getattr(args, "download", False):
        result = uploader.download_media(args.media_id, output_dir=getattr(args, "out_dir", None))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"✅ 原文已下载")
            print(f"   文件: {result['file_name']}")
            print(f"   路径: {result['path']}")
        return
    info = uploader.get_media_info(args.media_id)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    mt = info.get("media_type")
    if mt is None:
        # 无效 media_id 时 API 仍返回 code=0 但 data 为空，不能落到"请用客户端"的提示
        print(f"⚠️ 未查到媒体 {args.media_id}；请确认 media_id 是否正确（可用 `kb ls` 获取）")
        sys.exit(2)
    label = MEDIA_TYPE_LABELS.get(mt, "")
    print(f"媒体类型: {mt}" + (f"（{label}）" if label else ""))
    if info.get("url_info", {}).get("url"):
        print(f"访问链接: {info['url_info']['url']}")
        headers = info["url_info"].get("headers") or {}
        if headers:
            print(f"访问需带 Header: {', '.join(headers.keys())}")
    elif info.get("notebook_ext_info", {}).get("notebook_id"):
        nb_id = info["notebook_ext_info"]["notebook_id"]
        print(f"关联笔记 ID: {nb_id}")
        print("提示: 使用 `read` 命令读取笔记内容")
    else:
        print("提示: 该媒体没有可访问链接，请使用 IMA 客户端查看原文")


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
        "create", "upsert", "append", "search", "list", "read", "kb", "image-url", "-h", "--help"
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
        elif args.command == "image-url":
            _cmd_image_url(uploader, args)
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
