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
    [switch]$Json,
    [string]$Log
)

$ErrorActionPreference = "Stop"

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
        Write-Output ([System.Text.Encoding]::UTF8.GetBytes("{`"error`":true,`"msg`":`"$msg`"}"))
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
    }
    $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 10))
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Post -Body $utf8Bytes -Headers $headers -TimeoutSec 30
        return $resp
    } catch {
        throw "API请求失败: $_"
    }
}

function Read-FileContent {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        if ($Json) {
            Write-Output ([System.Text.Encoding]::UTF8.GetBytes("{`"error`":true,`"msg`":`"文件不存在: $Path`"}"))
        } else {
            Write-Error "文件不存在: $Path"
        }
        exit 1
    }
    # 尝试 UTF-8，失败则 GBK
    try {
        return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
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

        $body = @{
            title          = $title
            content        = $content
            content_format = 1
        }
        $resp = Invoke-IMAApi -Endpoint "import_doc" -Body $body

        if ($resp.code -ne 0) {
            $msg = "[IMA Error $($resp.code)] $($resp.msg)"
            if ($Json) {
                Write-Output ([System.Text.Encoding]::UTF8.GetBytes("{`"error`":true,`"code`":$($resp.code),`"msg`":`"$($resp.msg)`"}"))
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
            Write-Output ([System.Text.Encoding]::UTF8.GetBytes(($result | ConvertTo-Json -Compress)))
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
                Write-Output ([System.Text.Encoding]::UTF8.GetBytes("{`"error`":true,`"code`":$($resp.code),`"msg`":`"$($resp.msg)`"}"))
            } else {
                Write-Error "[IMA Error $($resp.code)] $($resp.msg)"
            }
            exit 1
        }

        if ($Json) {
            Write-Output ([System.Text.Encoding]::UTF8.GetBytes("{`"note_id`":`"$noteId`",`"ok`":true}"))
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
        $searchType = 0
        if ($File -eq "content") { $searchType = 1 }

        $body = @{
            search_type = $searchType
            query_info  = @{ title = $keyword }
            start       = 0
            end         = 20
        }
        $resp = Invoke-IMAApi -Endpoint "search_note" -Body $body

        if ($resp.code -ne 0) {
            if ($Json) {
                Write-Output ([System.Text.Encoding]::UTF8.GetBytes("{`"error`":true,`"code`":$($resp.code),`"msg`":`"$($resp.msg)`"}"))
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
            Write-Output ([System.Text.Encoding]::UTF8.GetBytes(($output | ConvertTo-Json -Depth 5)))
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
