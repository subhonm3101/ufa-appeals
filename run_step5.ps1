# Шаги 5.2 (анализ двух раундов, разметка в БД) и 5.3 (подбор весов, rules_v2) одним запуском.
# Запуск из корня проекта:   powershell -ExecutionPolicy Bypass -File .\run_step5.ps1
# Весь вывод пишется в data\step5_report.txt: отправь этот файл целиком.

Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$py   = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pyml = Join-Path $PSScriptRoot "ml\.venv\Scripts\python.exe"
$log  = Join-Path $PSScriptRoot "data\step5_report.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "data") | Out-Null
Set-Content -Path $log -Value ("Отчёт шага 5.2-5.3, " + (Get-Date -Format "yyyy-MM-dd HH:mm")) -Encoding UTF8

function Log($s) { Write-Host $s; Add-Content -Path $log -Value $s -Encoding UTF8 }

foreach ($p in @($py, $pyml)) {
    if (-not (Test-Path $p)) { Log "Не найден $p"; exit 1 }
}
foreach ($f in @("data\labeling\items_key.csv", "data\labeling\ratings.csv",
                 "data\labeling_r2\items_key.csv", "data\labeling_r2\ratings.csv", "data\appeals_synthetic.csv")) {
    if (-not (Test-Path (Join-Path $PSScriptRoot $f))) { Log "Нет файла $f"; exit 1 }
}

function Run($title, $exe, $argList, $workdir) {
    Log ""
    Log "##### $title #####"
    Push-Location $workdir
    & $exe @argList 2>&1 | ForEach-Object { Log "$_" }
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) {
        Log "ОШИБКА на шаге «$title» (код $code). Дальше не идём. Отправь файл $log"
        exit 1
    }
}

Run "1. Миграция 0005 (таблица expert_labels)" $py @("-m", "alembic", "upgrade", "head") (Join-Path $PSScriptRoot "backend")
Run "2. Выгрузка приоритета rules_v1" $py @("backend\scripts\export_priority_table.py") $PSScriptRoot
Run "3. Выгрузка состава кластеров" $py @("backend\scripts\export_cluster_members.py") $PSScriptRoot
Run "4. Анализ двух раундов разметки" $pyml @("ml\analyze_rounds.py") $PSScriptRoot
Run "5. Загрузка разметки в БД" $py @("backend\scripts\load_expert_labels.py") $PSScriptRoot
Run "6. Подбор весов и сравнение моделей" $pyml @("ml\fit_priority_weights.py") $PSScriptRoot
Run "7. Расчёт приоритета rules_v2 и запись в БД" $py @("backend\scripts\run_priority.py", "--weights", "data\priority_weights_v2.json", "--save") $PSScriptRoot

Log ""
Log "##### 8. Проверка БД #####"
& docker exec ufa-appeals-db psql -U appeals -d appeals -c "SELECT method, as_of, count(*) FROM priority_scores GROUP BY 1,2 ORDER BY 1;" 2>&1 | ForEach-Object { Log "$_" }
& docker exec ufa-appeals-db psql -U appeals -d appeals -c "SELECT count(*) AS labels, count(r2) AS with_round2, min(rating), max(rating) FROM expert_labels;" 2>&1 | ForEach-Object { Log "$_" }

Log ""
Log "Готово. Отправь мне файл data\step5_report.txt"

