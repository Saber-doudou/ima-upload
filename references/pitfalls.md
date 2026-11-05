# ima-upload 实现细节与历史坑

> 按需加载文件。这里的条目多数已由脚本内部修复，保留是为了改脚本时知道「为什么代码写成这样」。
> 只在这些情况读：怀疑踩到已知问题、要修改 `scripts/ima_upload.py`、或核对某个设计取舍的来由。

---

## 历史坑与已修复项

| 坑 | 原因 | 解决 |
|----|------|------|
| PowerShell 中文乱码 | PS5.1 默认 GBK | 脚本已带 UTF-8 BOM；Body 需转字节数组 |
| `clientID or apiKey is empty` | header 名错误 | 用 `ima-openapi-clientid`（全小写）|
| 凭证读不到 | BOM 或空格 | 自动 strip() + BOM 跳过；尝试多路径回退 |
| 内容里标题重复 | `create_note` 自动加了 `# 标题` | v2 已移除自动前缀，content 直接写入 |
| Git Bash 找不到 Python | 环境限制 | 改用 PowerShell 封装脚本 |
| 文件内容乱码 | 文件是 GBK 编码 | 自动尝试 UTF-8 → GBK → Latin-1 |
| COS 上传超时 | 大文件超 120s | 默认 timeout 300s，大文件可自行调整 |
| **文件夹显示成文件图标** | `get_knowledge_list` 不返回 `folder_id`，文件夹靠 `media_type=99` 识别 | 判 `media_type==99` 或 `media_id` 以 `folder` 开头 |
| **`find-folder` 返回错的 ID** | 曾把 `parent_folder_id`（父目录）当文件夹自身 ID | 文件夹自身 ID 就是其 `media_id`；`parent_folder_id` 只表示所属目录 |
| **`list`/`search` 时间显示报错** | API 的 `create_time`/`modify_time` 是字符串，不是数字 | `_ts_to_str` 先 `int()` 转换再格式化 |
| **`search` 一次返回上百条** | 服务端忽略 `start`/`end` 上限 | 本地按 `--limit` 截断（默认 20） |
| **`list_note` 响应没有 `next_cursor`** | 只有 `is_end` | 翻页需自行累加已取条数作为下一轮 `cursor` |
| **图片换链报 session ID is required** | `mcp_cloud_agent/upload_temp_file` 等双端点需 MCP 云代理会话，本地 client_id 不支持 | 换链失败会明确提示；插图批量处理改用 `--transform-images` 内嵌 |
