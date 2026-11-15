<#
Резервная копия рабочей сборки: база данных и фотографии обращений.
Запуск из корня проекта:  .\deploy\backup.ps1            (папка backups\, хранится 14 последних копий)
                          .\deploy\backup.ps1 -OutDir D:\copies -Keep 30
#>
param(
    [string]$OutDir = "backups",
    [int]$Keep = 14
)
$ErrorActionPreference = "Stop"

function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "Не удалось: $what (код $LASTEXITCODE)" }
}

$compose = @("compose", "-f", "docker-compose.prod.yml", "--env-file", ".env.prod")
New-Item -ItemType Directory -Force $OutDir | Out-Null
$abs = (Resolve-Path $OutDir).Path
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dump = "appeals-$stamp.dump"
$photos = "uploads-$stamp.tar.gz"

# База: дамп делается внутри контейнера и сразу проверяется на читаемость
docker @compose exec -T db sh -c "pg_dump -U appeals -d appeals -Fc -f /tmp/appeals.dump && pg_restore --list /tmp/appeals.dump > /dev/null"
Check "создать дамп базы"
docker @compose cp db:/tmp/appeals.dump "$abs\$dump"
Check "скопировать дамп"
docker @compose exec -T db rm -f /tmp/appeals.dump

# Фотографии обращений (отдельный том, в дамп базы они не входят)
docker run --rm -v ufa-appeals-prod_uploads_prod:/data:ro -v "${abs}:/out" alpine tar czf "/out/$photos" -C /data .
Check "архивировать фотографии"

# Хранятся только последние $Keep копий каждого вида
foreach ($pattern in @("appeals-*.dump", "uploads-*.tar.gz")) {
    Get-ChildItem $abs -Filter $pattern | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep | Remove-Item
}

$size = "{0:N1} МБ" -f ((Get-Item "$abs\$dump").Length / 1MB)
Write-Host "Готово: $abs\$dump ($size) и $abs\$photos"
