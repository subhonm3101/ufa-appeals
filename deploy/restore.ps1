<#
Восстановление из резервной копии.
По умолчанию копия разворачивается в ОТДЕЛЬНУЮ проверочную базу appeals_check: рабочая база не затрагивается.
  .\deploy\restore.ps1 -Dump backups\appeals-20261115-180000.dump
Восстановление в рабочую базу (останавливает бэкенд, заменяет данные, запускает бэкенд):
  .\deploy\restore.ps1 -Dump backups\appeals-....dump -Uploads backups\uploads-....tar.gz -Database appeals -Force
#>
param(
    [Parameter(Mandatory = $true)][string]$Dump,
    [string]$Uploads = "",
    [string]$Database = "appeals_check",
    [switch]$Force
)
$ErrorActionPreference = "Stop"

function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "Не удалось: $what (код $LASTEXITCODE)" }
}

$compose = @("compose", "-f", "docker-compose.prod.yml", "--env-file", ".env.prod")
$live = ($Database -eq "appeals")
if ($live -and -not $Force) { throw "Восстановление в рабочую базу требует ключа -Force" }
if (-not (Test-Path $Dump)) { throw "Файл не найден: $Dump" }

if ($live) { docker @compose stop backend; Check "остановить бэкенд" }

docker @compose cp (Resolve-Path $Dump).Path db:/tmp/restore.dump
Check "скопировать дамп в контейнер"
# в рабочем случае базу пересоздаём из служебной базы postgres
docker @compose exec -T db psql -U appeals -d postgres -c "DROP DATABASE IF EXISTS $Database WITH (FORCE)" -c "CREATE DATABASE $Database"
Check "создать базу $Database"
docker @compose exec -T db pg_restore -U appeals -d $Database --no-owner /tmp/restore.dump
Check "восстановить данные"
docker @compose exec -T db rm -f /tmp/restore.dump

if ($Uploads -ne "") {
    $up = Resolve-Path $Uploads
    $dir = Split-Path $up.Path
    $name = Split-Path $up.Path -Leaf
    $target = if ($live) { "ufa-appeals-prod_uploads_prod" } else { "ufa-appeals-prod_uploads_check" }
    docker run --rm -v "${target}:/data" -v "${dir}:/in:ro" alpine sh -c "rm -rf /data/* && tar xzf /in/$name -C /data"
    Check "распаковать фотографии"
}

if ($live) { docker @compose start backend; Check "запустить бэкенд" }

docker @compose exec -T db psql -U appeals -d $Database -c "SELECT (SELECT count(*) FROM appeals) AS appeals, (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM categories) AS categories"
Write-Host "Восстановление в базу $Database выполнено."
