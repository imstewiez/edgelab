# Setup Windows Task Scheduler for portfolio trading
$taskName = "MultiTF-PaperTrader"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -Command `"cd 'C:\Users\steve\Documents\fx-trading-bot'; & .\trade_portfolio.bat`""

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

Write-Host "Portfolio task '$taskName' updated successfully."
Write-Host "Runs every hour at :05 past the hour."
