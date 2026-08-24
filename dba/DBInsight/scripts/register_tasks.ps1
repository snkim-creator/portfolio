<#
.SYNOPSIS
  DBInsight 스케줄 작업 등록 (Windows Task Scheduler).
    - DBInsight-Collect<Suffix> : 지정 간격(기본 10분)마다 `collect`
    - DBInsight-Report<Suffix>  : 매일 지정 시각(기본 09:00)에 `report`

.DESCRIPTION
  현재 로그인 사용자 권한으로 실행되며, 해당 사용자가 로그인해 있을 때만 동작한다
  (비밀번호/관리자 권한 불필요). 실행 로그는 logs/app.log 에 기록된다.

  다중 서버: -ConfigPath 로 서버별 config 를, -NameSuffix 로 작업 이름 접미사를 지정한다.
  (예: 별도 설정은 -ConfigPath config\config.sample-db.yaml -NameSuffix -sample)

  주의: `report` 작업은 외부 AI(KIMI/Moonshot)로 쿼리 digest(테이블/컬럼명 포함)를
  전송한다. 사내 정책상 부담되면 -CollectOnly 로 collect 만 등록하고 report 는 수동 실행.

.EXAMPLE
  # 기본 서버(config.yaml)
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1

  # 별도 설정 파일을 사용하는 추가 대상
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -ConfigPath config\config.sample-db.yaml -NameSuffix -sample

  # collect 만
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -CollectOnly
#>
[CmdletBinding()]
param(
    [int]$IntervalMinutes = 10,
    [string]$ReportTime = '09:00',
    [switch]$CollectOnly,
    [string]$ConfigPath = '',    # 비우면 기본 config/config.yaml 사용
    [string]$NameSuffix = ''     # 작업 이름 접미사 (예: -sample)
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
# 창 없는 실행을 위해 pythonw.exe 우선 사용 (없으면 python.exe 폴백)
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) {
    $python = Join-Path $root '.venv\Scripts\python.exe'
}
$entry = Join-Path $root 'app\main.py'
if (-not (Test-Path $python)) {
    throw "venv Python 이 없습니다: $python`n먼저 'python -m venv .venv' 후 'pip install -r requirements.txt' 를 실행하세요."
}
if (-not (Test-Path $entry)) { throw "진입점이 없습니다: $entry" }

# --config 인자 구성 (지정 시 절대경로화)
$configArg = ''
if ($ConfigPath -ne '') {
    $cfgFull = if ([System.IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath } else { Join-Path $root $ConfigPath }
    if (-not (Test-Path $cfgFull)) { throw "config 파일이 없습니다: $cfgFull" }
    $configArg = "--config `"$cfgFull`" "
}

$collectName = "DBInsight-Collect$NameSuffix"
$reportName = "DBInsight-Report$NameSuffix"

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

# --- Collect: N분마다 (오늘 0시부터 무기한 반복) ---
$collectAction = New-ScheduledTaskAction -Execute $python -Argument "`"$entry`" ${configArg}collect" -WorkingDirectory $root
$collectTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $collectName -Action $collectAction -Trigger $collectTrigger `
    -Settings $settings -Principal $principal `
    -Description "DBInsight: $IntervalMinutes 분마다 스냅샷 수집 ($ConfigPath)" -Force | Out-Null
Write-Host "[OK] 등록: $collectName ($IntervalMinutes 분 간격)"

# --- Report: 매일 지정 시각 ---
if (-not $CollectOnly) {
    $reportAction = New-ScheduledTaskAction -Execute $python -Argument "`"$entry`" ${configArg}report" -WorkingDirectory $root
    $reportTrigger = New-ScheduledTaskTrigger -Daily -At $ReportTime
    Register-ScheduledTask -TaskName $reportName -Action $reportAction -Trigger $reportTrigger `
        -Settings $settings -Principal $principal `
        -Description "DBInsight: 매일 $ReportTime 리포트 생성 ($ConfigPath)" -Force | Out-Null
    Write-Host "[OK] 등록: $reportName (매일 $ReportTime)"
} else {
    Write-Host "[SKIP] -CollectOnly: $reportName 은 등록하지 않음 (외부 AI 호출 회피). report 는 수동 실행."
}

Write-Host "`n상태 확인:  powershell -File scripts\status_tasks.ps1"
Write-Host "해제:       powershell -File scripts\unregister_tasks.ps1"
