# ima-upload API 参考

> 按需加载文件。只在需要用 Python 直接调用脚本、或排查请求层与鉴权问题时读。

---

## Python API

```python
from ima_upload import IMAUploader

uploader = IMAUploader()

# 笔记
uploader.create_note("标题", "内容", folder_id=None, transform_images=False)
uploader.upsert_note("标题", "内容", transform_images=False)  # 智能创建/追加
uploader.append_note("note_id", "追加内容", transform_images=False)
uploader.search_notes("关键词", search_type=0)  # 0=标题, 1=正文
uploader.find_exact_title("标题")  # 精确查找同名笔记
uploader.list_notebooks()  # 列出笔记本
uploader.list_notes("notebook_id", limit=20)  # 列出笔记
uploader.get_note_content("note_id")  # 读取笔记正文
uploader.upload_note_image("/path/img.png")  # 单图换链（需云端会话）

# 知识库
uploader.list_knowledge_bases()
uploader.search_knowledge_bases("关键词")
uploader.get_knowledge_base_info("kb_id")
uploader.get_knowledge_list("kb_id", folder_id=None)
uploader.search_knowledge("关键词", "kb_id")
uploader.upload_file_to_kb("file.pdf", "kb_id", on_duplicate="cancel")  # keep-copy=时间戳副本
uploader.download_media("media_id", output_dir="./dl")  # 原文落盘
uploader.import_urls("kb_id", ["https://..."])
uploader.get_media_info("media_id")
uploader.check_repeated_names("kb_id", [("file.pdf", 1)])
uploader.get_addable_knowledge_bases()  # 可添加的知识库
uploader.add_note_to_kb("note_id", "标题", "kb_id")  # 笔记关联到知识库
uploader.find_folder("kb_id", "文件夹名")  # 查找文件夹（注意参数顺序：kb_id 在前）
```

## 典型调用示例

```python
# Python API（AI 内部调用）
import sys
sys.path.insert(0, "/path/to/ima-upload/scripts")
from ima_upload import IMAUploader

uploader = IMAUploader()

# 笔记操作
result = uploader.create_note("标题", "# 标题\n\n正文内容")
result = uploader.upsert_note("标题", "内容")
notes = uploader.search_notes("关键词")
notebooks = uploader.list_notebooks()
notes = uploader.list_notes("notebook_id")
content = uploader.get_note_content("note_id")

# 知识库操作
kbs = uploader.list_knowledge_bases()
result = uploader.upload_file_to_kb("report.pdf", "kb_id")
result = uploader.import_urls("kb_id", ["https://example.com"])
info = uploader.get_media_info("media_id")
```

---

## API 端点

### 笔记模块

| 操作 | 端点 | 方法 |
|------|------|------|
| 创建笔记 | `openapi/note/v1/import_doc` | POST |
| 追加笔记 | `openapi/note/v1/append_doc` | POST |
| 搜索笔记 | `openapi/note/v1/search_note` | POST |
| 笔记本列表 | `openapi/note/v1/list_notebook` | POST |
| 笔记列表 | `openapi/note/v1/list_note` | POST |
| 读取内容 | `openapi/note/v1/get_doc_content` | POST |

### 知识库模块

| 操作 | 端点 | 方法 |
|------|------|------|
| 创建媒体 | `openapi/wiki/v1/create_media` | POST |
| 添加知识 | `openapi/wiki/v1/add_knowledge` | POST |
| 知识库信息 | `openapi/wiki/v1/get_knowledge_base` | POST |
| 内容列表 | `openapi/wiki/v1/get_knowledge_list` | POST |
| 搜索内容 | `openapi/wiki/v1/search_knowledge` | POST |
| 搜索知识库 | `openapi/wiki/v1/search_knowledge_base` | POST |
| 重名检查 | `openapi/wiki/v1/check_repeated_names` | POST |
| 导入URL | `openapi/wiki/v1/import_urls` | POST |
| 可添加知识库列表 | `openapi/wiki/v1/get_addable_knowledge_base_list` | POST |
| 媒体信息 | `openapi/wiki/v1/get_media_info` | POST |
| 图片转存换链（需云端会话） | `openapi/mcp_cloud_agent/upload_temp_file` | POST |
| 换链取访问 URL（需云端会话） | `openapi/mcp_cloud_agent/get_access_url` | POST |

---

## Header 格式

```
ima-openapi-clientid: <client_id>
ima-openapi-apikey: <api_key>
ima-openapi-ctx: skill_version=<version>
Content-Type: application/json; charset=utf-8
```

`ima-openapi-ctx` 与官方 `ima_api.cjs:72` 对齐，每个请求都带；版本号从 `_meta.json` 读取，读不到为 `unknown`。两条传输通道（requests / urllib）与 PowerShell 通道都会带。
