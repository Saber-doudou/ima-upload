---
name: ima-upload
display_name: IMA 笔记上传 - 腾讯IMA云端笔记
description: 腾讯 IMA 云端笔记上传工具，支持创建笔记、追加内容、搜索笔记。凭证自动从 ~/.config/ima/ 读取，无需手动配置。
version: 2.0.1
agent_created: true
---

# IMA 笔记上传 Skill

腾讯 IMA 云端笔记上传，支持创建笔记、追加内容、搜索笔记。

## 凭证（自动读取）

- 文件：`~/.config/ima/client_id`（32位字符串）
- 文件：`~/.config/ima/api_key`
- 环境变量：`IMA_CLIENT_ID` / `IMA_API_KEY`

## 触发条件

用户表达了以下意图之一：
- 上传/保存/备份内容到 IMA
- 把笔记存到 IMA / 上传到 IMA
- 创建 IMA 笔记 / IMA 笔记上传
- 同步到 IMA 云端
- 上传自动化配置到 IMA
- `ima_upload.py` / `ima_upload.ps1` 或任何涉及 IMA 笔记上传的请求

---

## AI 调用指南

当用户要求上传笔记时，按以下步骤执行：

### 1. 判断用哪个脚本

```
优先用 Python（功能更完整）：
  Python 3 可用 → ima_upload.py
  Python 不可用（PowerShell环境） → ima_upload.ps1
```

### 2. 确定调用方式

| 场景 | 推荐方式 |
|------|---------|
| 上传 Markdown 文本 | `create "标题" "内容"` |
| 上传文件内容 | `create "标题" --file path/to/file.md` |
| 追加到已有笔记 | `append note_id "内容"` 或 `append note_id --file update.md` |
| 搜索已有笔记 | `search "关键词"` |
| 自动化调用（需获取 note_id） | 加 `--json` 返回纯 JSON，加 `--log FILE` 记录映射 |

### 3. 典型调用示例

```python
# Python API（AI 内部调用）
import sys
sys.path.insert(0, "/path/to/ima-upload/scripts")
from ima_upload import IMAUploader, create_note

uploader = IMAUploader()
result = uploader.create_note("标题", "# 标题\n\n正文内容")
print(result["note_id"])  # 返回 note_id
```

```bash
# PowerShell（AI 执行命令）
powershell -File "/path/to/ima-upload/scripts/ima_upload.ps1" create "标题" "内容"
```

---

## CLI 命令参考

### create — 创建新笔记

```
ima_upload.py create "标题" "内容"
ima_upload.py create "标题" --file notes.md
ima_upload.py create "标题" --file notes.md --json --log id_map.json
```

| 参数 | 说明 |
|------|------|
| `标题`（位置） | 笔记标题 |
| `内容`（位置） | 正文（省略则用 --file） |
| `--file`, `-f` | 从本地文件读取内容（支持 .md/.txt，UTF-8/GBK 自动识别） |
| `--json`, `-j` | 输出纯 JSON（自动化友好） |
| `--log`, `-l` | 将 `{title, note_id}` 追加写入文件（JSONL格式） |

### append — 追加内容

```
ima_upload.py append "note_id_here" "追加的段落"
ima_upload.py append "note_id_here" --file update.md --json
```

| 参数 | 说明 |
|------|------|
| `note_id`（位置） | 目标笔记 ID |
| `内容`（位置） | 追加内容（省略则用 --file） |
| `--file`, `-f` | 从本地文件读取内容 |
| `--json`, `-j` | 输出纯 JSON |

### search — 搜索笔记

```
ima_upload.py search "关键词"
ima_upload.py search "关键词" --type title
ima_upload.py search "关键词" --type content --json
```

| 参数 | 说明 |
|------|------|
| `关键词`（位置） | 搜索词 |
| `--type`, `-t` | `title`（默认）= 标题搜索；`content` = 正文搜索 |
| `--json`, `-j` | 输出纯 JSON |

---

## Python API

```python
import sys
sys.path.insert(0, "/path/to/ima-upload/scripts")
from ima_upload import IMAUploader, create_note, append_to_note

uploader = IMAUploader()

# 创建笔记
result = uploader.create_note("标题", "# Markdown 正文...")
# 返回: {'note_id': 'note_id_here', 'title': '标题'}

# 追加内容
result = uploader.append_note("note_id_here", "\n\n## 新增章节")
# 返回: {'note_id': 'note_id_here', 'ok': True}

# 搜索
notes = uploader.search_notes("关键词", search_type=0)
# 返回: [{'note_id': '...', 'title': '...', 'summary': '...'}, ...]
```

**注意**：`create_note` 的 `content` 直接作为正文写入，不会自动加 `# 标题` 前缀。如果需要标题，请手动在内容中包含。

---

## PowerShell 封装

`scripts/ima_upload.ps1` — PowerShell 5.1+ 专用，无需 Python 环境。

```powershell
# 创建
.\ima_upload.ps1 create "标题" "内容"
.\ima_upload.ps1 create "标题" -File notes.md -Json -Log id_map.json

# 追加
.\ima_upload.ps1 append "note_id_here" "内容"
.\ima_upload.ps1 append "note_id_here" -File update.md

# 搜索
.\ima_upload.ps1 search "关键词"
.\ima_upload.ps1 search "关键词" -Type content
```

**⚠️ 注意**：必须用 PowerShell（`powershell -File`）执行，不能用 Git Bash 的 `bash`。

---

## API 端点

| 操作 | 端点 | 方法 |
|------|------|------|
| 创建笔记 | `https://ima.qq.com/openapi/note/v1/import_doc` | POST |
| 追加笔记 | `https://ima.qq.com/openapi/note/v1/append_doc` | POST |
| 搜索笔记 | `https://ima.qq.com/openapi/note/v1/search_note` | POST |

## Header 格式

```
ima-openapi-clientid: <client_id>
ima-openapi-apikey: <api_key>
Content-Type: application/json; charset=utf-8
```

**常见错误**：`clientID or apiKey is empty` → header 名拼写错误，正确名称是 `ima-openapi-clientid`（全小写）

## 踩坑记录

| 坑 | 原因 | 解决 |
|----|------|------|
| PowerShell 中文乱码 | PS5.1 默认 GBK / 脚本无 BOM | 脚本已带 UTF-8 BOM；Body 需转字节数组 |
| `clientID or apiKey is empty` | header 名错误 | 用 `ima-openapi-clientid`（全小写）|
| 凭证读不到 | BOM 或空格 | 自动 strip() + BOM 跳过；尝试多路径回退 |
| 内容里标题重复 | `create_note` 自动加了 `# 标题` | v2 已移除自动前缀，content 直接写入 |
| Git Bash 找不到 Python | 环境限制 | 改用 PowerShell 封装脚本 |
| 文件内容乱码 | 文件是 GBK 编码 | 自动尝试 UTF-8 → GBK → Latin-1 |
| **`--file` 传 `/tmp/` 路径报"文件不存在"** 🆕 | Git Bash 的 `/tmp/` 在 Windows Python 下不识别 | **用 `--file` 前必须将路径转为 Windows 绝对路径**：`/tmp/x.md` → `C:\Users\admin\AppData\Local\Temp\x.md`。可在 Bash 中用 `realpath /tmp/x.md` 获取真实路径 |

### 💡 调用时的路径安全提醒

Python 脚本运行在 Windows 下，不支持 Git Bash 风格路径。**传 `--file` 参数时：**
1. ❌ 不要直接传 `/tmp/xxx.md` — Python 会理解为 `C:\tmp\xxx.md`
2. ✅ 先 `realpath /tmp/xxx.md` 拿到完整 Windows 路径
3. ✅ 或者直接用 PowerShell 创建文件在 `$env:TEMP\` 下

## 工具路径速查

| 文件 | 路径 |
|------|------|
| Python 主脚本 | `/path/to/ima-upload/scripts/ima_upload.py` |
| PowerShell 封装 | `/path/to/ima-upload/scripts/ima_upload.ps1` |
| 归档工具 | `/path/to/tools/ima_archive.py` |
| 凭证配置 | `~/.config/ima/` |

## 相关笔记 ID

- 女娲技能使用指南：`[note_id_here]`
- daily-why 备份：`[note_id_v2beta1]` / `[note_id_v2.5]` / `[note_id_v3]`
- english-words 备份：`[note_id_here]`
- IMA 笔记上传指南（README）：`[note_id_here]`
