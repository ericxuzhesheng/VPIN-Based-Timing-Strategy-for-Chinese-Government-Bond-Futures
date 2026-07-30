# Daily Sync — Pull latest updates from GitHub after daily cron completes
#
# GitHub Actions runs at ~17:00 CST. This script pulls updates and optionally
# re-runs the local VPIN pipeline to verify consistency.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/sync_from_github.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/sync_from_github.ps1 -DryRun

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $RepoRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VPIN Daily Sync from GitHub" -ForegroundColor Cyan
Write-Host "  日期: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] Would pull latest changes from origin/main" -ForegroundColor Yellow
    exit 0
}

# Step 1: Stash local changes (if any) to avoid conflicts
$localChanges = git status --porcelain
if ($localChanges) {
    Write-Host "[INFO] Stashing local changes before pull..." -ForegroundColor Yellow
    git stash push -m "auto-stash-before-daily-sync-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    $stashed = $true
} else {
    $stashed = $false
}

# Step 2: Pull latest from GitHub
Write-Host "[INFO] Pulling latest from origin/main..." -ForegroundColor Green
try {
    git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }
} catch {
    Write-Host "[ERROR] git pull failed: $_" -ForegroundColor Red
    if ($stashed) {
        Write-Host "[INFO] Restoring stashed changes..." -ForegroundColor Yellow
        git stash pop
    }
    exit 1
}

# Step 3: Restore local working changes
if ($stashed) {
    Write-Host "[INFO] Restoring previous local changes..." -ForegroundColor Yellow
    git stash pop 2>&1 | ForEach-Object { Write-Host "  $_" }
}

# Step 4: Show what changed
Write-Host ""
Write-Host "[INFO] Recent commits from today:" -ForegroundColor Green
$todayIso = (Get-Date).ToString("yyyy-MM-dd")
git log --since="$todayIso 00:00:00" --oneline --no-merges 2>&1 | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "[INFO] Files updated today:" -ForegroundColor Green
git diff --name-only HEAD@{1} HEAD 2>$null | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sync complete." -ForegroundColor Cyan
Write-Host "  最新数据已同步到本地，可直接使用。"
Write-Host "========================================" -ForegroundColor Cyan
