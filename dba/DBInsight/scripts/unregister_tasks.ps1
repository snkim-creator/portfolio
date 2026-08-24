<#
.SYNOPSIS
  DBInsight 스케줄 작업 제거. 인자 없으면 모든 DBInsight-* 작업 제거.
.PARAMETER NameSuffix
  특정 접미사 작업만 제거 (예: -205 → DBInsight-Collect-205, DBInsight-Report-205).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\unregister_tasks.ps1
  powershell -ExecutionPolicy Bypass -File scripts\unregister_tasks.ps1 -NameSuffix -205
#>
param([string]$NameSuffix = '')
$ErrorActionPreference = 'Stop'

if ($NameSuffix -ne '') {
    $names = @("DBInsight-Collect$NameSuffix", "DBInsight-Report$NameSuffix")
} else {
    $names = (Get-ScheduledTask -TaskName 'DBInsight-*' -ErrorAction SilentlyContinue).TaskName
}

if (-not $names) {
    Write-Host "제거할 DBInsight 작업이 없습니다."
    return
}
foreach ($name in $names) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "[OK] 삭제: $name"
    }
}
