# kohaku-sns-video v0：Windows 標準の日本語の音声認識（手元。外へ送らない）で WAV を文字に起こす（聞き取りの目安）
# 使い方：powershell -NoProfile -File asr_win.ps1 <WAVのフォルダ> <出力の.tsv>
param([string]$Dir, [string]$Out)
Add-Type -AssemblyName System.Speech
$culture = New-Object System.Globalization.CultureInfo("ja-JP")
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("file`ttext`tconfidence")
Get-ChildItem -Path $Dir -Filter *.wav | Sort-Object Name | ForEach-Object {
    $eng = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
    $eng.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $eng.SetInputToWaveFile($_.FullName)
    $eng.InitialSilenceTimeout = [TimeSpan]::FromSeconds(5)
    $eng.EndSilenceTimeout = [TimeSpan]::FromSeconds(1.2)
    $texts = @(); $confs = @()
    while ($true) {
        try { $r = $eng.Recognize() } catch { break }
        if ($null -eq $r) { break }
        $texts += $r.Text; $confs += $r.Confidence
    }
    $eng.Dispose()
    $avg = 0; if ($confs.Count -gt 0) { $avg = [math]::Round((($confs | Measure-Object -Average).Average), 2) }
    $lines.Add($_.Name + "`t" + ($texts -join " ") + "`t" + $avg)
}
[System.IO.File]::WriteAllLines($Out, $lines, (New-Object System.Text.UTF8Encoding($false)))
