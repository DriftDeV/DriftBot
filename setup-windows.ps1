# DriftBot - Windows Setup Script
# Installs the system dependencies (Chocolatey, Visual C++ build tools, Python 3.10, FFmpeg, Make, Git),
# creates a virtual environment and installs the bot with `make install`.
# Requires administrator privileges.
#
#   .\setup-windows.ps1              standard install (GPU auto-detected: NVIDIA CUDA, otherwise CPU)
#   .\setup-windows.ps1 -Dev         also install the development tools
#   .\setup-windows.ps1 -Gpu cpu     force CPU (or -Gpu cuda). AMD ROCm is Linux only.
#   .\setup-windows.ps1 -SkipPython -SkipFFmpeg

param(
    [switch]$SkipPython = $false,
    [switch]$SkipFFmpeg = $false,
    [switch]$Dev = $false,
    [ValidateSet("auto", "cuda", "cpu")]
    [string]$Gpu = "auto"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "     DriftBot - Windows Setup Script                           " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Function to check if command exists
function Test-CommandExists {
    param($Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

# Function to check if running as admin
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Check admin privileges
if (-not (Test-Administrator)) {
    Write-Host "[WARNING] This script requires administrator privileges." -ForegroundColor Yellow
    Write-Host "Please run PowerShell as Administrator and try again." -ForegroundColor Yellow
    exit 1
}

# Install Chocolatey if not present
function Install-Chocolatey {
    if (Test-CommandExists choco) {
        Write-Host "[OK] Chocolatey is already installed" -ForegroundColor Green
        return
    }

    Write-Host "[INSTALL] Installing Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Write-Host "[OK] Chocolatey installed successfully" -ForegroundColor Green
}

# Install the Visual C++ build tools (needed to compile some Python packages)
function Install-VisualCpp {
    Write-Host "[INSTALL] Installing Visual C++ build tools..." -ForegroundColor Yellow
    choco install visualcpp-build-tools -y
    Write-Host "[OK] Visual C++ build tools installed" -ForegroundColor Green
}

# Install Python 3.10 (the version the project targets: fairseq, used by RVC, does not support newer ones)
function Install-Python {
    if ($SkipPython) {
        Write-Host "[SKIP] Skipping Python installation" -ForegroundColor Cyan
        return
    }

    if (Test-CommandExists python) {
        $version = python --version 2>&1
        Write-Host "[OK] Python is already installed: $version" -ForegroundColor Green
        if ("$version" -notmatch "Python 3\.10\.") {
            Write-Host "[WARNING] The project targets Python 3.10: with another version the AI packages (fairseq/RVC) may fail to install." -ForegroundColor Yellow
        }
        return
    }

    Write-Host "[INSTALL] Installing Python 3.10..." -ForegroundColor Yellow
    choco install python310 -y --params="/InstallDir:C:\Python310"
    Write-Host "[OK] Python 3.10 installed successfully" -ForegroundColor Green

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# Install FFmpeg
function Install-FFmpeg {
    if ($SkipFFmpeg) {
        Write-Host "[SKIP] Skipping FFmpeg installation" -ForegroundColor Cyan
        return
    }

    if (Test-CommandExists ffmpeg) {
        Write-Host "[OK] FFmpeg is already installed" -ForegroundColor Green
        return
    }

    Write-Host "[INSTALL] Installing FFmpeg..." -ForegroundColor Yellow
    choco install ffmpeg -y
    Write-Host "[OK] FFmpeg installed successfully" -ForegroundColor Green

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# Install Make (via Chocolatey)
function Install-Make {
    if (Test-CommandExists make) {
        Write-Host "[OK] Make is already installed" -ForegroundColor Green
        return
    }

    Write-Host "[INSTALL] Installing Make..." -ForegroundColor Yellow
    choco install make -y
    Write-Host "[OK] Make installed successfully" -ForegroundColor Green

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# Install Git (if needed)
function Install-Git {
    if (Test-CommandExists git) {
        Write-Host "[OK] Git is already installed" -ForegroundColor Green
        return
    }

    Write-Host "[INSTALL] Installing Git..." -ForegroundColor Yellow
    choco install git -y
    Write-Host "[OK] Git installed successfully" -ForegroundColor Green

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# Main installation sequence
try {
    Write-Host "Step 1: Installing system dependencies..." -ForegroundColor Cyan
    Write-Host ""

    Install-Chocolatey
    Install-VisualCpp
    Install-Python
    Install-FFmpeg
    Install-Make
    Install-Git

    Write-Host ""
    Write-Host "Step 2: Creating Python virtual environment..." -ForegroundColor Cyan
    Write-Host ""

    Set-Location $ScriptDir

    # Create and activate venv
    python -m venv venv
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green

    Write-Host ""
    Write-Host "Step 3: Installing Python packages..." -ForegroundColor Cyan
    Write-Host ""

    # Activate venv
    & ".\venv\Scripts\Activate.ps1"

    # Upgrade pip
    python -m pip install --upgrade pip setuptools wheel

    # Install dependencies
    if ($Dev) {
        Write-Host "[INSTALL] Installing development dependencies (GPU: $Gpu)..." -ForegroundColor Yellow
        make install-dev "GPU=$Gpu"
    }
    else {
        Write-Host "[INSTALL] Installing production dependencies (GPU: $Gpu)..." -ForegroundColor Yellow
        make install "GPU=$Gpu"
    }

    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "           Setup completed successfully!                        " -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host ""

    Write-Host "Configuration steps:" -ForegroundColor Cyan
    Write-Host "  1. Create a .env file with your Discord token:"
    Write-Host "     DISCORD_TOKEN=your_token_here"
    Write-Host ""
    Write-Host "To run the bot:" -ForegroundColor Cyan
    Write-Host "  Option 1: Using Make"
    Write-Host "    make run"
    Write-Host ""
    Write-Host "  Option 2: Direct Python"
    Write-Host "    .\venv\Scripts\Activate.ps1"
    Write-Host "    python src/main.py"
    Write-Host ""

    Write-Host "Available Make commands:" -ForegroundColor Cyan
    Write-Host "  make help          - Show all available commands"
    Write-Host "  make lint          - Run code linting"
    Write-Host "  make test-py       - Check that PyTorch sees your GPU"
    Write-Host "  make test          - Run the test suite"
    Write-Host "  make format        - Format code with Black"
    Write-Host "  make type-check    - Run type checking"
    Write-Host "  make pre-commit    - Format + lint + type-check"
    Write-Host ""

}
catch {
    Write-Host ""
    Write-Host "[ERROR] Setup failed!" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}
