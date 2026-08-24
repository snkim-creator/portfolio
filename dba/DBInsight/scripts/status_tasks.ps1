<#
.SYNOPSIS
  DBInsight 스케줄 작업 상태 확인 (마지막 실행 시각/결과, 다음 실행 시각).
  LastTaskResult 0 = 정상.
#>
$tasks = Get-ScheduledTask -TaskName 'DBInsight-*' -ErrorAction SilentlyContinue
if (-not $tasks) {
    Write-Host "등록된 DBInsight 작업이 없습니다. scripts\register_tasks.ps1 로 등록하세요."
    return
}
$tasks | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    [PSCustomObject]@{
        Task           = $_.TaskName
        State          = $_.State
        LastRunTime    = $info.LastRunTime
        LastTaskResult = $info.LastTaskResult
        NextRunTime    = $info.NextRunTime
    }
} | Format-Table -AutoSize
