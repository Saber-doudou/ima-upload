# CHANGELOG

本文件记录 ima-upload 技能的版本变更。版本号遵循三段式（MAJOR.MINOR.PATCH），每段不超过一位数。

## v3.4.4 — 2026-11-07

`ps1` 降级通道实跑修复。**这两条只有真跑才暴露，静态审查看不出来。**

### 修复

- **响应中文 mojibake（实跑发现）**：`Invoke-RestMethod` 在 PS5.1 上对「响应头没写 charset」的 JSON 默认按 ISO-8859-1 解码，中文在**解析阶段**就变成拉丁乱码（实测输出 `è®°å½æ¶é´` 即「记录时间」）。此前只修过请求侧（Body 转字节数组），响应侧一直是坏的，且外层再设 `Console.OutputEncoding` 也救不回来。修复：改用 `Invoke-WebRequest` 取 `RawContentStream`，自己按 UTF-8 解码再 `ConvertFrom-Json`。
- **进度条污染 `-Json` 输出**：PS5.1 的 `Invoke-WebRequest` 会往输出流打「正在读取 Web 响应…」，把机器可读 JSON 弄成非 JSON。修复：启动时 `$ProgressPreference = "SilentlyContinue"`（顺带显著加快大响应）。

### 实跑验证

```
ps1 search "备份" -Type content -Json
→ 输出类型 String（非字节数组）
→ 纯 JSON，ConvertFrom-Json 解析成功，20 条结果
→ 中文正常：「记录时间：2026-05-15 脚本版本：sync_to_cloud.py v6.0」
```

只读接口，未产生任何写入。

### 仍未验证

`ps1` 的**写路径**（`create` / `append`）没有实跑——验证需要往 IMA 真实写入测试数据，留待 Master 指定测试笔记本后再做。

## v3.4.3 — 2026-11-07

content-type 口径统一。契约测试 74 → 76 项。

### 修复

- **content-type 归一化不一致**：视频黑名单判定做了 `split(";")` / `strip` / `lower`（`UNSUPPORTED_VIDEO_CT` 能命中 `Video/MP4; charset=x`），但 `CONTENT_TYPE_MAP` 查询直接拿原始串，于是 `--content-type "Image/PNG"` 或 `image/png; charset=utf-8` 查不到映射 → 静默退回扩展名判定 → 扩展名不认识时报「不支持的文件类型: .bin」，把真实原因（content-type 写法带参数/大写）掩盖掉。
  修复：抽出 `_normalize_content_type()`，两处共用；映射命中后回写归一化值，避免带参数的 MIME 被原样送到服务端。

### 契约测试

74 → **76 项**：新增归一化单元用例（大小写/参数/空白/None/空串五种输入）、端到端用例（`.bin` + `Application/PDF; charset=binary` 不得报「不支持的文件类型」）。编写顺序为先对 v3.4.2 跑红（**74/76**，两条新用例均失败）、修复后跑绿（**76/76**），用 `git stash` 回退代码验证过红态。

### 已评估但未做

- **`_safe_filename` 长度校验**：实测超长写入会被系统拦住，不会静默损坏，按 Master 判断不加截断策略。附带发现：失败时报 `OSError [Errno 22] Invalid argument`（不是「文件名太长」），错误码有误导性，属可选优化，本次未动。

## v3.4.2 — 2026-11-07

与官方行为对齐 + 两处修正。契约测试 72 → 74 项。

### 对齐

- **补 `ima-openapi-ctx: skill_version=<ver>` 请求头**：官方 `ima_api.cjs:72` 每个请求都带，本地一直没带。版本号从 `_meta.json` 读取（与官方读自己 `meta.json` 同做法），读不到降级 `unknown`，**不新增第五个版本号同步点**。requests 与 urllib 两条通道都加。实测带该头调用 `list_knowledge_bases` 正常返回 17 个知识库，服务端不拒。

### 修复

- **`file:///C:/x` 路径被多切一个斜杠**：`_local_image_path` 用 `source[7:]` 切掉 `file://`（7 字符），但标准写法 `file:///C:/x` 的第 8 个字符才是路径起点，结果得到 `/C:/x`，Windows 下必然「文件不存在」。修复：识别 `^/[A-Za-z]:[\\/]` 时去掉前导斜杠。**官方 `localPath()` 用 `slice(7)`，同样有此缺陷，此处不跟随**（对齐一个 bug 没有价值）。

### 文档

- 踩坑记录补两条现行文档缺失的已知限制：**插图不支持相对路径**（`![](images/a.png)` 报「不支持的图片来源」，只认 `file://` / `/` 开头 / `盘符:\`，官方同规则）、**小内容报错不自动降级**（降级门槛是切分后 ≥2 批，单批内容遇 content 类报错直接抛出）。
- 这两条原先只写在未跟踪的历史工单里，v3.4.0 瘦身时未收录，AI 按常规 markdown 习惯写相对路径必踩。

### 契约测试

72 → **74 项**：新增 `file:///C:/` 路径解析（含 Unix 绝对路径不被误改、相对路径返回空串两条断言）、请求头带 `ima-openapi-ctx` 且值等于 `_meta.json` 版本号。

## v3.4.1 — 2026-11-06

外部审查修复。3 个会静默损坏数据的缺陷 + 6 项一致性问题 + `ps1` 降级通道 4 处。全部遵循「先写用例跑红、再改代码跑绿」，契约测试 64 → 72 项。

### 修复（数据正确性，P0）

- **urllib 通道吞掉业务错误**（`_request`）：requests 缺失时走 urllib 分支，直接返回 `json.loads` 结果而不校验 `code`。实测 `{"code":100005,"msg":"无权限"}` 会被当成成功，CLI 打印「笔记创建成功」，`--log` 还会把空 `note_id` 写进映射文件。修复：抽出 `_parse_payload()`，两条通道共用同一套解析；`HTTPError` 的响应体也交给它，4xx/5xx 仍能拿到真实错误码。同时把 `urllib.request` / `urllib.error` 改为无条件导入（原先只在 `except ImportError` 分支导入，实际能跑是靠在 requests 传递导入的副作用上）。
- **降级分类把「响应解析失败」判成可重写，产生重复笔记**（`_is_content_related_error`）：原黑名单判定只排除业务码与几个关键词，而 `_parse_response` 对解析失败构造的正是 `code=-1` + `响应解析失败: ...`。于是 `--transform-images` 且内容可切 ≥2 批时，首次可能已在服务端成功的写入会再发一次 `import_doc`。修复：改白名单，只有明确指向内容体积/长度超限（`content length` / `413` / `内容过长` 等）才允许降级。取向是「宁可少降级」——误判成可降级是不可回滚的脏数据，误判成不可降级只是把错误如实报出。
- **`download_media` 同秒重名覆盖**：原逻辑只在 `dest.exists()` 时加一次秒级时间戳且不复查，同秒连续下载算出同一个名字，`_http_download` 以 `"wb"` 打开，后写覆盖前写。修复：改序号棘轮（`_YYYYMMDDHHmmss`、`_1`、`_2`…，上限 99），与上传侧 keep-copy 口径对齐。

### 修复（一致性与安全，P1）

- **`_cmd_kb_add_url` 兼容 list 响应**：原实现假设 `results` 是 dict，官方返回 list 时 `AttributeError: 'list' object has no attribute 'values'`。
- **`CONTENT_TYPE_MAP` 补 xmind 别名**：`application/vnd.xmind.workbook`、`application/zip` → 14，对齐官方 `preflight-check.cjs:130-131`。副作用：普通 zip 也会被当作 xmind 放行，与官方同口径。
- **图片签名补扩展名一致性校验**：原先只比签名与 `content_type`，`PNG 内容改名 .pdf + 显式 --content-type image/png` 会被放过。现对齐官方 `preflight-check.cjs:222-230`。
- **`session.post` 禁止跟随重定向**：requests 默认跟随 302，会把 `ima-openapi-clientid` / `ima-openapi-apikey` 带到重定向目标。
- **`_apply_transform` 不再谎报降级**：inline 模式原先也输出 `degrade: "inline→batched (on-error)"`，dry-run 报告会被读成「本次已降级」。现在只在真的产生批次时给值，否则为 `null`。

### 修复（`scripts/ima_upload.ps1` 降级通道）

仅静态语法检查 + 无网络路径实测，**未做真实上传验证**（该脚本只在 Python 不可用时启用）。

- **`-Type` 参数缺失**：帮助里写着 `search "关键词" -Type content`，但 param 块没有 `-Type`，实参会被参数绑定拒绝；且判定写的是 `$File -eq "content"`（`$File` 是文件路径参数）。修复：补 `[ValidateSet("title","content")]$Type`，判定改用 `$Type`。
- **`-Json` 输出字节数组**：多处 `Write-Output ([Encoding]::UTF8.GetBytes(...))`，管道下游拿到的是数字序列而非 JSON 文本。修复：统一走 `ConvertTo-Json` 输出字符串，并在启动时设 `[Console]::OutputEncoding = UTF8`。
- **手拼 JSON 未转义**：错误消息里的 `\`n` 换行、路径反斜杠被直接插进双引号 JSON 字面量，产出的是非法 JSON。修复：新增 `Write-JsonError`，用 `ConvertTo-Json` 生成；实测凭证缺失场景的输出已可被 `ConvertFrom-Json` 解析（3 行 msg 完整保留）。
- **UTF-8 兜底永不生效**：`[Encoding]::UTF8` 遇到非法字节会替换成 U+FFFD 而不抛异常，`catch` 分支永远走不到。修复：改用 `New-Object System.Text.UTF8Encoding($false, $true)`（throwOnInvalidBytes），GBK 兜底才可能触发。

### 文档修正

- `references/api.md`：`find_folder` 参数顺序改为 `(kb_id, folder_name)`（原文档与代码相反，照文档调用返回空列表）；端点表补 `get_addable_knowledge_base_list`（代码在用、文档漏记）。
- `references/cli.md`：删除连排的两条 `---`（v3.4.0 声称已修，实际去重逻辑只判紧邻，中间夹空行时漏掉）。
- 更正 v3.4.0 条目里 description 的字符数：481 → **499**（YAML 折叠后实测值；481 是加「同步到 IMA 云端」之前的旧数）。

### 契约测试

64 → **72 项**。新增 8 条覆盖上述 P0/P1：urllib 业务错误、urllib 非 JSON 响应、降级白名单正反例、下载同秒棘轮、add-url list 响应、xmind 别名、inline 不谎报降级、图片扩展名伪造。编写顺序为先对 v3.4.0 代码跑红（8 条全红，64/72）再修复跑绿（72/72）。

### 未修

- `_safe_filename` 未限制文件名长度（超长名在部分文件系统会截断或报错），风险低，未纳入本次。

## v3.4.0 — 2026-11-06

文档结构重构。无功能变更、无代码逻辑改动，`scripts/ima_upload.py` 仅同步两处版本号字面量。

### 变更

- **补 frontmatter（`name` / `display_name` / `description`）**：此前本文件无任何 frontmatter。实测平台在缺失时按目录名注册技能、并从正文前约 99 字截取 description，实际生成的描述末尾停在 `| 模块 | 功能 | `，是一段残缺表格，等于丧失了路由信号。现显式声明 description（YAML 折叠后 499 字符），覆盖触发场景、口语说法、文件类型、业务场景与排除边界。
- **删除「触发条件」章节**：7 条触发意图已全部并入 description，同一信息不再两处维护，对齐官方「Avoid Duplication: Information should exist in either SKILL.md or reference files, not both」。
- **CLI 逐命令示例下沉 `references/cli.md`**（176 行，标题层级已上提一级）：正文仅保留「确定调用方式」场景表、文件上传安全门、返回语义补充与资源清单表。原「CLI 命令参考」下 17 个 `####` 子命令块整体搬移，未改写任何命令、参数或引号。
- **Python API / API 端点 / Header 格式下沉 `references/api.md`**（105 行）。
- **踩坑记录按性质分流**：20 条中保留 7 条影响调用决策的操作约束（`/tmp/` 路径、`upsert` 去重、多行内容用 `--file`、字段名以实测为准、统计用 `list --nb`、单页 20 上限、签名 URL 不可追加参数），其余 13 条「脚本已修复」的实现细节迁 `references/pitfalls.md`（24 行）。
- 新增「资源文件」三列表，按官方「参考文件要说清什么时候读」要求标注各 references 的读取时机。
- 正文 16,131 → 8,746 字符（-45.8%），221 行。按同口径折算约 6,600 → 3,600 tokens，落入官方 SKILL.md 正文 5k token 预算内。

### 未做

- **未改 `scripts/` 下任何逻辑**，仅同步 docstring 与 argparse description 两处版本号字面量。
- **`display_name` 已在 frontmatter 声明，但平台技能列表当前仍显示目录名 `ima-upload`**。同一时刻 `description` 已被正确读取，判断为平台对展示名的缓存或取值路径差异，不影响调用与路由。待客户端重启后复验。
- 「功能概览」表与「确定调用方式」表存在部分重叠，评估后保留：前者是模块到命令的索引，后者是场景到命令的决策表，视角不同。

### 校验

- `scripts/test_contract.py`：**64/64 通过**。
- 命令保真（重构前后集合比对）：57 条命令 / 19 个参数 / 17 个子命令 / 22 个 API 方法 / 17 个端点，**零丢失**。
- 校验脚本与基线落在治理目录，未放进技能目录，避免给技能增添运行依赖。

## v3.3.0 — 2026-10-26

整合官方 ima-skills v1.1.10 的 5 项能力缺口（依据《工单-整合官方5项能力缺口-提示词.md》，纠偏 3 处工单与官方实际实现不符之处后执行）。

### 修复（返工，审查发现，同版本内修订）

- **【安全】`download_media` 路径穿越漏洞（P0-1）**：落盘文件名取自服务端可控的 `media_title`/URL 末段，原先直接 `out_dir / file_name` 拼接，`../` 或绝对路径可写穿目标目录。修复：文件名强制 basename 收敛（兼容 `/` 与 `\` 分隔符）+ 剔除 Windows 非法字符/控制字符/结尾点空格（清洗为空回退 media_id 兜底名）+ 落盘前 `resolve().relative_to(out_dir)` 落点断言，违者 `IMAError`。新增 2 个穿越型契约用例（`../` 与 `C:\` 均被收敛）。
- **keep-copy 改名后未复查重名（P0-2）**：方案书 S3 规格要求改名后走 `check_repeated_names` 再上传，原实现只查原名一次，新名可静默撞名绕过「不支持覆盖」。修复：改名后以新名复查，仍重复即拒绝；keep-copy 用例断言改为「查 2 次且第二次用新名」，新增「新名仍冲突时拒绝」用例。
- **D2 降级缺「报错降级」路径（P0-3）**：原实现仅按体积阈值降级，inline 写入报错直接抛出。修复：inline（`import_doc`/`append_doc`）捕获 `IMAError` 且内容可切分时自动降级分批 `append_doc` 重试，结果带 `degraded: "inline→batched"` 标记；两次均失败时报错注明「inline 与 batched 均失败」及批次号；dry-run 报告新增 `degrade` 可读标记。新增 1 个报错降级用例。
- **视频 MIME 黑名单缺失（P1-4）**：补官方 `UNSUPPORTED_VIDEO_CT` 7 种视频 MIME（`--content-type video/mp4` 等命中即拒，原先会回退扩展名误传）。新增 1 个用例。
- **防御与口径（P2）**：`create_note_batched`/`append_note_batched`/`_write_note_batches` 空批校验转 `IMAError`（原先裸抛 `IndexError`）；`_http_download` requests/urllib 两分支网络异常统一转 `IMAError`；图片签名错误文案改为「与声明类型（扩展名/content-type）不符」；`check_official_skill.py` 对 `mcp_cloud_agent` 端点标注「官方 note-images.cjs 实际使用」防误读。新增 1 个空批防御用例。

### 修缮（残余，复验后收尾，同版本内修订）

- **【数据丢失风险】Windows 保留设备名静默吞数据（P2-6）**：`_safe_filename` 原不识别 `CON/PRN/AUX/NUL/COM1-9/LPT1-9`（含 `CON.md` 形式），Win32 会把写入导向设备，`kb media --download` 报成功但磁盘无文件无数据。修复：保留设备名（主干判定）统一加 `safe_` 前缀改写（不拒绝，下载仍可用），media_id 兜底名走同一清洗函数。新增 2 个用例（`CON.md`/`NUL`）。
- **业务错误触发降级白重试（P2-7，选方案 A）**：inline 写入报错不分类一律降级，敏感词/权限/配额等业务错误注定同样失败，白打一次请求且文案重复。修复：新增 `_is_content_related_error` 错误分类，业务错误码（非 -1）或标题/权限/配额/敏感词类消息原样抛出不降级，仅 content 相关错误走分批重试。新增 1 个用例（业务错误只调 1 次 `import_doc` 且文案不拼接）。
- **keep-copy 同秒碰撞直接拒绝（P2-8）**：时间戳秒级精度，同秒连续 keep-copy 第二次必撞。修复：序号棘轮重试（`_YYYYMMDDHHmmss`、`_1`、`_2`、`_3` 依次复查），最多 3 次序号重试，试尽仍冲突才拒绝（「不支持覆盖」语义不变）。全冲突用例断言升级为 5 次查重序列，新增「序号名复查通过即上传」用例。
- **文档补全（P2-9/P2-10）**：SKILL.md Python API 段补 3 行返回语义（`degraded` 标记、空批异常、`file_name` 清洗语义）；argparse epilog 补 `kb media --download --out` 示例。
- **能力边界标注（防死循环）**：SKILL.md 新增「能力边界与通道切换指引」章节，A 表（本地可实现 7 类）、B 表（本地受限换官方技能/ima 客户端 4 类，含 `image-url` 换链的三选一出口）、C 表（双方都做不了换 ima 桌面端 4 类），并明确止损三原则（同参失败 2 次即换通道、业务错误换技能无用、按报错文案走）。`image-url` 的 session 错误文案同步补「出口三选一 + 请勿重复调用」指引，`image-url` 相关表格行标注勿重试口径。

### 新增
- **笔记插图转存内嵌（缺口 1）**：`--transform-images`（create/upsert/append 通用）将 markdown 中本地路径、http(s) URL、data URL 三种图片源校验后转 base64 data URL 内嵌。校验对齐官方 note-images.cjs：魔数（PNG/JPEG/WebP）+ 严格小于 3MiB。内联体积超 2MiB 时自动降级官方分批模式（text/image 切批，`append_doc` 逐批写入，任一批失败报批次号）。`--dry-run` 只输出批次报告（index/type/bytes）不写入。**纠偏**：工单写的 `openapi/note/v1/import_image` 端点不存在，官方实际是 data URL 内嵌而非换链。
- **单图转存换链 `image-url`（缺口 1 换链模式）**：对应官方 `--url` 模式（`upload_temp_file` → `get_access_url`）。**实测**：双端点需 MCP 云代理会话，本地 client_id 调用报「session ID is required」（code 100001），失败时给出改用 `--transform-images` 的降级指引。
- **原文落盘（缺口 4）**：`kb media <id> --download [--out DIR]` 新增 `download_media()`。**纠偏**：官方无 `cos-download.cjs`；实测 `url_info.url` 是带 `sign` 的预签名链接且查询串已含 `response-content-type`/`media_title`，追加任何参数都会 403，因此签名 URL 原样使用、文件名取 `media_title`，仅未签名 URL 才追加官方 `response-content-disposition=attachment;filename` 约定。本地重名自动加 `_YYYYMMDDHHmmss` 后缀不覆盖。
- **HTML/EPUB 上传（缺口 3）**：`EXT_MAP` 增 `html`→media_type 20、`epub`→21；`SIZE_LIMITS` 增 20:10MB、21:50MB，与官方 preflight-check.cjs 一致。
- **上传安全门对齐（缺口 5）**：明文 4 条（预检失败即停 / title 恒等于 file_name / 重名只允许取消或时间戳副本不支持覆盖 / COS 失败不得调 add_knowledge）。新增 `--on-duplicate cancel|keep-copy`（keep-copy 追加 `_YYYYMMDDHHmmss` 时间戳副本，默认 cancel 行为不变）与 `--content-type`（显式 MIME 优先于扩展名，对齐官方解析优先级）。**纠偏**：官方重名策略是「时间戳副本或取消」二选一，原实现只有拒绝。

### 变更
- 契约测试 32 项扩至 **64 项**（v3.3.0 主体 22 项 + 返工修复 6 项 + 残余修缮 4 项）：新增图片签名（伪造扩展名/坏魔数/合法通过）、HTML/EPUB 超限、COS 失败安全门、keep-copy 时间戳副本（含改名后复查、序号棘轮重试与试尽拒绝）、content-type 优先、download（签名 URL 透传/强制下载参数/笔记类型/重名后缀/路径穿越 2 例/保留设备名 2 例）、插图转存（3MiB 拦截/非法 data URL/dry-run/体积降级/报错降级/换链请求体/session 降级指引/业务错误不降级）、视频 MIME 黑名单、空批防御等，全程 FakeUploader 拦截网络层。
- `check_config.json`：5 项 `pending_capabilities` 全部标记 `integrated`，pending 清空。
- `SKILL.md`：新增文件上传安全门章节、「能力边界与通道切换指引」章节（防死循环，见上）、`--transform-images`/`--dry-run`/`image-url`/`--download`/`--on-duplicate` 用法与 2 条踩坑记录（预签名 URL 追加参数 403、换链 session 限制）；修复 kb find-folder 代码块未闭合。

### 实测冒烟
- `--transform-images --dry-run` 干跑：JSON 输出可解析，批次结构正确。
- `--download` 真实落盘：原文件名完整保留（13.9KB md 一次成功）。
- `image-url` 换链端点：确认需云端会话，按预案降级。

## v3.2.0 — 2026-10-26

### 修复
- **知识库列表全部为 null**：实测 `search_knowledge_base` 返回 `kb_id` / `kb_name`，代码却按官方 api.md 写的 `id` / `name` 取值。新增 `_normalize_kb` 同时兼容两种写法。
- **`find-folder` 返回父目录 ID**：曾把 `parent_folder_id` 当作文件夹自身 ID，导致上传落到根目录。改为按 `media_type=99` 与 `media_id` 前缀识别，返回条目自身 `media_id`。
- **`kb ls` 文件夹识别失效**：`get_knowledge_list` 不返回 `folder_id`，原判断恒为假。改为按 `media_type=99` 识别，并补媒体类型标签。
- **`list --nb` 崩溃**：API 的 `create_time` / `modify_time` 是字符串，`str / int` 抛异常。`_ts_to_str` 增加类型转换与边界容错。
- **无效 ID 静默失败**：`kb info`、`kb media`、`read` 传错 ID 时无输出或给出误导提示。改为可读告警并以退出码 2 结束。
- **`search` 一次返回全量**：服务端忽略 `start` / `end` 上限。新增 `--limit`（默认 20）并在输出中报告总数。
- **`list --nb --limit` 超过 20 返回空**：`list_note` 单页上限 20，超出时静默返回空列表且 `code=0`。`list_notes` 改为按偏移量自动翻页（`cursor` 是偏移量，响应无 `next_cursor`）。

### 新增
- `scripts/test_contract.py`：32 项请求契约测试，mock 网络层，不发起真实请求、不写入任何 IMA 数据。包含 upload_file_to_kb 预检阶段（文件类型、大小）拦截验证。
- `.gitignore`：排除 `__pycache__` 与本地版本基线文件。

### 变更
- `scripts/check_official_skill.py` 重构为 v2：官方目录动态定位、调用 `check_skill_update` 查询线上最新版本、诊断官方包完整性、端点自动 diff、新增 `--strict` 与 `--official-dir`。
- `scripts/check_config.json` 升级为 schema v2，成为检测脚本唯一配置源，并记录 6 条接口字段实测差异。
- `SKILL.md`：`kb addnote` / `kb findfolder` 更正为 `add-note` / `find-folder`；补齐 `kb info`、`kb ls`、`kb media` 条目；新增 5 条踩坑记录与契约测试说明。

### 说明
v3.1 规划的三项能力（`kb addable`、`kb add-note`、`kb find-folder`）此前已进代码但未单独发版，本次合入 v3.2.0。

## v3.0.0 — 2026-06-02

- 整合官方 ima-skill 知识库模块：上传文件、添加网页、媒体信息、内容搜索、内容浏览。
- 新增笔记浏览与读取：`list`、`list --nb`、`read`。
- 新增官方技能更新检测脚本 `check_official_skill.py`。

## v2.0.1 — 2026-05-22

- 通用化改造，脱敏脚本内硬编码路径。

## v2.0.0（日期未记录）

- 新增知识库上传能力（COS 直传）。
- 移除 `create_note` 自动添加的 `# 标题` 前缀，正文按原样写入。
- 新增 `upsert`（同名追加、无则新建）与 `create --dedup` 防重复创建。
- 新增 `--json` 与 `--log` 便于自动化调用。

## v1.0.0

- 首个版本：IMA 笔记创建、追加、搜索。
