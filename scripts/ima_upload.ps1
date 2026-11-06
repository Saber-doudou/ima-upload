#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    IMA笔记上传 PowerShell 封装脚本
.DESCRIPTION
    封装 IMA OpenAPI，支持 create / append / search 子命令
    凭证自动从 ~/.config/ima/ 读取

    用法:
      .\ima_upload.ps1 create "标题" "内容"
      .\ima_upload.ps1 create "标题" -File notes.md
      .\ima_upload.ps1 create "标题" -File notes.md -Json -Log id_map.json
      .\ima_upload.ps1 append "note_id_here" "追加内容"
      .\ima_upload.ps1 append "note_id_here" -File update.md
      .\ima_upload.ps1 search "关键词"
      .\ima_upload.ps1 search "关键词" -Type content

    注意：必须使用 PowerShell（不是 Git Bash），且用 UTF-8 with BOM 保存
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet("create", "append", "search")]
    [string]$Command,

    [Parameter(Position=1)]
    [string]$Arg1,

    [Parameter(Position=2)]
    [string]$Arg2,

    [string]$File,
    [ValidateSet("title", "content")]
    [string]$Type = "title",
    [switch]$Json,
    [string]$Log
)

$ErrorActionPreference = "Stop"

# PS5.1 的 Invoke-WebRequest 会往输出流打「正在读取 Web 响应…」进度条，
# 会把 -Json 的机器可读输出污染成非 JSON。关掉，顺带显著加快大响应。
$ProgressPreference = "SilentlyContinue"

# 与 Python 侧同源：版本号从 _meta.json 读，不在这里再写一份常量。
# 用 scriptblock 方式调用时 $PSScriptRoot 可能为空，降级为 unknown（不影响功能，只影响 ctx 头）。
$SkillVersion = "unknown"
try {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
    if ($scriptDir) {
        $metaPath = Join-Path (Split-Path $scriptDir -Parent) "_meta.json"
        if (Test-Path $metaPath) {
            $SkillVersion = (Get-Content $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
        }
    }
} catch { }

# 统一控制台输出编码。PS5.1 默认按 GBK 编码输出，中文 JSON 会乱码；
# 设成 UTF-8 后可直接 Write-Output 字符串，不必再手工转字节数组。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-JsonError {
    # 用 ConvertTo-Json 生成，避免把含引号/换行的文本直接插进 JSON 字面量（会产出非法 JSON）
    param([string]$Msg, $Code = $null)
    $obj = @{ error = $true; msg = $Msg }
    if ($null -ne $Code) { $obj["code"] = $Code }
    Write-Output ($obj | ConvertTo-Json -Compress)
}

# ===== 凭证加载 =====
$ConfigBase = "$env:USERPROFILE\.config\ima"
$ClientIdPath = Join-Path $ConfigBase "client_id"
$ApiKeyPath   = Join-Path $ConfigBase "api_key"

function Get-FileContent {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bytes = $bytes[3..($bytes.Length-1)]
    }
    return [System.Text.Encoding]::UTF8.GetString($bytes).Trim()
}

$ClientId = Get-FileContent $ClientIdPath
$ApiKey   = Get-FileContent $ApiKeyPath

if (-not $ClientId -or -not $ApiKey) {
    $msg = "未找到IMA凭证。请确保以下文件存在：`n  $ClientIdPath`n  $ApiKeyPath"
    if ($Json) {
        Write-JsonError -Msg $msg
    } else {
        Write-Error $msg
    }
    exit 1
}

# ===== API 调用 =====
$BaseUrl = "https://ima.qq.com/openapi/note/v1"

function Invoke-IMAApi {
    param(
        [string]$Endpoint,
        [hashtable]$Body
    )
    $url = "$BaseUrl/$Endpoint"
    $headers = @{
        "Content-Type"          = "application/json; charset=utf-8"
        "ima-openapi-clientid" = $ClientId
        "ima-openapi-apikey"   = $ApiKey
        # 与 Python 侧一致：官方每个请求都带 skill_version（ima_api.cjs:72）
        "ima-openapi-ctx"      = "skill_version=$SkillVersion"
    }
    $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 10))
    try {
        # 用 Invoke-WebRequest 取原始字节后自己按 UTF-8 解码。
        # Invoke-RestMethod 在 PS5.1 上对「响应头没写 charset」的 JSON 默认按 ISO-8859-1 解析，
        # 中文会在解析阶段就变成 mojibake（实跑症状：输出里出现 "è®°å½æ¶é´" 这类拉丁乱码），
        # 且转换发生在返回对象之后，外层再怎么设编码都救不回来。
        # -MaximumRedirection 0：requests 侧已 allow_redirects=False，ps1 若不设会带着
        # clientid/apikey 两个 header 跟随 302 到别的地址。
        $resp = Invoke-WebRequest -Uri $url -Method Post -Body $utf8Bytes -Headers $headers -TimeoutSec 30 -UseBasicParsing -MaximumRedirection 0
        $json = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
        return ($json | ConvertFrom-Json)
    } catch {
        # 4xx/5xx 的响应体里通常带真实业务 code/msg，直接 throw 字符串会把它们丢掉。
        # 这里尽力解析响应体并原样返回，交给调用方的 code 判定统一报错。
        $webResp = $_.Exception.Response
        if ($webResp) {
            try {
                $stream = $webResp.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
                $raw = $reader.ReadToEnd()
                $reader.Close()
                if ($raw) {
                    $parsed = $raw | ConvertFrom-Json
                    if ($null -ne $parsed.code) { return $parsed }
                }
            } catch {
                # 响应体不是 JSON（如 302 空体），落到下面的统一报错
            }
        }
        throw "API请求失败: $_"
    }
}

function Read-FileContent {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        if ($Json) {
            Write-JsonError -Msg "文件不存在: $Path"
        } else {
            Write-Error "文件不存在: $Path"
        }
        exit 1
    }
    # UTF8Encoding(throwOnInvalidBytes=$true)：非法字节必须抛异常才能落到 GBK 兜底。
    # 原写法用 [Encoding]::UTF8，它把非法序列替换成 U+FFFD 而不抛异常，兜底分支永远不生效。
    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        return [System.IO.File]::ReadAllText($Path, $strictUtf8)
    } catch {
        return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::Default)
    }
}

function Write-NoteIdLog {
    param([string]$LogFile, [string]$Title, [string]$NoteId)
    $entry = (@{ title = $Title; note_id = $NoteId; created_at = (Get-Date -Format "o") } | ConvertTo-Json -Compress)
    Add-Content -Path $LogFile -Value $entry -Encoding UTF8
}

# ===== 主逻辑 =====
switch ($Command) {

    "create" {
        if (-not $Arg1) {
            Write-Error "create 需要提供标题"
            exit 1
        }
        $title = $Arg1
        $content = $Arg2

        if ($File) {
            $content = Read-FileContent $File
        }
        if (-not $content) {
            Write-Error "create 需要提供内容（位置参数或 -File）"
            exit 1
        }

        # 只认「content 以 Markdown 一级标题开头」，与 Python 侧 _MD_HEADING_RE 的 ^ 语义一致。
        # 原先用 (?m) 逐行匹配，content 中段出现标题时 ps1 不加前缀、Python 加，两条通道写入内容不同。
        if ($content -notmatch '^\s*#\s+\S') {
            $content = "# $title`r`n`r`n$content"
        }

        $body = @{
            content        = $content
            content_format = 1
        }
        $resp = Invoke-IMAApi -Endpoint "import_doc" -Body $body

        if ($resp.code -ne 0) {
            $msg = "[IMA Error $($resp.code)] $($resp.msg)"
            if ($Json) {
                Write-JsonError -Msg $resp.msg -Code $resp.code
            } else {
                Write-Error $msg
            }
            exit 1
        }

        $noteId = $resp.data.note_id
        $result = @{ note_id = $noteId; title = $title }

        if ($Log) {
            Write-NoteIdLog -LogFile $Log -Title $title -NoteId $noteId
        }

        if ($Json) {
            Write-Output ($result | ConvertTo-Json -Compress)
        } else {
            Write-Host "笔记创建成功" -ForegroundColor Green
            Write-Host "   note_id: $noteId"
            Write-Host "   title:   $title"
        }
    }

    "append" {
        if (-not $Arg1) {
            Write-Error "append 需要提供 note_id"
            exit 1
        }
        $noteId = $Arg1
        $content = $Arg2

        if ($File) {
            $content = Read-FileContent $File
        }
        if (-not $content) {
            Write-Error "append 需要提供内容（位置参数或 -File）"
            exit 1
        }

        $body = @{
            note_id        = $noteId
            content        = $content
            content_format = 1
        }
        $resp = Invoke-IMAApi -Endpoint "append_doc" -Body $body

        if ($resp.code -ne 0) {
            if ($Json) {
                Write-JsonError -Msg $resp.msg -Code $resp.code
            } else {
                Write-Error "[IMA Error $($resp.code)] $($resp.msg)"
            }
            exit 1
        }

        if ($Json) {
            Write-Output (@{ note_id = $noteId; ok = $true } | ConvertTo-Json -Compress)
        } else {
            Write-Host "内容已追加到笔记 $noteId" -ForegroundColor Green
        }
    }

    "search" {
        if (-not $Arg1) {
            Write-Error "search 需要提供关键词"
            exit 1
        }
        $keyword  = $Arg1
        # 官方 QueryInfo 有 title / content 两个字段，SearchType=1 是正文检索。
        # 原先只改了 search_type 却仍构造 title 键，等于「正文搜索还在搜标题」。
        if ($Type -eq "content") {
            $searchType = 1
            $queryInfo  = @{ content = $keyword }
        } else {
            $searchType = 0
            $queryInfo  = @{ title = $keyword }
        }

        $body = @{
            search_type = $searchType
            query_info  = $queryInfo
            start       = 0
            end         = 20
        }
        $resp = Invoke-IMAApi -Endpoint "search_note" -Body $body

        if ($resp.code -ne 0) {
            if ($Json) {
                Write-JsonError -Msg $resp.msg -Code $resp.code
            } else {
                Write-Error "[IMA Error $($resp.code)] $($resp.msg)"
            }
            exit 1
        }

        $notes = $resp.data.search_note_infos
        if ($Json) {
            $output = $notes | ForEach-Object {
                @{
                    note_id = $_.note_book_info.note_id
                    title   = $_.note_book_info.title
                    summary = $_.note_book_info.summary
                }
            }
            Write-Output ($output | ConvertTo-Json -Depth 5)
        } else {
            if ($notes.Count -eq 0) {
                Write-Host "未找到匹配「$keyword」的笔记"
            } else {
                Write-Host "找到 $($notes.Count) 条笔记：" -ForegroundColor Cyan
                foreach ($n in $notes) {
                    $ni = $n.note_book_info
                    Write-Host "  [$($ni.note_id)] $($ni.title)"
                    if ($ni.summary) {
                        Write-Host "       $($ni.summary.Substring(0, [Math]::Min(80, $ni.summary.Length)))"
                    }
                }
            }
        }
    }
}
