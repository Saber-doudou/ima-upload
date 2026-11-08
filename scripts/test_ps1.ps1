#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    ima_upload.ps1 契约测试（PowerShell 侧）

.DESCRIPTION
    通过 -MockFile / -CaptureFile 注入预设响应并记录请求，不联网、不写真实 IMA 数据。
    覆盖此前手工实跑才发现、且无任何自动保护的四处：标题写入、content 自带标题、
    正文搜索的 query_info 键、append 不写标题行、以及 ima-openapi-ctx 请求头。

    为什么单独一套：ps1 是 PowerShell，Python 侧的 FakeUploader 拦不到它的网络调用；
    沙箱也不允许从 Python/Bash 启动 PowerShell。所以 ps1 的回归只能在这里做。

.USAGE
    脚本被安全策略限制时用 scriptblock 方式跑：
        $p = ".\scripts\test_ps1.ps1"
        & ([scriptblock]::Create([IO.File]::ReadAllText($p)))
    允许执行脚本时可直接：
        powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_ps1.ps1
#>

param(
    # scriptblock 方式运行时无法从 $PSScriptRoot / $MyInvocation 推断目录，需显式指定 scripts 目录
    [string]$ScriptDir = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ProgressPreference = "SilentlyContinue"

$here = $ScriptDir
if (-not $here) { $here = $PSScriptRoot }
if (-not $here) { throw "无法确定脚本目录，请用 -ScriptDir 指定 ima-upload/scripts 目录" }
$target = Join-Path $here "ima_upload.ps1"
if (-not (Test-Path $target)) { throw "找不到被测脚本: $target" }

# 用 scriptblock 载入，绕过文件执行策略（与本文件自身的运行方式一致）
$sb = [scriptblock]::Create([System.IO.File]::ReadAllText($target))

$script:Pass = 0
$script:Fail = 0

function New-Fixture {
    param([hashtable]$Mocks)
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("ima-ps1-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dir | Out-Null
    $mockPath = Join-Path $dir "mock.json"
    ($Mocks | ConvertTo-Json -Depth 10) | Set-Content -Path $mockPath -Encoding UTF8
    return @{ Dir = $dir; Mock = $mockPath; Capture = (Join-Path $dir "cap.jsonl") }
}

function Get-Captured {
    param([string]$Path)
    # 尾随一元逗号：单元素数组不会被 PowerShell 解包成单个对象，调用方 .Count 永远可用
    if (-not (Test-Path $Path)) { return ,@() }
    return ,@(Get-Content -Path $Path -Encoding UTF8 |
        Where-Object { $_.Trim() } |
        ForEach-Object { $_ | ConvertFrom-Json })
}

function Check {
    param([bool]$Cond, [string]$Name, [string]$Detail = "")
    if ($Cond) {
        $script:Pass++
        Write-Output "  OK   $Name"
    } else {
        $script:Fail++
        Write-Output "  FAIL $Name $Detail"
    }
}

# ---------------- 用例 ----------------

# 1. create 把标题写进正文首行，且不再传 title 字段
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "n1" } } }
try {
    $out = & $sb create "标题P" "正文内容" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $cap = Get-Captured $fx.Capture
    Check ($cap.Count -eq 1) "create 发出 1 次请求" "实际 $($cap.Count)"
    $body = $cap[0].body
    Check ($null -eq $body.title) "create 不传 title 字段（API 无此字段）" "body keys: $($body.PSObject.Properties.Name -join ',')"
    Check ($body.content -like "# 标题P*正文内容") "create 标题写入正文首行" ("content=" + $body.content)
    Check ($body.content_format -eq 1) "content_format=1"
    $parsed = ($out | Out-String).Trim() | ConvertFrom-Json
    Check ($parsed.note_id -eq "n1") "create 输出 JSON 且 note_id 正确" ("out=" + ($out | Out-String))
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 2. content 已带一级标题时不重复前置
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "n2" } } }
try {
    $out = & $sb create "标题Q" "# 已有标题`r`n`r`n正文" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $body = (Get-Captured $fx.Capture)[0].body
    Check ($body.content -notlike "*标题Q*") "已带标题时不插入第二个标题" ("content=" + $body.content)
    Check ($body.content -like "# 已有标题*") "保留原有标题" ("content=" + $body.content)
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 3. search -Type content 必须构造 content 键且 search_type=1
$fx = New-Fixture @{ search_note = @{ code = 0; data = @{ search_note_infos = @() } } }
try {
    $null = & $sb search "关键词" -Type content -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $body = (Get-Captured $fx.Capture)[0].body
    Check ($body.search_type -eq 1) "正文搜索 search_type=1" ("实际 " + $body.search_type)
    Check ($null -ne $body.query_info.content) "正文搜索用 query_info.content" ("keys: " + ($body.query_info.PSObject.Properties.Name -join ','))
    Check ($null -eq $body.query_info.title) "正文搜索不塞 title 键"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 4. search 默认按标题搜
$fx = New-Fixture @{ search_note = @{ code = 0; data = @{ search_note_infos = @() } } }
try {
    $null = & $sb search "关键词" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $body = (Get-Captured $fx.Capture)[0].body
    Check ($body.search_type -eq 0) "标题搜索 search_type=0" ("实际 " + $body.search_type)
    Check ($null -ne $body.query_info.title) "标题搜索用 query_info.title"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 5. append 不写标题行
$fx = New-Fixture @{ append_doc = @{ code = 0; data = @{} } }
try {
    $out = & $sb append "n5" "追加的纯文本" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $body = (Get-Captured $fx.Capture)[0].body
    Check ($body.content -eq "追加的纯文本") "append 不给内容加标题行" ("content=" + $body.content)
    Check ($body.note_id -eq "n5") "append 传对 note_id"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 6. 请求头带 ima-openapi-ctx（值可能是 unknown，只要格式在）
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "n6" } } }
try {
    $null = & $sb create "标题R" "正文" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $h = (Get-Captured $fx.Capture)[0].headers
    Check ($null -ne $h.'ima-openapi-ctx') "请求头含 ima-openapi-ctx"
    Check ($h.'ima-openapi-ctx' -like "skill_version=*") "ctx 头格式正确" ("实际 " + $h.'ima-openapi-ctx')
    Check ([bool]$h.'ima-openapi-clientid') "携带 clientid 头"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 6b. capture 文件不得落真实凭证（clientid/apikey 必须脱敏）
# 这条是安全回归：capture 会落盘，明文凭证在调用被打断时可能残留。
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "n6b" } } }
try {
    $null = & $sb create "标题S" "正文" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $capRaw = Get-Content $fx.Capture -Raw -Encoding UTF8
    Check ($capRaw -like "*REDACTED*") "capture 中凭证已替换为 REDACTED"
    $leaked = @()
    foreach ($name in @("client_id", "api_key")) {
        $fp = Join-Path (Join-Path $HOME ".config/ima") $name
        if (Test-Path $fp) {
            $v = (Get-Content $fp -Raw -Encoding UTF8).Trim()
            if ($v -and $capRaw.Contains($v)) { $leaked += $name }
        }
    }
    Check ($leaked.Count -eq 0) "capture 未写入真实凭证" ("泄漏项: " + ($leaked -join ","))
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 6c. mock 模式结果必须带 mock=true，否则自动化会把假成功当归档成功
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "n6c" } } }
try {
    $out = & $sb create "标题T" "正文" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $o = (($out | Out-String).Trim() | ConvertFrom-Json)
    Check ($o.mock -eq $true) "create 的 mock 模式输出带 mock=true"
    Check ($o.note_id -eq "n6c") "mock 响应仍被正常解析"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 6d. -NoExit 不得脱离测试注入点单独使用
$fx = New-Fixture @{}
try {
    $threw = $false
    try { $null = & $sb create "标题U" "正文" -Json -NoExit } catch { $threw = $true }
    Check $threw "-NoExit 单独使用被拒绝"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 6e. mock 模式下 -Log 不得写映射文件（假 note_id 写进去会让后续 append 指向不存在的笔记）
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "FAKE_ID" } } }
try {
    $logPath = Join-Path $fx.Dir "note_ids.jsonl"
    $null = & $sb create "标题V" "正文" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture -Log $logPath
    $logExists = Test-Path $logPath
    $logEmpty = if ($logExists) { ((Get-Content $logPath -Raw -Encoding UTF8).Trim().Length -eq 0) } else { $true }
    Check ((-not $logExists) -or $logEmpty) "mock 模式不把假 note_id 写进映射文件"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 6f. mock 模式 search 的 JSON 结果逐条带 mock=true
$fx = New-Fixture @{ search_note = @{ code = 0; data = @{ search_note_infos = @(
    @{ note_book_info = @{ note_id = "r1"; title = "标题"; summary = "s" } }
) } } }
try {
    $out = & $sb search "关键词" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $o = (($out | Out-String).Trim() | ConvertFrom-Json)
    Check ($o.mock -eq $true) "search 的 mock 结果带 mock=true"
    Check ($o.note_id -eq "r1") "search 结果字段未被破坏"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 7. 中文与 JSON 输出不被破坏
$fx = New-Fixture @{ import_doc = @{ code = 0; data = @{ note_id = "n7" } } }
try {
    $out = & $sb create "中文标题·测试" "包含中文与标点：第一段。" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture
    $text = ($out | Out-String).Trim()
    $body = (Get-Captured $fx.Capture)[0].body
    Check ($body.content -like "*中文标题·测试*") "中文标题正确写入"
    Check ($body.content -like "*包含中文与标点：第一段。*") "中文正文正确写入"
    Check ($text -like '*"note_id"*') "输出是可解析的 JSON 文本"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 8. create 业务错误：输出 error JSON、以退出码 1 结束、不写 note_id 日志
$fx = New-Fixture @{ import_doc = @{ code = 100005; msg = "no permission" } }
try {
    $logPath = Join-Path $fx.Dir "log.jsonl"
    $out = try {
        & $sb create "标题X" "正文" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture -Log $logPath -NoExit
    } catch { "CAUGHT:" + $_.Exception.Message }
    $text = ($out | Out-String)
    Check ($text -like '*"error"*') "业务错误输出 error 字段" ("out=" + $text)
    Check ($text -like "*CAUGHT:EXIT:1*") "业务错误以退出码 1 结束" ("out=" + $text)
    Check (-not (Test-Path $logPath)) "业务错误不写 note_id 日志（防假成功）"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 9. append 缺 note_id：不发请求，直接退出
$fx = New-Fixture @{}
try {
    $out = try {
        & $sb append -Json -MockFile $fx.Mock -CaptureFile $fx.Capture -NoExit
    } catch { "CAUGHT:" + $_.Exception.Message }
    $text = ($out | Out-String)
    Check ($text -like "*CAUGHT:EXIT:1*") "append 缺参以退出码 1 结束" ("out=" + $text)
    Check ((Get-Captured $fx.Capture).Count -eq 0) "append 缺参不发请求"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# 10. search 业务错误：同样以退出码 1 结束
$fx = New-Fixture @{ search_note = @{ code = 400; msg = "bad request" } }
try {
    $out = try {
        & $sb search "关键词" -Json -MockFile $fx.Mock -CaptureFile $fx.Capture -NoExit
    } catch { "CAUGHT:" + $_.Exception.Message }
    $text = ($out | Out-String)
    Check ($text -like "*CAUGHT:EXIT:1*") "search 业务错误以退出码 1 结束" ("out=" + $text)
    Check ((Get-Captured $fx.Capture).Count -eq 1) "search 已发出 1 次请求"
} finally { Remove-Item $fx.Dir -Recurse -Force }

# ---------------- 汇总 ----------------
Write-Output ""
$total = $script:Pass + $script:Fail
Write-Output "结果：$($script:Pass)/$total 通过"
if ($script:Fail -gt 0) {
    # 作为文件运行时用退出码表达失败；scriptblock 方式（沙箱受限时）不退出，
    # 否则整段输出会被 exit 截断，看不到是哪条挂了。
    if ($PSScriptRoot) { exit 1 }
}
