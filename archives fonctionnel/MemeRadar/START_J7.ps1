Set-Location -LiteralPath $PSScriptRoot
Write-Host "MemeRadar v6.7 - scanner et veille J7 - sorties manuelles"
$secret = Read-Host "Jeton J7 (saisie masquee)" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
    $env:J7_FEED_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    do {
        py -3 main.py --interval 20
        $result = $LASTEXITCODE
        if ($result -eq 75) {
            Write-Host "Redemarrage complet : scanner + J7 + verification X (base conservee)."
            Start-Sleep -Seconds 2
        }
    } while ($result -eq 75)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Item Env:J7_FEED_TOKEN -ErrorAction SilentlyContinue
    Read-Host "Programme termine. Appuyez sur Entree pour fermer"
}
