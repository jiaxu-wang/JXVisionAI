# 管理员 PowerShell 执行：放行 ZLM 国标 PS/RTP 10000-10200
$lo = 10000
$hi = 10200
foreach ($proto in @('UDP', 'TCP')) {
    $name = "JXVisionAI-GB28181-RTP-$proto"
    Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol $proto -LocalPort "$lo-$hi" | Out-Null
    Write-Host "added $name $lo-$hi"
}
