# ============================================================
# Short Gainers Agent - Task Scheduler Setup
# Creates a Windows scheduled task that runs every 15 minutes
# during market hours (Mon-Fri, 9:30 AM - 4:00 PM ET)
#
# Usage: Run this script once as Administrator
#   powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
# ============================================================

$TaskName = "ShortGainersRefresh"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BatchScript = Join-Path $ProjectDir "run_scheduled.bat"

# Verify the batch script exists
if (-not (Test-Path $BatchScript)) {
    Write-Error "run_scheduled.bat not found at: $BatchScript"
    exit 1
}

# Remove existing task if it exists
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: run the batch script
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchScript`"" `
    -WorkingDirectory $ProjectDir

# Triggers: every 15 minutes during market hours (Mon-Fri)
# We create triggers for each 15-minute slot from 9:30 AM to 3:45 PM ET
$Triggers = @()

# Market hours: 9:30 AM to 4:00 PM ET (last run at 3:45 PM since it takes ~5 min)
$startHour = 9
$startMinute = 30
$endHour = 15
$endMinute = 45

for ($h = $startHour; $h -le $endHour; $h++) {
    $minStart = if ($h -eq $startHour) { $startMinute } else { 0 }
    $minEnd = if ($h -eq $endHour) { $endMinute } else { 45 }

    for ($m = $minStart; $m -le $minEnd; $m += 15) {
        $timeStr = "{0:D2}:{1:D2}" -f $h, $m
        $trigger = New-ScheduledTaskTrigger -Weekly `
            -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
            -At $timeStr
        $Triggers += $trigger
    }
}

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

# Register the task (runs as current user)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "Auto-refresh Short Gainers analysis every 15 min during market hours" `
    -RunLevel Limited

Write-Host ""
Write-Host "Task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Schedule: Every 15 minutes, Mon-Fri, 9:30 AM - 4:00 PM ET"
Write-Host "Script:   $BatchScript"
Write-Host "Logs:     $(Join-Path $ProjectDir 'logs')"
Write-Host ""
Write-Host "To verify: Open Task Scheduler and look for '$TaskName'"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName'"
