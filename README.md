# ima-upload Skill

腾讯 IMA 云端笔记与知识库上传工具（公开脱敏版）。当前版本 **v3.4.6**。

## 特性

- 笔记：创建 / 智能追加 / 搜索 / 列表 / 读取，插图校验后内嵌 data URL
- 知识库：上传文件、添加网页与微信文章、浏览目录、原文落盘、笔记关联
- 自动读取 `~/.config/ima/` 凭证
- 提供 Python 与 PowerShell 两种调用方式（PowerShell 仅覆盖笔记基础操作）
- 上传安全门与官方 `ima-skills` 对齐：类型/大小/图片签名预检、重名只允许取消或时间戳副本、COS 失败不落库

## 使用说明

- 指令与命令速查：[`SKILL.md`](SKILL.md)
- 全部子命令示例与参数组合：[`references/cli.md`](references/cli.md)
- Python API、HTTP 端点、Header 格式：[`references/api.md`](references/api.md)
- 已修复的历史坑与实现取舍：[`references/pitfalls.md`](references/pitfalls.md)

## 自检

```bash
python scripts/test_contract.py      # 74 项契约测试，不发真实请求
python scripts/check_official_skill.py --brief   # 与官方 ima-skills 的端点和能力差异
```

## 脱敏声明

本项目所有路径与笔记 ID 均已替换为占位符，使用前请根据自己环境修改。
