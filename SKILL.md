# IMA 笔记上传 Skill v3.0

腾讯 IMA 云端笔记 + 知识库管理工具。整合官方 ima-skill 知识库模块，保留本地独有优势。

## 功能概览

| 模块 | 功能 | 命令 |
|------|------|------|
| 笔记 | 创建/追加/搜索/智能去重 | `create` / `upsert` / `append` / `search` |
| 笔记 | 浏览笔记本和笔记列表 | `list` / `list --nb` |
| 笔记 | 读取笔记正文 | `read` |
| 知识库 | 列出/搜索知识库 | `kb list` / `kb search` |
| 知识库 | 浏览知识库内容 | `kb ls` |
| 知识库 | 上传文件到知识库 | `kb upload` |
| 知识库 | 添加网页/微信文章 | `kb add-url` |
| 知识库 | 获取媒体信息/查看原文 | `kb media` |

## 凭证（自动读取）

- 文件：`~/.config/ima/client_id`（32位字符串）
- 文件：`~/.config/ima/api_key`
- 环境变量：`IMA_CLIENT_ID` / `IMA_API_KEY`（或 `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`）

## 触发条件

用户表达了以下意图之一：
- 上传/保存/备份内容到 IMA
- 把笔记存到 IMA / 上传到 IMA
- 创建 IMA 笔记 / IMA 笔记上传
- 同步到 IMA 云端
- 上传文件到知识库 / 添加网页到知识库
- 搜索知识库 / 浏览知识库
- 查看笔记内容 / 列出笔记

---

## AI 调用指南

### 1. 判断用哪个脚本

```
优先用 Python（功能更完整）：
  Python 3 可用 → ima_upload.py
  Python 不可用（PowerShell环境） → ima_upload.ps1（仅支持笔记基础操作）
```

### 2. 确定调用方式

| 场景 | 推荐方式 |
|------|---------|
| 上传 Markdown 文本（可能重复） | **`upsert "标题" "内容"`**（同名追加，无则新建） |
| 上传文件内容（可能重复） | **`upsert "标题" --file path/to/file.md`** |
| 创建笔记（确认无重） | `create "标题" "内容"` |
| 防重复创建 | `create "标题" "内容" --dedup`（有同名则跳过） |
| 追加到指定笔记 | `append note_id "内容"` 或 `append note_id --file update.md` |
| 搜索已有笔记 | `search "关键词"` |
| 列出笔记本 | `list` |
| 列出笔记 | `list --nb notebook_id` |
| 读取笔记内容 | `read note_id` |
| 上传文件到知识库 | `kb upload file.pdf --kb kb_id` |
| 添加网页到知识库 | `kb add-url "https://..." --kb kb_id` |
| 搜索知识库 | `kb search "关键词" --kb kb_id` |
| 自动化调用（需获取 note_id） | 加 `--json` 返回纯 JSON，加 `--log FILE` 记录映射 |

### 3. 典型调用示例

```bash
# Python CLI
python ima_upload.py create "标题" "内容"
python ima_upload.py upsert "标题" --file notes.md --json
python ima_upload.py search "关键词" --json
python ima_upload.py list
python ima_upload.py read note_id_here

# 知识库操作
python ima_upload.py kb list --json
python ima_upload.py kb upload report.pdf --kb kb_id_here
python ima_upload.py kb add-url "https://example.com" --kb kb_id_here
python ima_upload.py kb search "排期" --kb kb_id_here
```

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

## CLI 命令参考

### 笔记操作

#### create — 创建新笔记

```
ima_upload.py create "标题" "内容"
ima_upload.py create "标题" --file notes.md --json --log id_map.json
ima_upload.py create "标题" "内容" --dedup
```

#### upsert — 智能创建/追加（推荐）

```
ima_upload.py upsert "标题" --file notes.md
ima_upload.py upsert "标题" "内容" --json
```

#### append — 追加内容

```
ima_upload.py append "note_id_here" "追加的段落"
ima_upload.py append "note_id_here" --file update.md --json
```

#### search — 搜索笔记

```
ima_upload.py search "关键词"
ima_upload.py search "关键词" --type content --json
```

#### list — 列出笔记本/笔记

```
ima_upload.py list                        # 列出所有笔记本
ima_upload.py list --nb notebook_id       # 列出笔记本中的笔记
ima_upload.py list --json                 # JSON 输出
```

#### read — 读取笔记正文

```
ima_upload.py read note_id                # 读取笔记内容
ima_upload.py read note_id --json         # JSON 输出
```

### 知识库操作

#### kb list — 列出知识库

```
ima_upload.py kb list                     # 列出所有知识库
ima_upload.py kb list --json
```

#### kb search — 搜索知识库/内容

```
ima_upload.py kb search "关键词"           # 搜索知识库列表
ima_upload.py kb search "关键词" --kb id   # 在指定知识库中搜索内容
```

#### kb info — 知识库详情

```
ima_upload.py kb info kb_id
ima_upload.py kb info kb_id --json
```

#### kb ls — 浏览知识库内容

```
ima_upload.py kb ls kb_id
ima_upload.py kb ls kb_id --folder folder_id
ima_upload.py kb ls kb_id --limit 50 --json
```

#### kb upload — 上传文件到知识库

```
ima_upload.py kb upload report.pdf --kb kb_id
ima_upload.py kb upload data.xlsx --kb kb_id --folder folder_id --json
```

支持的文件类型：PDF, Word, PPT, Excel, CSV, Markdown, PNG/JPG/WebP, TXT, Xmind, MP3/M4A/WAV/AAC

#### kb add-url — 添加网页/微信文章

```
ima_upload.py kb add-url "https://example.com" --kb kb_id
ima_upload.py kb add-url "https://mp.weixin.qq.com/s/xxx" --kb kb_id
ima_upload.py kb add-url url1 url2 url3 --kb kb_id
```

#### kb media — 获取媒体信息

```
ima_upload.py kb media media_id           # 获取媒体信息（含访问链接）
ima_upload.py kb media media_id --json
```

---

## Python API

```python
from ima_upload import IMAUploader

uploader = IMAUploader()

# 笔记
uploader.create_note("标题", "内容", folder_id=None)
uploader.upsert_note("标题", "内容")  # 智能创建/追加
uploader.append_note("note_id", "追加内容")
uploader.search_notes("关键词", search_type=0)  # 0=标题, 1=正文
uploader.find_exact_title("标题")  # 精确查找同名笔记
uploader.list_notebooks()  # 列出笔记本
uploader.list_notes("notebook_id", limit=20)  # 列出笔记
uploader.get_note_content("note_id")  # 读取笔记正文

# 知识库
uploader.list_knowledge_bases()
uploader.search_knowledge_bases("关键词")
uploader.get_knowledge_base_info("kb_id")
uploader.get_knowledge_list("kb_id", folder_id=None)
uploader.search_knowledge("关键词", "kb_id")
uploader.upload_file_to_kb("file.pdf", "kb_id")
uploader.import_urls("kb_id", ["https://..."])
uploader.get_media_info("media_id")
uploader.check_repeated_names("kb_id", [("file.pdf", 1)])
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
| 媒体信息 | `openapi/wiki/v1/get_media_info` | POST |

---

## Header 格式

```
ima-openapi-clientid: <client_id>
ima-openapi-apikey: <api_key>
Content-Type: application/json; charset=utf-8
```

---

## 官方技能更新检测

本地技能内置了官方技能对比工具，可检测官方 ima-skill 的新功能：

```bash
python scripts/check_official_skill.py         # 完整对比报告
python scripts/check_official_skill.py --brief  # 精简模式
python scripts/check_official_skill.py --json   # JSON 输出
```

**建议**：每次官方 ima-skill 更新后运行一次，查看是否有新功能值得整合。

---

## 踩坑记录

| 坑 | 原因 | 解决 |
|----|------|------|
| PowerShell 中文乱码 | PS5.1 默认 GBK | 脚本已带 UTF-8 BOM；Body 需转字节数组 |
| `clientID or apiKey is empty` | header 名错误 | 用 `ima-openapi-clientid`（全小写）|
| 凭证读不到 | BOM 或空格 | 自动 strip() + BOM 跳过；尝试多路径回退 |
| 内容里标题重复 | `create_note` 自动加了 `# 标题` | v2 已移除自动前缀，content 直接写入 |
| Git Bash 找不到 Python | 环境限制 | 改用 PowerShell 封装脚本 |
| 文件内容乱码 | 文件是 GBK 编码 | 自动尝试 UTF-8 → GBK → Latin-1 |
| `/tmp/` 路径报"文件不存在" | Git Bash `/tmp/` Python 不识别 | 用 `realpath /tmp/x.md` 获取 Windows 路径 |
| 重复创建同名笔记 | `create` 无去重 | 用 **`upsert`**（同名追加）或 `create --dedup` |
| COS 上传超时 | 大文件超 120s | 默认 timeout 300s，大文件可自行调整 |

---

## 工具路径速查

| 文件 | 路径 |
|------|------|
| Python 主脚本 | `~/.workbuddy/skills/ima-upload/scripts/ima_upload.py` |
| PowerShell 封装 | `~/.workbuddy/skills/ima-upload/scripts/ima_upload.ps1` |
| 更新检测脚本 | `~/.workbuddy/skills/ima-upload/scripts/check_official_skill.py` |
| 凭证配置 | `~/.config/ima/` |
