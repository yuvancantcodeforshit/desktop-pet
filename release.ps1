# One-command release:   .\release.ps1 1.0.1
#   1. runs the selftest
#   2. sets VERSION in pet.py
#   3. builds dist\DesktopPet.exe (what auto-update downloads), dist\latest.json (version + SHA-256),
#      dist\DesktopPetSetup.exe (installer for new users)
#   4. commits everything as "Release v1.0.1" and pushes main
#   5. publishes GitHub release v1.0.1 (needs GitHub CLI, signed in once with `gh auth login`)
param([Parameter(Mandatory)][string]$Version)
Set-Location $PSScriptRoot

if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Version must look like 1.0.1' }
$src = [IO.File]::ReadAllText("$PWD\pet.py")
$old = [regex]::Match($src, "VERSION = '([\d.]+)'").Groups[1].Value
if (-not $old) { throw 'VERSION not found in pet.py' }
# Same version allowed: lets you re-run after a failed push; gh refuses a duplicate release anyway.
if ([version]$Version -lt [version]$old) { throw "Version must not be lower than the current $old" }
if ((git branch --show-current) -ne 'main') { throw 'Switch to main first: git switch main' }

python pet.py --selftest
if ($LASTEXITCODE) { throw 'selftest failed' }

[IO.File]::WriteAllText("$PWD\pet.py", ($src -replace "VERSION = '[\d.]+'", "VERSION = '$Version'"))

$w = "$env:TEMP\petbuild"
python -m PyInstaller --onefile --noconsole --name DesktopPet --distpath dist --workpath $w --specpath $w --log-level ERROR pet.py
if ($LASTEXITCODE) { throw 'building DesktopPet.exe failed' }
# Test the packed exe too: a broken build would ship to every pet and could never update itself again.
if ((Start-Process dist\DesktopPet.exe -ArgumentList '--selftest' -Wait -PassThru).ExitCode) { throw 'built DesktopPet.exe failed its selftest' }

$hash = (Get-FileHash dist\DesktopPet.exe -Algorithm SHA256).Hash.ToLower()
@{ version = $Version; sha256 = $hash } | ConvertTo-Json | Set-Content dist\latest.json -Encoding ascii

python -m PyInstaller --onefile --noconsole --name DesktopPetSetup --distpath dist --workpath $w --specpath $w --log-level ERROR `
    --add-data "$PWD\dist\DesktopPet.exe;." --add-data "$PWD\install.cmd;." --add-data "$PWD\uninstall.cmd;." installer.py
if ($LASTEXITCODE) { throw 'building DesktopPetSetup.exe failed' }

git add -A
git commit -q -m "Release v$Version"
git push -q
if ($LASTEXITCODE) { throw 'git push failed' }

$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = "$env:ProgramFiles\GitHub CLI\gh.exe" }
& $gh release create "v$Version" dist\DesktopPet.exe dist\latest.json dist\DesktopPetSetup.exe `
    --repo yuvancantcodeforshit/desktop-pet --target main --title "v$Version" --generate-notes
if ($LASTEXITCODE) { throw 'gh release create failed (run "gh auth login" once?)' }
"Published v$Version. Installed pets update within a minute of their next start."
