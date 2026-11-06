# ima-upload CLI 命令参考

> 按需加载文件。SKILL.md 正文的「确定调用方式」表已覆盖常用场景，这里放全部子命令的示例与参数组合。
> 命令与参数必须原样使用，不要改写引号、参数顺序或缩写。

---

## 笔记操作

### create — 创建新笔记

```
ima_upload.py create "标题" "内容"
ima_upload.py create "标题" --file notes.md --json --log id_map.json
ima_upload.py create "标题" "内容" --dedup
ima_upload.py create "标题" --file notes.md --transform-images        # 插图内嵌
ima_upload.py create "标题" --file notes.md --transform-images --dry-run  # 只出批次报告
```

### upsert — 智能创建/追加（推荐）

```
ima_upload.py upsert "标题" --file notes.md
ima_upload.py upsert "标题" "内容" --json
ima_upload.py upsert "标题" --file notes.md --transform-images
```

### append — 追加内容

```
ima_upload.py append "note_id_here" "追加的段落"
ima_upload.py append "note_id_here" --file update.md --json
ima_upload.py append "note_id_here" --file update.md --transform-images
```

### image-url — 单图转存换链

```
ima_upload.py image-url /path/img.png
ima_upload.py image-url "data:image/png;base64,..." --json
```

> 对应官方 note-images 的 `--url` 模式（`upload_temp_file` → `get_access_url`）。
> **实测限制**：该双端点需要 MCP 云代理会话，本地 client_id 调用报「session ID is required」，
> 失败时会给出明确指引改用 `--transform-images` 内嵌。插图批量处理一律用 `--transform-images`。

### search — 搜索笔记

```
ima_upload.py search "关键词"
ima_upload.py search "关键词" --type content --json
ima_upload.py search "关键词" --limit 5      # 默认 20，服务端会返回全量匹配
```

### list — 列出笔记本/笔记

```
ima_upload.py list                        # 列出所有笔记本
ima_upload.py list --nb notebook_id       # 列出笔记本中的笔记
ima_upload.py list --json                 # JSON 输出
```

### read — 读取笔记正文

```
ima_upload.py read note_id                # 读取笔记内容
ima_upload.py read note_id --json         # JSON 输出
```

## 知识库操作

### kb list — 列出知识库

```
ima_upload.py kb list                     # 列出所有知识库
ima_upload.py kb list --json
```

### kb search — 搜索知识库/内容

```
ima_upload.py kb search "关键词"           # 搜索知识库列表
ima_upload.py kb search "关键词" --kb id   # 在指定知识库中搜索内容
```

### kb info — 知识库详情

```
ima_upload.py kb info kb_id
ima_upload.py kb info kb_id --json
```

### kb ls — 浏览知识库内容

```
ima_upload.py kb ls kb_id
ima_upload.py kb ls kb_id --folder folder_id
ima_upload.py kb ls kb_id --limit 50 --json
```

### kb upload — 上传文件到知识库

```
ima_upload.py kb upload report.pdf --kb kb_id
ima_upload.py kb upload data.xlsx --kb kb_id --folder folder_id --json
ima_upload.py kb upload report.pdf --kb kb_id --on-duplicate keep-copy   # 重名保留时间戳副本
ima_upload.py kb upload downloaded_file --kb kb_id --content-type application/pdf
```

支持的文件类型：PDF, Word, PPT, Excel, CSV, Markdown, PNG/JPG/WebP, TXT, Xmind, MP3/M4A/WAV/AAC, HTML, EPUB

### kb add-url — 添加网页/微信文章

```
ima_upload.py kb add-url "https://example.com" --kb kb_id
ima_upload.py kb add-url "https://mp.weixin.qq.com/s/xxx" --kb kb_id
ima_upload.py kb add-url url1 url2 url3 --kb kb_id
```

### kb media — 获取媒体信息 / 原文落盘

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

### kb addable — 获取可添加的知识库列表

```
ima_upload.py kb addable                  # 列出用户有权限添加的知识库
ima_upload.py kb addable --json
```

### kb add-note — 将笔记关联到知识库

```
ima_upload.py kb add-note note_id "标题" --kb kb_id
ima_upload.py kb add-note note_id "标题" --kb kb_id --json
```

### kb find-folder — 按名称查找知识库中的文件夹

```
ima_upload.py kb find-folder "文件夹名" --kb kb_id
ima_upload.py kb find-folder "文件夹名" --kb kb_id --json
```

---

## 典型调用示例

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
