#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ima_upload 请求契约测试

目的：在没有真实写入的前提下，验证每个方法发出的请求路径与 body 字段
符合官方 references/api.md 的定义，并验证响应解析能处理真实字段名。

做法：继承 IMAUploader 但拦截 _request，记录调用并发回构造好的响应。
本测试不发起任何网络请求，不写任何 IMA 数据。

运行：
    python test_contract.py
    python test_contract.py -v
"""

import sys
import tempfile
import urllib.parse
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ima_upload as m  # noqa: E402

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

PASSED = []
FAILED = []


class FakeUploader(m.IMAUploader):
    """拦截网络层，记录调用并返回预设响应"""

    def __init__(self):
        # 绕过真实凭证加载
        self.client_id = "fake-client-id"
        self.api_key = "fake-api-key"
        self.session = None
        self.calls = []
        self.responses = {}
        self.cos_calls = []

    def _request(self, api_path, body, timeout=30):
        self.calls.append({"path": api_path, "body": body})
        return self.responses.get(api_path, {"code": 0, "data": {}})

    def _cos_upload(self, **kwargs):
        self.cos_calls.append(kwargs)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def case(name):
    def deco(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"  ✅ {name}")
        except AssertionError as e:
            FAILED.append((name, str(e)))
            print(f"  ❌ {name}: {e}")
        except Exception as e:
            FAILED.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
        return fn
    return deco


def last_call(u):
    expect(u.calls, "没有任何请求被发出")
    return u.calls[-1]


# ---------------- 笔记模块 ----------------

@case("create_note → import_doc 字段完整")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/import_doc"] = {"code": 0, "data": {"note_id": "n1"}}
    r = u.create_note("标题", "正文")
    c = last_call(u)
    expect(c["path"] == "openapi/note/v1/import_doc", "端点错误")
    expect(c["body"]["title"] == "标题", "title 错误")
    expect(c["body"]["content"] == "正文", "content 错误")
    expect(c["body"]["content_format"] == 1, "content_format 应为 1(markdown)")
    expect(r["note_id"] == "n1", "note_id 解析错误")


@case("append_note → append_doc 字段完整")
def _():
    u = FakeUploader()
    u.append_note("n1", "追加")
    c = last_call(u)
    expect(c["path"] == "openapi/note/v1/append_doc", "端点错误")
    expect(c["body"] == {"note_id": "n1", "content": "追加", "content_format": 1}, "body 不符")


@case("create_note 拒绝非法 UTF-8（防乱码）")
def _():
    u = FakeUploader()
    bad = "正常" + "\ud800"  # 孤立代理项，无法编码为 UTF-8
    try:
        u.create_note("t", bad)
    except m.IMAError as e:
        expect("UTF-8" in e.msg, "错误信息未说明编码问题")
        return
    raise AssertionError("未拦截非法 UTF-8")


@case("search_notes → search_note 参数符合官方定义")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {
        "code": 0,
        "data": {"search_note_infos": [{
            "note_book_info": {"note_id": "n9", "title": "T", "summary": "S",
                               "modify_time": 1700000000000,
                               "note_ext_info": {"folder_name": "F"}},
            "highlightInfo": {"doc_title": "<em>x</em>"},
        }]},
    }
    r = u.search_notes("kw", 0)
    c = last_call(u)
    expect(c["path"] == "openapi/note/v1/search_note", "端点错误")
    expect(c["body"]["search_type"] == 0, "search_type 错误")
    expect(c["body"]["query_info"] == {"title": "kw"}, "query_info 标题搜索构造错误")
    expect(c["body"]["start"] == 0 and c["body"]["end"] <= 20, "分页区间应为 0 至 20")
    expect(r[0]["note_id"] == "n9", "嵌套 note_book_info 解析错误")
    expect(r[0]["folder_name"] == "F", "note_ext_info.folder_name 解析错误")


@case("list_notebooks → list_notebook 解析 note_folder_infos")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/list_notebook"] = {"code": 0, "data": {
        "note_folder_infos": [{"folder_id": "f1", "name": "笔记本",
                               "note_number": "3", "folder_type": 0}],
        "is_end": False, "next_cursor": "3",
    }}
    r = u.list_notebooks()
    c = last_call(u)
    expect(c["path"] == "openapi/note/v1/list_notebook", "端点错误")
    expect(r[0]["folder_id"] == "f1", "folder_id 解析错误")
    expect(r[0]["note_count"] == "3", "note_number 解析错误")


@case("list_notes → list_note 分页参数合法")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/list_note"] = {"code": 0, "data": {"note_book_list": [
        {"note_id": "n1", "title": "t", "note_ext_info": {"folder_name": "f"}}
    ], "is_end": True}}
    r = u.list_notes("nb1", 20)
    c = last_call(u)
    expect(c["path"] == "openapi/note/v1/list_note", "端点错误")
    expect(c["body"]["cursor"] == "0", "首次 cursor 应为偏移量 0")
    expect(0 < c["body"]["limit"] <= 20, "limit 必须 1 至 20")
    expect(r[0]["note_id"] == "n1", "note_id 解析错误")


@case("get_note_content → get_doc_content 用纯文本格式")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/get_doc_content"] = {"code": 0, "data": {"content": "正文"}}
    r = u.get_note_content("n1")
    c = last_call(u)
    expect(c["body"]["target_content_format"] == 0, "应为纯文本(0)，markdown(1) 不被支持")
    expect(r == "正文", "content 解析错误")


@case("upsert_note 无同名时新建")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {"code": 0, "data": {"search_note_infos": []}}
    u.responses["openapi/note/v1/import_doc"] = {"code": 0, "data": {"note_id": "new1"}}
    r = u.upsert_note("新标题", "内容")
    expect(r["action"] == "created", f"应为 created，实际 {r['action']}")
    expect(r["note_id"] == "new1", "note_id 错误")
    expect(u.calls[-1]["path"] == "openapi/note/v1/import_doc", "未走新建路径")


@case("upsert_note 有同名时追加而非重复创建")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {"code": 0, "data": {"search_note_infos": [
        {"note_book_info": {"note_id": "old1", "title": "同名标题"}}
    ]}}
    r = u.upsert_note("同名标题", "追加内容")
    expect(r["action"] == "appended", f"应为 appended，实际 {r['action']}")
    expect(r["note_id"] == "old1", "应复用已有 note_id")
    expect(u.calls[-1]["path"] == "openapi/note/v1/append_doc", "未走追加路径")
    expect(not any(c["path"].endswith("import_doc") for c in u.calls), "不应重复创建")


@case("upsert_note 只认精确同名，不做模糊匹配")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {"code": 0, "data": {"search_note_infos": [
        {"note_book_info": {"note_id": "x1", "title": "标题A（旧）"}}
    ]}}
    u.responses["openapi/note/v1/import_doc"] = {"code": 0, "data": {"note_id": "new2"}}
    r = u.upsert_note("标题A", "内容")
    expect(r["action"] == "created", "模糊匹配不应触发追加，否则会把内容写错笔记")


@case("create --dedup 命中同名时退出且不创建")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {"code": 0, "data": {"search_note_infos": [
        {"note_book_info": {"note_id": "d1", "title": "重复标题"}}
    ]}}
    args = type("A", (), {"content": "x", "file": None, "title": "重复标题",
                          "dedup": True, "json": True, "log_file": None})()
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    code = 0
    try:
        with redirect_stdout(buf):
            m._cmd_create(u, args)
    except SystemExit as e:
        code = e.code
    expect(code == 2, f"dedup 命中应以 2 退出，实际 {code}")
    expect("DUPLICATE" in buf.getvalue(), "未输出 DUPLICATE 标记")
    expect(not any(c["path"].endswith("import_doc") for c in u.calls), "命中去重后不应创建")


@case("search_notes 返回全量时由 CLI 按 --limit 截断")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {"code": 0, "data": {"search_note_infos": [
        {"note_book_info": {"note_id": f"n{i}", "title": f"t{i}"}} for i in range(50)
    ]}}
    args = type("A", (), {"keyword": "kw", "type": "title", "limit": 5, "json": False})()
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        m._cmd_search(u, args)
    out = buf.getvalue()
    expect("找到 50 条笔记" in out, "未报告总数")
    expect("显示前 5 条" in out, "未按 limit 截断")
    expect(out.count("[n") == 5, f"应只打印 5 条，实际 {out.count('[n')}")


@case("list_notes 超过单页上限 20 时自动翻页")
def _():
    u = FakeUploader()
    # 模拟真实行为：cursor 是偏移量，limit > 20 会返回空
    total = 26
    def fake(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        off = int(body.get("cursor") or 0)
        lim = int(body["limit"])
        if lim > 20:
            return {"code": 0, "data": {"note_book_list": [], "is_end": True}}
        end = min(off + lim, total)
        rows = [{"note_id": f"n{i}", "title": f"t{i}"} for i in range(off, end)]
        return {"code": 0, "data": {"note_book_list": rows, "is_end": end >= total}}
    u._request = fake

    r = u.list_notes("nb1", 26)
    expect(len(r) == 26, f"应取到 26 篇，实际 {len(r)}")
    lims = [c["body"]["limit"] for c in u.calls]
    expect(all(l <= 20 for l in lims), f"单页 limit 不得超过 20，实际 {lims}")
    expect(len(u.calls) == 2, f"26 篇应分 2 页，实际 {len(u.calls)} 页")


@case("list_notes 默认 limit 不越界")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/list_note"] = {"code": 0, "data": {
        "note_book_list": [{"note_id": "n1", "title": "t"}], "is_end": True}}
    u.list_notes("nb1")
    expect(u.calls[0]["body"]["limit"] <= 20, "默认 limit 必须 1 至 20")


# ---------------- 知识库：读取与字段归一 ----------------

@case("list_knowledge_bases 兼容 kb_id/kb_name 实测字段")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/search_knowledge_base"] = {"code": 0, "data": {
        "info_list": [{"kb_id": "kb1", "kb_name": "知识库A", "cover_url": "",
                       "content_count": "170", "role_type": "创建者"}],
    }}
    r = u.list_knowledge_bases()
    expect(r[0]["id"] == "kb1", f"kb_id 未归一到 id，实际 {r[0]}")
    expect(r[0]["name"] == "知识库A", "kb_name 未归一到 name")
    expect(r[0]["content_count"] == "170", "content_count 丢失")


@case("list_knowledge_bases 兼容官方文档的 id/name 写法")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/search_knowledge_base"] = {"code": 0, "data": {
        "info_list": [{"id": "kb2", "name": "知识库B"}],
    }}
    r = u.list_knowledge_bases()
    expect(r[0]["id"] == "kb2" and r[0]["name"] == "知识库B", "id/name 写法未兼容")


@case("get_knowledge_base → infos map 解析")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_knowledge_base"] = {"code": 0, "data": {"infos": {
        "kb1": {"id": "kb1", "name": "A", "description": "d"}
    }}}
    r = u.get_knowledge_base_info("kb1")
    c = last_call(u)
    expect(c["body"]["ids"] == ["kb1"], "ids 应为数组")
    expect(r["kb1"]["name"] == "A", "infos 解析错误")


@case("get_knowledge_list 解析 knowledge_list / current_path")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_knowledge_list"] = {"code": 0, "data": {
        "knowledge_list": [{"media_id": "markdown_1", "title": "a.md", "media_type": 7}],
        "is_end": True, "next_cursor": "",
        "current_path": [{"folder_id": "kb1", "name": "根"}],
    }}
    r = u.get_knowledge_list("kb1")
    c = last_call(u)
    expect(c["body"]["knowledge_base_id"] == "kb1", "knowledge_base_id 错误")
    expect(c["body"]["cursor"] == "", "首次 cursor 应为空串")
    expect(len(r["items"]) == 1 and r["current_path"][0]["name"] == "根", "解析错误")


@case("get_knowledge_list_paged 自动翻页")
def _():
    u = FakeUploader()
    u.pages = [
        {"code": 0, "data": {"knowledge_list": [{"media_id": "a"}], "is_end": False,
                             "next_cursor": "c1"}},
        {"code": 0, "data": {"knowledge_list": [{"media_id": "b"}], "is_end": True,
                             "next_cursor": ""}},
    ]
    orig = u._request

    def paged(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        return u.pages[len([c for c in u.calls if c["path"] == api_path]) - 1]

    u._request = paged
    items = u.get_knowledge_list_paged("kb1")
    expect(len(items) == 2, f"翻页应累计 2 条，实际 {len(items)}")
    expect(u.calls[1]["body"]["cursor"] == "c1", "第二页未带 next_cursor")


@case("find_folder 用 media_type=99 识别，返回真实 folder_id")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/search_knowledge"] = {"code": 0, "data": {"info_list": [
        {"media_id": "folder_7514339246371712", "title": "05-项目档案",
         "parent_folder_id": "ima_kb_root", "media_type": 99},
        {"media_id": "markdown_9", "title": "05-项目档案.md",
         "parent_folder_id": "folder_7514339246371712", "media_type": 7},
    ]}}
    r = u.find_folder("kb1", "05-项目档案")
    expect(len(r) == 1, f"应只命中文件夹，实际 {len(r)} 条")
    expect(r[0]["folder_id"] == "folder_7514339246371712", "folder_id 必须是条目自身 media_id")
    expect(r[0]["folder_id"] != "ima_kb_root", "不能把 parent_folder_id 当 folder_id")


@case("search_knowledge 保留 parent_folder_id 语义，不冒充 folder_id")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/search_knowledge"] = {"code": 0, "data": {"info_list": [
        {"media_id": "m1", "title": "t", "parent_folder_id": "p1",
         "media_type": 7, "highlight_content": "hl"},
    ]}}
    r = u.search_knowledge("kw", "kb1")
    expect(r[0]["parent_folder_id"] == "p1", "parent_folder_id 丢失")
    expect("folder_id" not in r[0], "不应再输出误导性的 folder_id 字段")
    expect(r[0]["media_type"] == 7 and r[0]["highlight"] == "hl", "media_type/highlight 丢失")


@case("get_media_info 透出 url_info 与 notebook_ext_info")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": "https://x/y.md", "headers": {"A": "b"}},
    }}
    r = u.get_media_info("m1")
    expect(r["url_info"]["url"] == "https://x/y.md", "url_info 未透出")
    expect(r["url_info"]["headers"] == {"A": "b"}, "headers 未透出")


# ---------------- 知识库：写操作请求体 ----------------

@case("check_repeated_names 只在文件类型使用，参数结构正确")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/check_repeated_names"] = {"code": 0, "data": {
        "results": [{"name": "a.pdf", "is_repeated": True}]}}
    r = u.check_repeated_names("kb1", [("a.pdf", 1)])
    c = last_call(u)
    expect(c["body"]["params"] == [{"name": "a.pdf", "media_type": 1}], "params 结构错误")
    expect(c["body"]["knowledge_base_id"] == "kb1", "knowledge_base_id 缺失")
    expect(r[0]["is_repeated"] is True, "is_repeated 解析错误")


@case("import_urls 根目录必须显式传 knowledge_base_id")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/import_urls"] = {"code": 0, "data": {"results": {}}}
    u.import_urls("kb1", ["https://a"], None)
    c = last_call(u)
    expect(c["body"]["folder_id"] == "kb1", "根目录 folder_id 应等于 knowledge_base_id")
    expect(c["body"]["urls"] == ["https://a"], "urls 错误")


@case("add_note_to_kb 用 media_type=11 + note_info.content_id")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/add_knowledge"] = {"code": 0, "data": {"media_id": "m1"}}
    u.add_note_to_kb("n1", "标题", "kb1")
    c = last_call(u)
    b = c["body"]
    expect(b["media_type"] == 11, "media_type 应为 11(笔记)")
    expect(b["note_info"] == {"content_id": "n1"}, "note_info 结构错误")
    expect(b["knowledge_base_id"] == "kb1", "knowledge_base_id 缺失")


@case("upload_file_to_kb 完整链路请求体（重名→create_media→COS→add_knowledge）")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/check_repeated_names"] = {"code": 0, "data": {"results": []}}
    u.responses["openapi/wiki/v1/create_media"] = {"code": 0, "data": {
        "media_id": "m1",
        "cos_credential": {"token": "t", "secret_id": "s", "secret_key": "k",
                           "bucket_name": "b", "region": "r", "cos_key": "ck",
                           "start_time": 1, "expired_time": 2},
    }}
    u.responses["openapi/wiki/v1/add_knowledge"] = {"code": 0, "data": {"media_id": "m1"}}

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"# hi\n")
        path = f.name

    r = u.upload_file_to_kb(path, "kb1")
    paths = [c["path"] for c in u.calls]
    expect(paths[:3] == ["openapi/wiki/v1/check_repeated_names",
                         "openapi/wiki/v1/create_media",
                         "openapi/wiki/v1/add_knowledge"], f"调用顺序错误: {paths}")
    expect(len(u.cos_calls) == 1, "COS 上传未执行")

    cm = u.calls[1]["body"]
    for k in ("file_name", "file_size", "content_type", "knowledge_base_id", "file_ext"):
        expect(k in cm, f"create_media 缺字段 {k}")
    expect(cm["file_ext"] == "md", "file_ext 不应带点号")

    ak = u.calls[2]["body"]
    expect(ak["media_type"] == 7, "md 的 media_type 应为 7")
    expect(ak["title"] == Path(path).name, "title 必须等于原文件名")
    expect(set(ak["file_info"]) >= {"cos_key", "file_size", "file_name"}, "file_info 字段缺失")
    expect(r["media_id"] == "m1", "返回值错误")
    Path(path).unlink()


@case("upload_file_to_kb 超限文件在预检阶段拒绝（不发起任何请求）")
def _():
    u = FakeUploader()
    # md 对应 media_type=7，限制 10MB
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"x" * (11 * 1024 * 1024))  # 11MB 超过 10MB 限制
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("超过限制" in e.msg, f"错误信息未说明超限: {e.msg}")
        expect(len(u.calls) == 0, f"预检失败不应发起任何 API 请求，实际 {len(u.calls)} 次")
        expect(len(u.cos_calls) == 0, "预检失败不应触发 COS 上传")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("超限文件未拦截")


@case("upload_file_to_kb 不支持类型在预检阶段拒绝（不发起任何请求）")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
        f.write(b"data")
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("不支持的文件类型" in e.msg, f"错误信息未说明类型不支持: {e.msg}")
        expect(len(u.calls) == 0, f"预检失败不应发起任何 API 请求，实际 {len(u.calls)} 次")
        expect(len(u.cos_calls) == 0, "预检失败不应触发 COS 上传")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("不支持类型未拦截")


@case("upload_file_to_kb 遇重名即拒绝（不支持覆盖）")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/check_repeated_names"] = {"code": 0, "data": {
        "results": [{"name": "a.md", "is_repeated": True}]}}
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("已存在" in e.msg, "错误信息未说明重名")
        expect(not any(c["path"].endswith("create_media") for c in u.calls),
               "重名后不应继续创建媒体")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("重名未拦截")


@case("upload_file_to_kb 拒绝视频类型")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("视频" in e.msg, "错误信息未说明视频不支持")
        expect(len(u.calls) == 0, f"视频类型应在预检阶段拦截，实际 {len(u.calls)} 次请求")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("视频类型未拦截")


# ---------------- 图片签名校验 + 上传安全门 ----------------

@case("upload_file_to_kb 伪造扩展名的图片被拦截（签名与扩展名不符）")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)  # PNG 内容改名 .jpg
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("文件签名与声明类型" in e.msg and "不符" in e.msg, f"错误信息未说明签名不符: {e.msg}")
        expect(len(u.calls) == 0, "签名失败不应发起任何请求")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("伪造扩展名的图片未拦截")


@case("upload_file_to_kb 无效签名的图片被拦截（非 PNG/JPEG/WebP）")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"NOTANIMAGE" + b"\x00" * 20)
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("签名无效" in e.msg or "不受支持" in e.msg, f"错误信息未说明签名无效: {e.msg}")
        expect(len(u.calls) == 0, "签名失败不应发起任何请求")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("无效签名的图片未拦截")


@case("upload_file_to_kb 合法 PNG 通过签名校验走完上传链路")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/check_repeated_names"] = {"code": 0, "data": {"results": []}}
    u.responses["openapi/wiki/v1/create_media"] = {"code": 0, "data": {
        "media_id": "m9",
        "cos_credential": {"token": "t", "secret_id": "s", "secret_key": "k",
                           "bucket_name": "b", "region": "r", "cos_key": "ck",
                           "start_time": 1, "expired_time": 2},
    }}
    u.responses["openapi/wiki/v1/add_knowledge"] = {"code": 0, "data": {"media_id": "m9"}}
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        path = f.name
    r = u.upload_file_to_kb(path, "kb1")
    expect(r["media_id"] == "m9", "返回值错误")
    expect(u.calls[-1]["body"]["media_type"] == 9, "png 应走 media_type=9")
    expect(u.calls[-1]["body"]["title"] == Path(path).name, "title 必须等于原文件名")
    Path(path).unlink()


@case("upload_file_to_kb 显式 content-type 优先于扩展名")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/check_repeated_names"] = {"code": 0, "data": {"results": []}}
    u.responses["openapi/wiki/v1/create_media"] = {"code": 0, "data": {
        "media_id": "m10",
        "cos_credential": {"token": "t", "secret_id": "s", "secret_key": "k",
                           "bucket_name": "b", "region": "r", "cos_key": "ck",
                           "start_time": 1, "expired_time": 2},
    }}
    u.responses["openapi/wiki/v1/add_knowledge"] = {"code": 0, "data": {"media_id": "m10"}}
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"# content\n")
        path = f.name
    u.upload_file_to_kb(path, "kb1", content_type="text/markdown")
    ak = u.calls[-1]["body"]
    expect(ak["media_type"] == 7, f"content-type 应覆盖扩展名，实际 media_type={ak['media_type']}")
    expect(ak["title"] == Path(path).name, "title 必须等于原文件名")
    Path(path).unlink()


@case("COS 上传失败后不得调用 add_knowledge（安全门）")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/check_repeated_names"] = {"code": 0, "data": {"results": []}}
    u.responses["openapi/wiki/v1/create_media"] = {"code": 0, "data": {
        "media_id": "m11",
        "cos_credential": {"token": "t", "secret_id": "s", "secret_key": "k",
                           "bucket_name": "b", "region": "r", "cos_key": "ck",
                           "start_time": 1, "expired_time": 2},
    }}

    def cos_fail(**kwargs):
        u.cos_calls.append(kwargs)
        raise m.IMAError(-1, "COS 上传失败 (HTTP 500): boom")
    u._cos_upload = cos_fail

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"x")
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("COS" in e.msg, f"错误信息应说明 COS 失败: {e.msg}")
        expect(not any(c["path"].endswith("add_knowledge") for c in u.calls),
               "COS 失败后绝不能调用 add_knowledge")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("COS 失败未中止流程")


@case("upload_file_to_kb on-duplicate=keep-copy 生成时间戳副本且改名后复查重名")
def _():
    u = FakeUploader()
    orig_names = []

    def smart(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        if api_path.endswith("check_repeated_names"):
            name = body["params"][0]["name"]
            orig_names.append(name)
            # 仅原名重复，新时间戳名不重复
            return {"code": 0, "data": {"results": [{"name": name, "is_repeated": len(orig_names) == 1}]}}
        if api_path.endswith("create_media"):
            return {"code": 0, "data": {
                "media_id": "m12",
                "cos_credential": {"token": "t", "secret_id": "s", "secret_key": "k",
                                   "bucket_name": "b", "region": "r", "cos_key": "ck",
                                   "start_time": 1, "expired_time": 2},
            }}
        return {"code": 0, "data": {"media_id": "m12"}}
    u._request = smart

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"x")
        path = f.name
    import re
    orig_name = Path(path).name
    r = u.upload_file_to_kb(path, "kb1", on_duplicate="keep-copy")
    expect(r["action"] == "uploaded", "keep-copy 应继续上传")

    checks = [c for c in u.calls if c["path"].endswith("check_repeated_names")]
    expect(len(checks) == 2, f"改名后必须复查重名（应查 2 次），实际 {len(checks)} 次")
    expect(checks[0]["body"]["params"][0]["name"] == orig_name, "第一次应用原名查")
    new_name = checks[1]["body"]["params"][0]["name"]
    expect(new_name != orig_name, "第二次应用新时间戳名查")
    expect(re.search(r"_\d{14}\.md$", new_name), f"新名应带 _YYYYMMDDHHmmss 时间戳: {new_name}")

    cm = next(c for c in u.calls if c["path"].endswith("create_media"))
    ak = next(c for c in u.calls if c["path"].endswith("add_knowledge"))
    expect(cm["body"]["file_name"] == new_name, "create_media 应使用复查过的新名")
    expect(ak["body"]["title"] == new_name, f"title 必须等于最终文件名: {ak['body']['title']} vs {new_name}")
    Path(path).unlink()


@case("upload_file_to_kb keep-copy 新名仍冲突时序号棘轮试尽后拒绝（不支持覆盖）")
def _():
    u = FakeUploader()
    checked = []

    def always_dup(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        if api_path.endswith("check_repeated_names"):
            name = body["params"][0]["name"]
            checked.append(name)
            return {"code": 0, "data": {"results": [{"name": name, "is_repeated": True}]}}
        return {"code": 0, "data": {}}
    u._request = always_dup

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"x")
        path = f.name
    import re
    try:
        u.upload_file_to_kb(path, "kb1", on_duplicate="keep-copy")
    except m.IMAError as e:
        expect("重复" in e.msg and "不支持覆盖" in e.msg, f"错误信息应说明试尽仍重复: {e.msg}")
        expect(len(checked) == 5, f"应为原名 + ts/ts_1/ts_2/ts_3 共 5 次查重，实际 {len(checked)}: {checked}")
        expect(re.search(r"_\d{14}\.md$", checked[1]), f"第 2 次应为无序号时间戳名: {checked[1]}")
        expect(checked[2].endswith("_1.md") and checked[3].endswith("_2.md") and checked[4].endswith("_3.md"),
               f"序号棘轮顺序错误: {checked[1:]}")
        expect(not any(c["path"].endswith("create_media") for c in u.calls),
               "序号试尽后不得继续创建媒体")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("序号试尽仍冲突未拦截")


# ---------------- 原文落盘（--download） ----------------

@case("download_media 未签名 URL 拼接强制下载参数并透传 headers")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": "https://cos.example.com/path/report.md?x=1",
                     "headers": {"Authorization": "Bearer x"}},
    }}
    got = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        got["url"] = url
        got["headers"] = headers
        got["dest"] = dest_path
        Path(dest_path).write_bytes(b"data")
    u._http_download = fake_dl

    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        r = u.download_media("m1", output_dir=td)
        expect(r["file_name"] == "report.md", f"应从 URL 推断文件名: {r}")
        expect("response-content-disposition=" in got["url"], "未拼接 response-content-disposition")
        expect("response-content-type=application/octet-stream" in got["url"], "未拼接 response-content-type")
        expect(got["url"].startswith("https://cos.example.com/path/report.md?x=1&"), f"应保留原查询串: {got['url']}")
        expect(got["headers"] == {"Authorization": "Bearer x"}, "headers 未透传")
        expect(Path(r["path"]).exists(), "落盘文件不存在")


@case("download_media 签名 URL 原样使用不追加参数（追加会 403）")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": "https://skb.ima.myqcloud.com/a/b?media_id=m9&media_title=%E6%8A%A5%E5%91%8A.md&response-content-type=text%2Fmarkdown&sign=abc&t=1",
                     "headers": {"X-IMA-Sign": "s"}},
    }}
    got = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        got["url"] = url
        Path(dest_path).write_bytes(b"data")
    u._http_download = fake_dl

    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        r = u.download_media("m9", output_dir=td)
        expect(got["url"] == u.responses["openapi/wiki/v1/get_media_info"]["data"]["url_info"]["url"],
               "签名 URL 必须原样使用，不得追加/修改查询串")
        expect("response-content-disposition=" not in got["url"], "签名 URL 不得追加 disposition")
        expect(r["file_name"] == "报告.md", f"文件名应取 media_title: {r['file_name']}")


@case("download_media 无 url_info 时提示用 ima 客户端")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {"media_type": 7}}
    try:
        u.download_media("m2")
    except m.IMAError as e:
        expect("ima客户端" in e.msg, f"错误信息应提示客户端兜底: {e.msg}")
        return
    raise AssertionError("无链接媒体未拦截")


@case("download_media 笔记类型提示走 read 命令")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 11, "notebook_ext_info": {"notebook_id": "n1"}}}
    try:
        u.download_media("m3")
    except m.IMAError as e:
        expect("read" in e.msg, f"笔记类型应提示 read 命令: {e.msg}")
        return
    raise AssertionError("笔记类型未拦截")


@case("download_media 本地重名时加时间戳后缀不覆盖")
def _():
    u = FakeUploader()
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7, "url_info": {"url": "https://cos.example.com/a/doc.md", "headers": {}}}}
    saved = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        saved["dest"] = dest_path
        Path(dest_path).write_bytes(b"x")
    u._http_download = fake_dl

    import re, tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        Path(td, "doc.md").write_bytes(b"old")
        r = u.download_media("m4", output_dir=td)
        expect(r["file_name"] == "doc.md", "返回的逻辑文件名应保持原名")
        expect(Path(saved["dest"]).name != "doc.md", "重名落盘必须改名，不许覆盖")
        expect(re.search(r"_\d{14}\.md$", Path(saved["dest"]).name), "重名后缀应为 _YYYYMMDDHHmmss")
        expect(Path(td, "doc.md").read_bytes() == b"old", "原文件被覆盖了")


# ---------------- 笔记插图转存（--transform-images / image-url） ----------------

def _tiny_png_bytes():
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _tiny_png_file():
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    f.write(_tiny_png_bytes())
    f.close()
    return f.name


@case("transform_note_images 本地图片内嵌为 data URL 并统计")
def _():
    path = _tiny_png_file()
    md = f"前文\n\n![图]({path})\n\n后文"
    out, stats = m.transform_note_images(md)
    expect("data:image/png;base64," in out, "未内嵌 data URL")
    expect(path not in out, "原路径未被替换")
    expect(out.startswith("前文") and out.endswith("后文"), "文本上下文被破坏")
    expect(len(stats) == 1 and stats[0]["mime"] == "image/png", f"统计错误: {stats}")
    expect(stats[0]["bytes"] == len(_tiny_png_bytes()), "字节统计错误")
    Path(path).unlink()


@case("transform_note_images 超过 3MiB 的图片被拦截")
def _():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * (3 * 1024 * 1024))
        path = f.name
    try:
        m.transform_note_images(f"![x]({path})")
    except m.IMAError as e:
        expect("3MiB" in e.msg, f"错误信息应说明大小限制: {e.msg}")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("超 3MiB 图片未拦截")


@case("transform_note_images 非法 data URL 与坏魔数被拦截")
def _():
    for bad in ("data:image/png;base64,!!!!", "data:text/html;base64,PGh0bWw+"):
        try:
            m.transform_note_images(f"![x]({bad})")
        except m.IMAError:
            continue
        raise AssertionError(f"非法 data URL 未拦截: {bad[:30]}")
    # 坏魔数（声明 png 实际不是）
    import base64 as _b64
    fake = "data:image/png;base64," + _b64.b64encode(b"NOTANIMAGE" * 4).decode()
    try:
        m.transform_note_images(f"![x]({fake})")
    except m.IMAError as e:
        expect("签名" in e.msg, f"应报签名问题: {e.msg}")
        return
    raise AssertionError("坏魔数图片未拦截")


@case("create --transform-images --dry-run 只输出批次报告不发请求")
def _():
    u = FakeUploader()
    path = _tiny_png_file()
    args = type("A", (), {"content": f"文![i]({path})", "file": None, "title": "t",
                          "json": True, "log_file": None, "dedup": False,
                          "transform_images": True, "dry_run": True})()
    import io, json as _json
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        m._cmd_create(u, args)
    report = _json.loads(buf.getvalue())
    expect(report["mode"] in ("inline", "batched"), "报告缺 mode")
    expect(len(report["images"]) == 1, "报告缺图片统计")
    expect(len(report["batches"]) == 2, f"应切成 text+image 两批: {report['batches']}")
    expect(report["batches"][0]["type"] == "text" and report["batches"][1]["type"] == "image", "批次顺序错误")
    expect(len(u.calls) == 0, "dry-run 不应发起任何请求")
    Path(path).unlink()


@case("transform 超内联上限时降级分批 append_doc（D2）")
def _():
    u = FakeUploader()
    path = _tiny_png_file()
    old_limit = m.BATCH_INLINE_LIMIT
    m.BATCH_INLINE_LIMIT = 16  # 压到极小逼出降级
    try:
        md = f"段落一\n\n![i]({path})\n\n段落二"
        content, batches, report = m._apply_transform(md, True)
        expect(batches is not None, "超限应进入分批模式")
        expect(report["mode"] == "batched", "报告 mode 应为 batched")
        expect(report["degrade"] == "inline→batched (size)", f"报告应带降级可读标记: {report.get('degrade')}")
        u.responses["openapi/note/v1/import_doc"] = {"code": 0, "data": {"note_id": "nb1"}}
        r = u.create_note("t", md, transform_images=True)
        paths = [c["path"] for c in u.calls]
        expect(paths[0] == "openapi/note/v1/import_doc", "首批应走 import_doc")
        expect(paths[1:] == ["openapi/note/v1/append_doc"] * (len(paths) - 1), f"其余批应走 append_doc: {paths}")
        expect(len(paths) == 1 + (len(batches) - 1), f"批次数不符: {paths}")
        expect(r["note_id"] == "nb1", "note_id 错误")
    finally:
        m.BATCH_INLINE_LIMIT = old_limit
        Path(path).unlink()


@case("upload_note_image 换链请求体正确（upload_temp_file → get_access_url）")
def _():
    u = FakeUploader()
    u.responses["openapi/mcp_cloud_agent/upload_temp_file"] = {"code": 0, "data": {"coskey": "ck1"}}
    u.responses["openapi/mcp_cloud_agent/get_access_url"] = {"code": 0, "data": {"download_url": "https://x/i.png"}}
    path = _tiny_png_file()
    r = u.upload_note_image(path)
    expect(r["url"] == "https://x/i.png", f"download_url 解析错误: {r}")
    expect(r["mime"] == "image/png", "mime 错误")
    expect(u.calls[0]["path"] == "openapi/mcp_cloud_agent/upload_temp_file", "首个端点错误")
    expect(u.calls[0]["body"]["file_path"].endswith("image.png"), f"应传规范化临时路径: {u.calls[0]['body']}")
    expect(u.calls[1]["body"] == {"coskey": "ck1"}, "get_access_url body 错误")
    Path(path).unlink()


@case("upload_note_image 遇 session 业务错误给出降级指引（D3）")
def _():
    u = FakeUploader()

    def raise_session(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        raise m.IMAError(100001, "session ID is required")
    u._request = raise_session
    path = _tiny_png_file()
    try:
        u.upload_note_image(path)
    except m.IMAError as e:
        expect("不可用" in e.msg or "不支持" in e.msg, f"应给出降级指引: {e.msg}")
        expect("transform-images" in e.msg, "应提示改用 --transform-images: " + e.msg)
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("session 错误未转为降级指引")


@case("upsert_note transform_images 透传到写入路径")
def _():
    u = FakeUploader()
    u.responses["openapi/note/v1/search_note"] = {"code": 0, "data": {"search_note_infos": []}}
    u.responses["openapi/note/v1/import_doc"] = {"code": 0, "data": {"note_id": "nt1"}}
    path = _tiny_png_file()
    r = u.upsert_note("标题", f"文![i]({path})", transform_images=True)
    expect(r["action"] == "created", "应走新建")
    sent = u.calls[-1]["body"]["content"]
    expect("data:image/png;base64," in sent, "transform 未生效")
    expect(path not in sent, "原路径残留")
    Path(path).unlink()


# ---------------- 返工修复（P0 路径穿越 / 报错降级 / P1 视频 MIME / P2 防御） ----------------

@case("download_media 穿越型 media_title 被收敛，不写穿 out_dir")
def _():
    u = FakeUploader()
    evil = urllib.parse.quote("../../../evil.md", safe="")
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": f"https://skb.ima.myqcloud.com/a/b?media_id=m1&media_title={evil}&sign=s", "headers": {}},
    }}
    got = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        got["dest"] = dest_path
        Path(dest_path).write_bytes(b"x")
    u._http_download = fake_dl

    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        out_root = Path(td).resolve()
        r = u.download_media("m1", output_dir=td)
        dest = Path(got["dest"]).resolve()
        expect(dest.is_relative_to(out_root), f"落点必须收敛在 out_dir 内: {dest}")
        expect("\\" not in r["file_name"] and "/" not in r["file_name"],
               f"返回文件名不得含路径分量: {r['file_name']}")
        expect(r["file_name"] == "evil.md", f"应只取 basename: {r['file_name']}")
        outside = Path(td).parent / "evil.md"
        expect(not outside.exists(), f"out_dir 外出现文件: {outside}")


@case("download_media 绝对路径型 media_title 被收敛，不覆盖系统路径")
def _():
    u = FakeUploader()
    evil = urllib.parse.quote("C:\\Windows\\evil.md", safe="")
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": f"https://skb.ima.myqcloud.com/a/b?media_id=m2&media_title={evil}&sign=s", "headers": {}},
    }}
    got = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        got["dest"] = dest_path
        Path(dest_path).write_bytes(b"x")
    u._http_download = fake_dl

    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        out_root = Path(td).resolve()
        r = u.download_media("m2", output_dir=td)
        dest = Path(got["dest"]).resolve()
        expect(dest.is_relative_to(out_root), f"落点必须收敛在 out_dir 内: {dest}")
        expect(":" not in r["file_name"], f"文件名不得含盘符/冒号: {r['file_name']}")
        expect(r["file_name"] == "evil.md", f"应只取 basename: {r['file_name']}")
        expect("Windows" not in got["dest"], f"落点不得指向系统目录: {got['dest']}")


@case("transform inline 写入报错后自动降级分批 append_doc（D2 报错降级）")
def _():
    u = FakeUploader()
    path = _tiny_png_file()

    def size_limited(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        if api_path.endswith("import_doc") and len(body.get("content", "")) > 60:
            raise m.IMAError(-1, "content too large")
        return {"code": 0, "data": {"note_id": "nb2"}}
    u._request = size_limited

    md = f"段落一\n\n![i]({path})\n\n段落二"
    r = u.create_note("t", md, transform_images=True)
    paths = [c["path"] for c in u.calls]
    expect(paths[0] == "openapi/note/v1/import_doc", "先尝试 inline import_doc")
    expect(paths[1] == "openapi/note/v1/import_doc", "降级后首批仍走 import_doc")
    expect(all(p == "openapi/note/v1/append_doc" for p in paths[2:]),
           f"其余批应走 append_doc: {paths}")
    expect(len(paths) >= 4, f"inline 失败后应分 3 批写入: {paths}")
    expect(r["note_id"] == "nb2", "降级后仍应返回 note_id")
    expect(r.get("degraded") == "inline→batched", f"结果应带降级标记: {r}")
    Path(path).unlink()


@case("upload_file_to_kb 视频 MIME 黑名单拦截（content-type 命中即拒）")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"data")
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1", content_type="video/mp4")
    except m.IMAError as e:
        expect("视频" in e.msg, f"错误信息应说明视频不支持: {e.msg}")
        expect(len(u.calls) == 0, "视频 MIME 应在预检阶段拦截")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("视频 MIME 未拦截")


@case("create/append_note_batched 空批防御（转 IMAError 不裸抛 IndexError）")
def _():
    u = FakeUploader()
    for fn, args in ((u.create_note_batched, ("t", [])),
                     (u.append_note_batched, ("n1", [])),
                     (u._write_note_batches, ("n1", []))):
        try:
            fn(*args)
        except m.IMAError as e:
            expect("不能为空" in e.msg, f"空批错误信息应可判读: {e.msg}")
            continue
        except Exception as e:
            raise AssertionError(f"{fn.__name__} 空批裸抛 {type(e).__name__}，应转 IMAError")
        raise AssertionError(f"{fn.__name__} 空批未拦截")


# ---------------- 收尾修缮（P2-6 设备名 / P2-7 错误分类 / P2-8 序号棘轮） ----------------

@case("download_media Windows 保留设备名 CON.md 被加前缀改写（防静默吞数据）")
def _():
    u = FakeUploader()
    evil = urllib.parse.quote("CON.md", safe="")
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": f"https://skb.ima.myqcloud.com/a/b?media_id=m1&media_title={evil}&sign=s", "headers": {}},
    }}
    got = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        got["dest"] = dest_path
        Path(dest_path).write_bytes(b"x")
    u._http_download = fake_dl

    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        out_root = Path(td).resolve()
        r = u.download_media("m1", output_dir=td)
        expect(r["file_name"] == "safe_CON.md", f"保留设备名应加 safe_ 前缀: {r['file_name']}")
        expect(Path(r["file_name"]).stem.lower() not in m._WINDOWS_RESERVED_NAMES,
               "改写后主干不得仍是保留设备名")
        expect(Path(got["dest"]).resolve().is_relative_to(out_root), "落点须收敛在 out_dir 内")


@case("download_media Windows 保留设备名 NUL 被加前缀改写")
def _():
    u = FakeUploader()
    evil = urllib.parse.quote("NUL", safe="")
    u.responses["openapi/wiki/v1/get_media_info"] = {"code": 0, "data": {
        "media_type": 7,
        "url_info": {"url": f"https://skb.ima.myqcloud.com/a/b?media_id=m1&media_title={evil}&sign=s", "headers": {}},
    }}
    got = {}

    def fake_dl(url, headers, dest_path, timeout=120):
        got["dest"] = dest_path
        Path(dest_path).write_bytes(b"x")
    u._http_download = fake_dl

    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        out_root = Path(td).resolve()
        r = u.download_media("m1", output_dir=td)
        expect(r["file_name"] == "safe_NUL", f"保留设备名应加 safe_ 前缀: {r['file_name']}")
        expect(Path(r["file_name"]).stem.lower() not in m._WINDOWS_RESERVED_NAMES,
               "改写后主干不得仍是保留设备名")
        expect(Path(got["dest"]).resolve().is_relative_to(out_root), "落点须收敛在 out_dir 内")


@case("业务错误（敏感词）不做降级白重试，原样报错只调 1 次")
def _():
    u = FakeUploader()
    path = _tiny_png_file()

    def biz_fail(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        raise m.IMAError(100203, "标题包含敏感词")
    u._request = biz_fail

    md = f"段落一\n\n![i]({path})\n\n段落二"  # 可切分多批：错误分类失效就会触发白重试
    try:
        u.create_note("t", md, transform_images=True)
    except m.IMAError as e:
        expect(e.code == 100203, f"应原样抛出业务错误码: {e.code}")
        expect("标题包含敏感词" in e.msg, f"应保留原错误信息: {e.msg}")
        expect("均失败" not in e.msg, "业务错误不应拼接降级文案")
        expect(len(u.calls) == 1, f"业务错误不应白重试，import_doc 应只调 1 次，实际 {len(u.calls)}")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("业务错误未原样抛出")


@case("keep-copy 同秒碰撞时序号棘轮重试，序号名复查通过即上传")
def _():
    u = FakeUploader()
    checked = []

    def smart(api_path, body, timeout=30):
        u.calls.append({"path": api_path, "body": body})
        if api_path.endswith("check_repeated_names"):
            name = body["params"][0]["name"]
            checked.append(name)
            # 原名与无序号时间戳名冲突，序号 _1 起放行
            return {"code": 0, "data": {"results": [{"name": name, "is_repeated": len(checked) <= 2}]}}
        if api_path.endswith("create_media"):
            return {"code": 0, "data": {
                "media_id": "m20",
                "cos_credential": {"token": "t", "secret_id": "s", "secret_key": "k",
                                   "bucket_name": "b", "region": "r", "cos_key": "ck",
                                   "start_time": 1, "expired_time": 2},
            }}
        return {"code": 0, "data": {"media_id": "m20"}}
    u._request = smart

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"x")
        path = f.name
    import re
    r = u.upload_file_to_kb(path, "kb1", on_duplicate="keep-copy")
    expect(r["action"] == "uploaded", "序号名通过后应继续上传")
    expect(len(checked) == 3, f"应为原名 + ts + ts_1 共 3 次查重，实际 {len(checked)}: {checked}")
    expect(re.search(r"_\d{14}_1\.md$", checked[-1]), f"最终名应为序号名: {checked[-1]}")
    ak = next(c for c in u.calls if c["path"].endswith("add_knowledge"))
    expect(ak["body"]["title"] == checked[-1], f"title 应等于复查通过的序号名: {ak['body']['title']}")
    Path(path).unlink()


# ---------------- 常量表一致性 ----------------

@case("EXT_MAP 的 media_type 与官方 MediaType 枚举一致")
def _():
    expected = {
        "pdf": 1, "doc": 3, "docx": 3, "ppt": 4, "pptx": 4,
        "xls": 5, "xlsx": 5, "csv": 5, "md": 7, "markdown": 7,
        "png": 9, "jpg": 9, "jpeg": 9, "webp": 9, "txt": 13,
        "xmind": 14, "mp3": 15, "m4a": 15, "wav": 15, "aac": 15,
        "html": 20, "epub": 21,
    }
    actual = {k: v["media_type"] for k, v in m.EXT_MAP.items()}
    for ext, mt in expected.items():
        expect(actual.get(ext) == mt, f"{ext} 的 media_type 应为 {mt}，实际 {actual.get(ext)}")
    for ext in m.UNSUPPORTED_VIDEO_EXT:
        expect(ext not in actual, f"视频后缀 {ext} 不应出现在 EXT_MAP")


@case("SIZE_LIMITS 与官方一致（含 HTML 10MB / EPUB 50MB）")
def _():
    expect(m.SIZE_LIMITS.get(20) == 10 * m.MB, "HTML(media_type=20) 限制应为 10MB")
    expect(m.SIZE_LIMITS.get(21) == 50 * m.MB, "EPUB(media_type=21) 限制应为 50MB")
    expect(m.EXT_MAP["html"]["content_type"] == "text/html", "html content_type 错误")
    expect(m.EXT_MAP["epub"]["content_type"] == "application/epub+zip", "epub content_type 错误")


@case("upload_file_to_kb HTML 超过 10MB 被拦截")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.seek(11 * 1024 * 1024)
        f.write(b"0")
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("超过限制" in e.msg, f"错误信息未说明超限: {e.msg}")
        expect(len(u.calls) == 0, "预检失败不应发起请求")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("HTML 超限未拦截")


@case("upload_file_to_kb EPUB 超过 50MB 被拦截")
def _():
    u = FakeUploader()
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as f:
        f.seek(51 * 1024 * 1024)
        f.write(b"0")
        path = f.name
    try:
        u.upload_file_to_kb(path, "kb1")
    except m.IMAError as e:
        expect("超过限制" in e.msg, f"错误信息未说明超限: {e.msg}")
        expect(len(u.calls) == 0, "预检失败不应发起请求")
        Path(path).unlink()
        return
    Path(path).unlink()
    raise AssertionError("EPUB 超限未拦截")


@case("MEDIA_TYPE_LABELS 覆盖 EXT_MAP 全部类型")
def _():
    used = {v["media_type"] for v in m.EXT_MAP.values()}
    missing = used - set(m.MEDIA_TYPE_LABELS)
    expect(not missing, f"缺少标签的 media_type: {missing}")


def main():
    print("=" * 62)
    print("  ima_upload 请求契约测试（不发起真实请求）")
    print("=" * 62)
    # 用例通过 @case 装饰器在导入时即执行
    print()
    total = len(PASSED) + len(FAILED)
    print(f"结果：{len(PASSED)}/{total} 通过")
    if VERBOSE and FAILED:
        print("\n失败明细：")
        for name, err in FAILED:
            print(f"  - {name}: {err}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
