# Builds a release for the VERSION in pet.py:
#   dist\DesktopPet.exe      the app (what auto-update downloads)
#   dist\latest.json         version + SHA-256 the app checks against
#   dist\DesktopPetSetup.exe installer for new users
# Then upload all three to a GitHub release (link printed at the end).
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

"Built v$v. Upload dist\DesktopPet.exe, dist\latest.json and dist\DesktopPetSetup.exe here:"
"https://github.com/yuvancantcodeforshit/desktop-pet/releases/new?tag=v$v"
