# タイトル付きウィンドウを持つプロセス一覧を表示する（ChatGPT等の対象ウィンドウ確認用）
Get-Process | Where-Object { $_.MainWindowTitle -ne "" } | Select-Object Id, ProcessName, MainWindowTitle
