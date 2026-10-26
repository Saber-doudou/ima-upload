# CHANGELOG

本文件记录 ima-upload 技能的版本变更。版本号遵循三段式（MAJOR.MINOR.PATCH），每段不超过一位数。

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
