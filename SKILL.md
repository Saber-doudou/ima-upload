# IMA 笔记上传 Skill v3.3.0

腾讯 IMA 云端笔记 + 知识库管理工具。整合官方 ima-skill 知识库模块，保留本地独有优势。

## 功能概览

| 模块 | 功能 | 命令 |
|------|------|------|
| 笔记 | 创建/追加/搜索/智能去重 | `create` / `upsert` / `append` / `search` |
| 笔记 | 浏览笔记本和笔记列表 | `list` / `list --nb` |
| 笔记 | 读取笔记正文 | `read` |
| 笔记 | 插图校验后内嵌 data URL | `--transform-images`（配 `--dry-run` 只查不写） |
| 笔记 | 单图转存换链（需云端会话，本地直连不可用，见「能力边界」B 表） | `image-url` |
| 知识库 | 列出/搜索知识库 | `kb list` / `kb search` |
| 知识库 | 知识库详情 | `kb info` |
| 知识库 | 浏览知识库内容 | `kb ls` |
| 知识库 | 上传文件到知识库 | `kb upload`（`--on-duplicate` / `--content-type`） |
| 知识库 | 添加网页/微信文章 | `kb add-url` |
| 知识库 | 获取媒体信息/原文落盘 | `kb media` / `kb media --download` |
| 知识库 | 可添加的知识库列表 | `kb addable` |
| 知识库 | 笔记关联到知识库 | `kb add-note` |
| 知识库 | 查找/浏览文件夹 | `kb find-folder` / `kb ls --folder` |

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

## 能力边界与通道切换指引（防死循环）

> **止损三原则**：①同一命令同一参数失败 2 次即停止重试，按下方出口换通道；②业务错误（`code` 非 -1，如 100005 无权限、20002 限频、20004 鉴权失败）是账号或服务端问题，换任何技能都没用，如实上报；③本技能报错文案已带出口指引，按报错走，不要改参数硬闯。

### A. 本地可实现（用本技能完成，不要换通道）

| 能力 | 命令 |
|------|------|
| 笔记创建/追加/搜索/读取/列表（含 upsert 智能追加、--dedup、--json、--log） | `create` / `upsert` / `append` / `search` / `read` / `list` |
| 笔记插图校验内嵌（本地路径/网络 URL/data URL，严格小于 3MiB，PNG/JPEG/WebP） | `--transform-images`（配 `--dry-run` 预览批次） |
| 体积超限或 content 相关报错自动降级分批写入 | 自动完成，无需干预 |
| 知识库上传（类型/大小/图片签名预检、keep-copy 时间戳副本、--content-type） | `kb upload` |
| 知识库增删查浏览（add-url / media / download / find-folder / add-note / addable） | `kb ...` |
| 原文落盘（含路径穿越与设备名防护） | `kb media <id> --download` |
| 批量上传多个文件 | 循环调用 `kb upload` 即可（本地可完成） |

### B. 本地受限：换官方技能或 ima 客户端（重试无效就换，别死磕）

| 场景 | 本地表现 | 出口（按顺序试） |
|------|---------|------------------|
| 单图转存换链（需要图片外链） | `image-url` 必报「session ID is required」（`mcp_cloud_agent` 双端点需 MCP 云代理会话，本地直连必然失败，重试无意义） | ① `--transform-images` 内嵌（推荐，本地可完成，多数场景已够用）；② 确需外链：换官方 `ima-skills` 的 `notes/scripts/note-images.cjs --url <图>`（须在 Agent/MCP 云代理会话环境运行）；③ ima 客户端 |
| 无 `url_info` 链接的媒体要原文 | 报「无可下载链接」 | ima 客户端（官方同口径） |
| 笔记正文要 Markdown 格式 | `read` 只回纯文本（`get_doc_content` 不支持 Markdown 读取） | 就是纯文本，官方同样如此，不要重试 |
| 未知/特殊 MIME 文件上传 | `EXT_MAP` 未收录即拒（与官方 preflight 同表） | 官方 `preflight-check.cjs --content-type` 试一次 → ima 客户端 |

### C. 双方都做不了（换 ima 桌面端/客户端，别再试）

| 场景 | 原因 |
|------|------|
| 视频文件 | OpenAPI 不支持（扩展名与 MIME 双黑名单都拦）→ IMA 桌面端 |
| 覆盖同名文件 | 设计禁止（官方同规则）→ `--on-duplicate keep-copy` 保留副本，或取消 |
| 超大小限制文件（PDF/Word/PPT/音频 200MB、图片 30MB、HTML/MD/Excel/TXT/Xmind 10MB、EPUB 50MB） | 服务端限制 → 拆分/压缩文档后重传，或 ima 客户端 |
| 插图超 3MiB | 官方硬限制，禁止压缩转码规避 → ima 客户端插图 |

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
| 重名时保留时间戳副本 | `kb upload file.pdf --kb kb_id --on-duplicate keep-copy` |
| 添加网页到知识库 | `kb add-url "https://..." --kb kb_id` |
| 搜索知识库列表 | `kb search "关键词"` |
| 在知识库内搜索内容 | `kb search "关键词" --kb kb_id` |
| 知识库详情 | `kb info kb_id` |
| 浏览知识库内容/进入文件夹 | `kb ls kb_id [--folder folder_id]` |
| 获取媒体信息/原文链接 | `kb media media_id` |
| 原文落盘（保留原文件名） | `kb media media_id --download --out DIR` |
| 笔记插图内嵌（本地/URL 图转 data URL） | `upsert "标题" --file notes.md --transform-images` |
| 插图只查不写（批次报告） | 加 `--dry-run` |
| 单图转存换链（需 MCP 云代理会话；本地报 session 错误勿重试，出口见「能力边界」B 表） | `image-url /path/img.png` |
| 可添加的知识库 | `kb addable` |
| 笔记关联到知识库 | `kb add-note note_id "标题" --kb kb_id` |
| 查找文件夹 | `kb find-folder "名称" --kb kb_id` |
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
ima_upload.py create "标题" --file notes.md --transform-images        # 插图内嵌
ima_upload.py create "标题" --file notes.md --transform-images --dry-run  # 只出批次报告
```

#### upsert — 智能创建/追加（推荐）

```
ima_upload.py upsert "标题" --file notes.md
ima_upload.py upsert "标题" "内容" --json
ima_upload.py upsert "标题" --file notes.md --transform-images
```

#### append — 追加内容

```
ima_upload.py append "note_id_here" "追加的段落"
ima_upload.py append "note_id_here" --file update.md --json
ima_upload.py append "note_id_here" --file update.md --transform-images
```

#### image-url — 单图转存换链

```
ima_upload.py image-url /path/img.png
ima_upload.py image-url "data:image/png;base64,..." --json
```

> 对应官方 note-images 的 `--url` 模式（`upload_temp_file` → `get_access_url`）。
> **实测限制**：该双端点需要 MCP 云代理会话，本地 client_id 调用报「session ID is required」，
> 失败时会给出明确指引改用 `--transform-images` 内嵌。插图批量处理一律用 `--transform-images`。

#### search — 搜索笔记

```
ima_upload.py search "关键词"
ima_upload.py search "关键词" --type content --json
ima_upload.py search "关键词" --limit 5      # 默认 20，服务端会返回全量匹配
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
ima_upload.py kb upload report.pdf --kb kb_id --on-duplicate keep-copy   # 重名保留时间戳副本
ima_upload.py kb upload downloaded_file --kb kb_id --content-type application/pdf
```

支持的文件类型：PDF, Word, PPT, Excel, CSV, Markdown, PNG/JPG/WebP, TXT, Xmind, MP3/M4A/WAV/AAC, HTML, EPUB

##### ⛔ 文件上传安全门（与官方 ima-skills 对齐，强制执行）

1. **预检失败即停**：类型/大小/图片签名校验不过立即拒绝，不询问是否继续，不发起任何请求。
2. **title 原样等于 file_name**（含扩展名），不得改名、不得加前缀后缀。
3. **重名只允许两种选择**：`--on-duplicate cancel`（默认，拒绝并提示重命名）或 `--on-duplicate keep-copy`（追加 `_YYYYMMDDHHmmss` 时间戳保留副本，**改名后复查重名**；同秒碰撞时自动追加序号 `_1`/`_2`/`_3` 棘轮重试，序号试尽仍冲突才拒绝）。**不支持覆盖**。
4. **COS 上传失败不得调 add_knowledge**：COS 非零/异常立即中止；仅 COS 成功后才写 `add_knowledge`，且业务响应 `code=0` 才算完成。

图片签名校验（media_type=9）：读文件头 12 字节比对魔数（PNG `89 50 4E 47 0D 0A 1A 0A`、JPEG `FF D8 FF`、WEBP `RIFF....WEBP`），签名与扩展名不符时拦截。大小限制：HTML 10MB、EPUB 50MB、图片 30MB、Markdown/Excel/TXT/Xmind 10MB、其余 200MB。

#### kb add-url — 添加网页/微信文章

```
ima_upload.py kb add-url "https://example.com" --kb kb_id
ima_upload.py kb add-url "https://mp.weixin.qq.com/s/xxx" --kb kb_id
ima_upload.py kb add-url url1 url2 url3 --kb kb_id
```

#### kb media — 获取媒体信息 / 原文落盘

```
ima_upload.py kb media media_id           # 获取媒体信息（含访问链接）
ima_upload.py kb media media_id --json
ima_upload.py kb media media_id --download --out ./downloads   # 原文落盘（保留原文件名）
```

> `--download` 通过 `url_info` 请求原文并落盘，文件名优先取 URL 的 `media_title`。
> **实测注意**：`url_info.url` 是带 `sign` 的预签名链接，查询串**不能追加任何参数**（会 403）；
> 脚本已自动识别签名链接并原样使用，仅未签名 URL 才追加官方的
> `response-content-disposition=attachment;filename` 约定。无链接/笔记类型会给出对应指引。
> **安全**：文件名强制 basename 收敛并剔除 Windows 非法字符，Windows 保留设备名（CON/NUL/PRN 等）
> 加 `safe_` 前缀改写（防写入导向设备静默吞数据），落盘前校验落点在目标目录内，
> 恶意 `media_title`（含 `../`、绝对路径）无法写穿 `--out` 目录。

#### kb addable — 获取可添加的知识库列表

```
ima_upload.py kb addable                  # 列出用户有权限添加的知识库
ima_upload.py kb addable --json
```

#### kb add-note — 将笔记关联到知识库

```
ima_upload.py kb add-note note_id "标题" --kb kb_id
ima_upload.py kb add-note note_id "标题" --kb kb_id --json
```

#### kb find-folder — 按名称查找知识库中的文件夹

```
ima_upload.py kb find-folder "文件夹名" --kb kb_id
ima_upload.py kb find-folder "文件夹名" --kb kb_id --json
```

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
uploader.find_folder("文件夹名", "kb_id")  # 查找文件夹
```

返回语义补充（v3.3.0）：
- `create_note` / `append_note` / `upsert_note` 走 transform 路径时，若 inline 写入报错且自动降级分批成功，返回值带 `degraded: "inline→batched"` 标记；仅 content 相关错误才降级，业务错误（敏感词/权限/配额等）原样抛出不重试。
- `create_note_batched` / `append_note_batched` / `_write_note_batches` 传入空 `batches` 抛 `IMAError("batches 不能为空（无可写入内容）")`，不裸抛 IndexError。
- `download_media` 返回的 `file_name` 是经 `_safe_filename` 清洗后的名字（basename 收敛、剔非法字符、Windows 保留设备名加 `safe_` 前缀），与实际落盘名一致（重名时间戳后缀除外，`path` 字段为准）。

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
| 图片转存换链（需云端会话） | `openapi/mcp_cloud_agent/upload_temp_file` | POST |
| 换链取访问 URL（需云端会话） | `openapi/mcp_cloud_agent/get_access_url` | POST |

---

## Header 格式

```
ima-openapi-clientid: <client_id>
ima-openapi-apikey: <api_key>
Content-Type: application/json; charset=utf-8
```

---

## 官方技能更新检测

内置对比工具（v2），可查线上最新版本、诊断官方包完整性、自动比对各 API 端点：

```bash
python scripts/check_official_skill.py                      # 完整对比报告
python scripts/check_official_skill.py --brief              # 精简模式
python scripts/check_official_skill.py --json               # JSON 输出
python scripts/check_official_skill.py --strict             # 有未整合项时退出码 1（可挂自动化）
python scripts/check_official_skill.py --official-dir PATH  # 指定官方包目录
```

检测内容：
- 调用官方 `check_skill_update` 查线上最新版本，与本地安装版本对比
- 诊断官方包是否残缺（缺 `notes/` 或 `knowledge-base/` 会直接判失败）
- 从官方 `*/references/api.md` 与本地脚本自动提取端点做差集，官方新增端点无需手工维护即可发现
- 待整合能力清单以 `scripts/check_config.json` 为唯一配置源

**建议**：官方发版后运行一次，看是否有新能力值得整合。

---

## 契约测试

写操作的正确性用 mock 验证，不产生真实数据：

```bash
python scripts/test_contract.py        # 64 项契约检查
python scripts/test_contract.py -v     # 附失败明细
```

覆盖：每个方法请求路径与 body 字段是否符合官方定义、响应解析能否处理真实字段名、
重名与视频类型拦截（含视频 MIME 黑名单）、图片签名校验（伪造扩展名/坏魔数）、HTML/EPUB 超限拦截、
上传安全门（COS 失败不调 add_knowledge、title 恒等、keep-copy 时间戳副本且改名后复查重名、
序号棘轮重试与试尽拒绝）、原文落盘（签名 URL 透传、强制下载参数、重名后缀、路径穿越防护、
Windows 保留设备名改写）、插图转存（3MiB 限制、data URL、体积降级与写入报错降级、业务错误不降级、
dry-run、换链请求体与 session 降级）、空批防御、`EXT_MAP`/`SIZE_LIMITS` 与官方枚举一致性。

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
| **`create` 多行内容标题被覆盖** | bash 多行字符串中首行被当标题 | **用 `upsert "标题" --file 文件`**（标题和内容分离），不要用 `create "标题" "多行内容"` 传多行 |
| **知识库列表全为 null** | `search_knowledge_base` 实测返回 `kb_id`/`kb_name`，官方 api.md 却写 `id`/`name` | 已由 `_normalize_kb` 双字段兼容；**新接口以实测为准，不要只信文档** |
| **文件夹显示成文件图标** | `get_knowledge_list` 不返回 `folder_id`，文件夹靠 `media_type=99` 识别 | 判 `media_type==99` 或 `media_id` 以 `folder` 开头 |
| **`find-folder` 返回错的 ID** | 曾把 `parent_folder_id`（父目录）当文件夹自身 ID | 文件夹自身 ID 就是其 `media_id`；`parent_folder_id` 只表示所属目录 |
| **`list`/`search` 时间显示报错** | API 的 `create_time`/`modify_time` 是字符串，不是数字 | `_ts_to_str` 先 `int()` 转换再格式化 |
| **`search` 一次返回上百条** | 服务端忽略 `start`/`end` 上限 | 本地按 `--limit` 截断（默认 20） |
| **`search` 结果数不可用于统计** | 服务端返回不全：搜「备份」只回 143 篇，`list --nb` 遍历实际超 248 篇 | 统计一律用 `list --nb` 遍历；`search` 只用于定位单条 |
| **`list --nb --limit` 超过 20 返回空** | `list_note` 单页上限 20，超过静默返回空且 code=0 | 已由 `list_notes` 按偏移量自动翻页；`cursor` 是偏移量不是游标 |
| **`list_note` 响应没有 `next_cursor`** | 只有 `is_end` | 翻页需自行累加已取条数作为下一轮 `cursor` |
| **给原文链接追加下载参数变 403** | `url_info.url` 是带 `sign` 的预签名链接，查询串含 `media_title`/`response-content-type`，追加任何参数都破坏签名 | 签名 URL 原样用；文件名从 `media_title` 取；仅未签名 URL 才追加官方 disposition 约定 |
| **图片换链报 session ID is required** | `mcp_cloud_agent/upload_temp_file` 等双端点需 MCP 云代理会话，本地 client_id 不支持 | 换链失败会明确提示；插图批量处理改用 `--transform-images` 内嵌 |

---

## 工具路径速查

| 文件 | 路径 |
|------|------|
| Python 主脚本 | `~/.workbuddy/skills/ima-upload/scripts/ima_upload.py` |
| PowerShell 封装 | `~/.workbuddy/skills/ima-upload/scripts/ima_upload.ps1` |
| 更新检测脚本 | `~/.workbuddy/skills/ima-upload/scripts/check_official_skill.py` |
| 契约测试 | `~/.workbuddy/skills/ima-upload/scripts/test_contract.py` |
| 检测配置 | `~/.workbuddy/skills/ima-upload/scripts/check_config.json` |
| 凭证配置 | `~/.config/ima/` |
