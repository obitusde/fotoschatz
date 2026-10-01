# Fotoschatz - neue Skripte von GitHub holen (wird von aktualisieren.bat gestartet)
#
# Holt alle Skripte aus dem Ordner sync/ des Repos obitusde/fotoschatz (Stand: main) in den Ordner,
# in dem dieses Skript liegt (D:\Fotoschatz\_sync). Erst wird alles in einen Temp-Ordner geladen -
# nur wenn ALLES geklappt hat, werden die Dateien ersetzt. Eigene Dateien (config.local.json, work\,
# google\, gpx\, katalog\ ...) werden nie angefasst, ebenso nichts unter D:\Bilder - Raw.
# aktualisieren.bat selbst wird nicht ersetzt (Windows liest eine laufende .bat Zeile fuer Zeile).
# Version 0.6.23

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = "obitusde/fotoschatz"
$ziel = $PSScriptRoot
$headers = @{ "User-Agent" = "fotoschatz-aktualisieren" }
$muster = '\.(py|bat|ps1)$|^config\.example\.json$'

Write-Host "Fotoschatz - Skripte aktualisieren"
Write-Host "Ziel: $ziel"
Write-Host ""

if ($ziel -like "*\Bilder - Raw*") {
    Write-Host "FEHLER: Das Skript liegt im Originalordner - dort wird nichts geschrieben. Abbruch."
    exit 1
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("fotoschatz-update-" + [guid]::NewGuid().ToString("N"))
try {
    # Stand von main festhalten (Commit), damit alle Dateien zusammenpassen und kein alter Zwischenspeicher stoert
    $sha = (Invoke-RestMethod "https://api.github.com/repos/$repo/commits/main" -Headers $headers).sha
    $raw = "https://raw.githubusercontent.com/$repo/$sha"
    $version = ([string](Invoke-WebRequest "$raw/VERSION" -UseBasicParsing -Headers $headers).Content).Trim()
    $liste = Invoke-RestMethod "https://api.github.com/repos/$repo/contents/sync?ref=$sha" -Headers $headers
    $dateien = @($liste | Where-Object { $_.type -eq "file" -and $_.name -match $muster -and $_.name -ne "aktualisieren.bat" } |
                 Sort-Object name)
    if ($dateien.Count -eq 0) { throw "Im Repo wurden keine Skripte gefunden." }

    Write-Host "Stand im Repo: Version $version ($($dateien.Count) Dateien)"
    New-Item -ItemType Directory -Path $tmp | Out-Null
    foreach ($d in $dateien) {
        Invoke-WebRequest "$raw/sync/$($d.name)" -OutFile (Join-Path $tmp $d.name) -UseBasicParsing -Headers $headers
    }

    # Alles geladen -> erst jetzt ersetzen
    $neu = 0; $geaendert = 0; $gleich = 0
    foreach ($d in $dateien) {
        $quelle = Join-Path $tmp $d.name
        $datei = Join-Path $ziel $d.name
        if (-not (Test-Path $datei)) {
            Copy-Item $quelle $datei
            Write-Host "  neu:          $($d.name)"
            $neu++
        } elseif ((Get-FileHash $quelle).Hash -ne (Get-FileHash $datei).Hash) {
            Copy-Item $quelle $datei -Force
            Write-Host "  aktualisiert: $($d.name)"
            $geaendert++
        } else {
            $gleich++
        }
    }
    Write-Host ""
    Write-Host "Fertig: $neu neu, $geaendert aktualisiert, $gleich unveraendert - jetzt auf Version $version."
}
catch {
    Write-Host ""
    Write-Host "FEHLER: $($_.Exception.Message)"
    Write-Host "Es wurde nichts ersetzt. Internetverbindung pruefen und nochmal starten."
    exit 1
}
finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
}
