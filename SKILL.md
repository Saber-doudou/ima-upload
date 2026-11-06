---
name: ima-upload
display_name: "IMA上传（本地版）"
description: "IMA（腾讯 ima）云端笔记与知识库的本地直连上传技能。走 OpenAPI 直连、不需要 MCP 云代理会话，
  适合批量、可脚本化、可归档的写入与检索。触发场景：把文件或网页写入 IMA 知识库、创建与追加笔记、
  搜索笔记与知识库内容、浏览笔记本与知识库目录、读取笔记正文、把知识库文件原文落盘、把笔记关联进知识库。
  用户可能这么说：帮我记一下、存到 IMA、传到知识库、归档到 IMA、同步到 IMA 云端、备份到云端、知识库里有没有某个东西、
  搜一下知识库、把这篇文章收进知识库、列出我的笔记、读一下那篇笔记、把这个 PDF 或 Excel 或图片传上去。
  涉及的格式包括 PDF、Word、PPT、Excel、CSV、Markdown、TXT、Xmind、HTML、EPUB、PNG/JPG/WebP 图片、
  MP3/M4A/WAV/AAC 音频，以及网页链接和微信公众号文章。技能配置备份、L3 与 L2 流程的 IMA 归档环节也走本技能。
  不适用：只需要把本地图片转成外链再嵌入时用官方 ima-skills（需云代理会话）；普通对话记忆整理用 memory-consolidate。"
---

# IMA 笔记上传 Skill v3.4.4

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

---

## 命令速查与上传安全门

日常调用按上文「确定调用方式」表走即可，它覆盖全部常用场景与关键参数。
逐命令示例、非常用参数组合与边界说明见 `references/cli.md`，遇到下列情况再读：
要用 `--log` / `--content-type` / `--limit` / `--type` / `--folder` 等非常用参数，
或者第一次使用某个子命令、不确定它接受哪些参数。

### 文件上传安全门（与官方 ima-skills 对齐，强制执行）

1. **预检失败即停**：类型/大小/图片签名校验不过立即拒绝，不询问是否继续，不发起任何请求。
2. **title 原样等于 file_name**（含扩展名），不得改名、不得加前缀后缀。
3. **重名只允许两种选择**：`--on-duplicate cancel`（默认，拒绝并提示重命名）或 `--on-duplicate keep-copy`（追加 `_YYYYMMDDHHmmss` 时间戳保留副本，**改名后复查重名**；同秒碰撞时自动追加序号 `_1`/`_2`/`_3` 棘轮重试，序号试尽仍冲突才拒绝）。**不支持覆盖**。
4. **COS 上传失败不得调 add_knowledge**：COS 非零/异常立即中止；仅 COS 成功后才写 `add_knowledge`，且业务响应 `code=0` 才算完成。

图片签名校验（media_type=9）：读文件头 12 字节比对魔数（PNG `89 50 4E 47 0D 0A 1A 0A`、JPEG `FF D8 FF`、WEBP `RIFF....WEBP`），签名与扩展名不符时拦截。大小限制：HTML 10MB、EPUB 50MB、图片 30MB、Markdown/Excel/TXT/Xmind 10MB、其余 200MB。

### 返回语义补充（自 v3.3.0 起）

- `create_note` / `append_note` / `upsert_note` 走 transform 路径时，若 inline 写入报错且自动降级分批成功，返回值带 `degraded: "inline→batched"` 标记；仅 content 相关错误才降级，业务错误（敏感词/权限/配额等）原样抛出不重试。
- `create_note_batched` / `append_note_batched` / `_write_note_batches` 传入空 `batches` 抛 `IMAError("batches 不能为空（无可写入内容）")`，不裸抛 IndexError。
- `download_media` 返回的 `file_name` 是经 `_safe_filename` 清洗后的名字（basename 收敛、剔非法字符、Windows 保留设备名加 `safe_` 前缀），与实际落盘名一致（重名时间戳后缀除外，`path` 字段为准）。

### 资源文件

| 文件 | 包含什么 | 什么时候读 |
|------|---------|-----------|
| `references/cli.md` | 每个子命令的完整示例、参数组合、边界说明 | 用到非常用参数，或第一次用某个子命令 |
| `references/api.md` | Python API 方法表、HTTP 端点、Header 格式 | 用 Python 直接调用脚本，或排查请求层 / 鉴权问题 |
| `references/pitfalls.md` | 已修复的历史坑与脚本实现取舍 | 怀疑踩到已知问题，或要改脚本实现时 |

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
python scripts/test_contract.py        # 76 项契约检查
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

只列会影响调用决策的坑。脚本内部已修复的实现细节见 `references/pitfalls.md`，
排查疑似已修问题时再读。

| 坑 | 原因 | 解决 |
|----|------|------|
| `/tmp/` 路径报"文件不存在" | Git Bash `/tmp/` Python 不识别 | 用 `realpath /tmp/x.md` 获取 Windows 路径 |
| 重复创建同名笔记 | `create` 无去重 | 用 **`upsert`**（同名追加）或 `create --dedup` |
| **`create` 多行内容标题被覆盖** | bash 多行字符串中首行被当标题 | **用 `upsert "标题" --file 文件`**（标题和内容分离），不要用 `create "标题" "多行内容"` 传多行 |
| **知识库列表全为 null** | `search_knowledge_base` 实测返回 `kb_id`/`kb_name`，官方 api.md 却写 `id`/`name` | 已由 `_normalize_kb` 双字段兼容；**新接口以实测为准，不要只信文档** |
| **`search` 结果数不可用于统计** | 服务端返回不全：搜「备份」只回 143 篇，`list --nb` 遍历实际超 248 篇 | 统计一律用 `list --nb` 遍历；`search` 只用于定位单条 |
| **`list --nb --limit` 超过 20 返回空** | `list_note` 单页上限 20，超过静默返回空且 code=0 | 已由 `list_notes` 按偏移量自动翻页；`cursor` 是偏移量不是游标 |
| **给原文链接追加下载参数变 403** | `url_info.url` 是带 `sign` 的预签名链接，查询串含 `media_title`/`response-content-type`，追加任何参数都破坏签名 | 签名 URL 原样用；文件名从 `media_title` 取；仅未签名 URL 才追加官方 disposition 约定 |
| **插图写相对路径被拒** | `![](images/a.png)` 报「不支持的图片来源」：只认 `file://`、`/` 开头、`盘符:\` 三种（官方 `localPath()` 同规则，非本地限制） | 改绝对路径 `![](C:/pics/a.png)` 或 `![](file:///C:/pics/a.png)`；Windows 下 `file:///C:/x` 的前导斜杠本地已修正，官方仍有该缺陷 |
| **小内容报错不自动降级** | 降级条件是切分后 ≥2 批（`len(fallback) > 1`），单批内容遇到 content 类报错直接抛出 | 内容本身就小，拆无可拆；按报错文案调整后重试，或去掉 `--transform-images` 走普通 `create` |

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
