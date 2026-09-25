$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
}

$Python = Join-Path $Root '.venv\Scripts\python.exe'
& $Python -m pip install --disable-pip-version-check -r requirements.txt
& $Python -m compileall -q main.py win_assistants sedentary tests
& $Python -m unittest discover -s tests -v
& $Python -c "import tkinter as tk; root = tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy(); print('Tk runtime ready')"
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name win-assistants `
    --collect-submodules pystray `
    --collect-data cv2 `
    --hidden-import PIL.Image `
    --hidden-import PIL.ImageDraw `
    main.py

Write-Host ''
Write-Host 'Build completed:' -ForegroundColor Green
Write-Host (Join-Path $Root 'dist\win-assistants.exe')
