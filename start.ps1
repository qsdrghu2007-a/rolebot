Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Telegram 聊天机器人 — 启动脚本" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

try { python --version 2>&1 | Out-Null } catch {
    Write-Host "[错误] 未找到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host "检查依赖..." -ForegroundColor Yellow
$deps = python -c "import telegram, requests, yaml, tenacity, colorama" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[提示] 缺少依赖，运行: pip install -r requirements.txt" -ForegroundColor Yellow
}

if (-not (Test-Path "config.yaml")) {
    Write-Host "[提示] 未找到 config.yaml，启动配置引导..." -ForegroundColor Yellow
    python setup.py
    if ($LASTEXITCODE -ne 0) {
        Read-Host "按回车退出"
        exit 1
    }
}

Write-Host "启动中..." -ForegroundColor Green
python main.py
Read-Host "按回车退出"
