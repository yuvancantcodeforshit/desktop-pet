# Builds a release for the VERSION in pet.py:
#   dist\DesktopPet.exe      the app (what auto-update downloads)
#   dist\latest.json         version + SHA-256 the app checks against
#   dist\DesktopPetSetup.exe installer for new users
# Then publishes all three as GitHub release v<VERSION> (needs GitHub CLI, signed in once with `gh auth login`).
Set-Location $PSScriptRoot
$v = [regex]::Match((Get-Content pet.py -Raw), "VERSION = '([\d.]+)'").Groups[1].Value
if (-not $v) { throw 'VERSION not found in pet.py' }

python pet.py --selftest
if ($LASTEXITCODE) { throw 'selftest failed' }

$w = "$env:TEMP\petbuild"
python -m PyInstaller --onefile --noconsole --name DesktopPet --distpath dist --workpath $w --specpath $w --log-level ERROR pet.py
if ($LASTEXITCODE) { throw 'building DesktopPet.exe failed' }

$hash = (Get-FileHash dist\DesktopPet.exe -Algorithm SHA256).Hash.ToLower()
@{ version = $v; sha256 = $hash } | ConvertTo-Json | Set-Content dist\latest.json -Encoding ascii

python -m PyInstaller --onefile --noconsole --name DesktopPetSetup --distpath dist --workpath $w --specpath $w --log-level ERROR `
    --add-data "$PWD\dist\DesktopPet.exe;." --add-data "$PWD\install.cmd;." --add-data "$PWD\uninstall.cmd;." installer.py
if ($LASTEXITCODE) { throw 'building DesktopPetSetup.exe failed' }

$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = "$env:ProgramFiles\GitHub CLI\gh.exe" }
& $gh release create "v$v" dist\DesktopPet.exe dist\latest.json dist\DesktopPetSetup.exe `
    --repo yuvancantcodeforshit/desktop-pet --target (git branch --show-current) --title "v$v" --generate-notes
if ($LASTEXITCODE) { throw 'gh release create failed (run "gh auth login" once?)' }
"Published v$v. Running apps update within a minute of their next start."
