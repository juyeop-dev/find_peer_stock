# Windows password dialog; the token is never written to disk or arguments.
$ErrorActionPreference = 'Stop'
$taskCachePath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../data/tmp_scheduler_npm'))
$taskStatusDir = Join-Path $PSScriptRoot '.wrangler'
$taskStatusPath = Join-Path $taskStatusDir 'registration-status.json'
$taskPlainToken = $null

function Write-RegistrationStatus([string] $state) {
    [System.IO.Directory]::CreateDirectory($taskStatusDir) | Out-Null
    @{ status = $state; updated_at = [DateTimeOffset]::UtcNow.ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $taskStatusPath -Encoding UTF8
}

Push-Location $PSScriptRoot
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $taskDialog = New-Object System.Windows.Forms.Form
    $taskDialog.Text = 'Stock Peer Site - GitHub 토큰 등록'
    $taskDialog.ClientSize = New-Object System.Drawing.Size(540, 220)
    $taskDialog.StartPosition = 'CenterScreen'
    $taskDialog.FormBorderStyle = 'FixedDialog'
    $taskDialog.MaximizeBox = $false
    $taskDialog.MinimizeBox = $false
    $taskLabel = New-Object System.Windows.Forms.Label
    $taskLabel.Location = New-Object System.Drawing.Point(20, 20)
    $taskLabel.Size = New-Object System.Drawing.Size(500, 90)
    $taskLabel.Text = "GitHub에서 생성한 토큰을 아래에 붙여 넣으세요.`r`n저장소: juyeop-dev/find_peer_stock`r`n권한: Actions - Read and write`r`n토큰은 Cloudflare 비밀값으로만 저장합니다."
    $taskInput = New-Object System.Windows.Forms.TextBox
    $taskInput.Location = New-Object System.Drawing.Point(20, 115)
    $taskInput.Size = New-Object System.Drawing.Size(500, 25)
    $taskInput.UseSystemPasswordChar = $true
    $taskInput.MaxLength = 1024
    $taskSubmit = New-Object System.Windows.Forms.Button
    $taskSubmit.Text = '등록'
    $taskSubmit.Location = New-Object System.Drawing.Point(320, 165)
    $taskSubmit.Size = New-Object System.Drawing.Size(95, 32)
    $taskSubmit.DialogResult = 'OK'
    $taskCancel = New-Object System.Windows.Forms.Button
    $taskCancel.Text = '취소'
    $taskCancel.Location = New-Object System.Drawing.Point(425, 165)
    $taskCancel.Size = New-Object System.Drawing.Size(95, 32)
    $taskCancel.DialogResult = 'Cancel'
    $taskDialog.AcceptButton = $taskSubmit
    $taskDialog.CancelButton = $taskCancel
    $taskDialog.Controls.AddRange(@($taskLabel, $taskInput, $taskSubmit, $taskCancel))
    Write-RegistrationStatus 'waiting_for_input'
    while ($true) {
        if ($taskDialog.ShowDialog() -ne 'OK') {
            Write-RegistrationStatus 'cancelled'
            return
        }
        $taskPlainToken = $taskInput.Text.Trim()
        $taskInput.Clear()
        if ($taskPlainToken.StartsWith('github_pat_')) { break }
        $taskPlainToken = $null
        [System.Windows.Forms.MessageBox]::Show('github_pat_로 시작하는 fine-grained 토큰 전체를 붙여 넣어 주세요.', '토큰 확인') | Out-Null
    }

    Write-RegistrationStatus 'uploading'
    $taskPlainToken | & npm.cmd exec --yes --cache $taskCachePath --package wrangler@4.131.1 -- wrangler secret put GITHUB_TOKEN
    if ($LASTEXITCODE -ne 0) { throw 'Cloudflare secret registration failed.' }
    Write-RegistrationStatus 'registered'
    [System.Windows.Forms.MessageBox]::Show('토큰 등록이 완료됐습니다. 이 창을 닫아도 됩니다.', '등록 완료') | Out-Null
}
catch {
    Write-RegistrationStatus 'failed'
    if ('System.Windows.Forms.MessageBox' -as [type]) {
        [System.Windows.Forms.MessageBox]::Show('등록에 실패했습니다. 채팅에 실패 상태만 알려 주세요. 토큰은 보내지 마세요.', '등록 실패') | Out-Null
    }
}
finally {
    $taskPlainToken = $null
    if ($null -ne $taskDialog) { $taskDialog.Dispose() }
    Pop-Location
}
