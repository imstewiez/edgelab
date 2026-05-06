# Setup Windows Task Scheduler for hourly MultiTF paper trading
# Run as Administrator if needed

$taskName = "MultiTF-PaperTrader"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"cd '$PSScriptRoot'; & .\multitf.bat live`""

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date.AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 365)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force

Write-Host "Task '$taskName' created successfully."
Write-Host "Runs every hour at :05 past the hour."
Write-Host ""
Write-Host "To check: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
