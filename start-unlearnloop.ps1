[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$backendPort = 18000
$frontendPort = 15173
$backendUrl = "http://127.0.0.1:$backendPort"
$frontendUrl = "http://127.0.0.1:$frontendPort/"
$runRoot = Join-Path $env:LOCALAPPDATA 'UnlearnLoop\run'
$logRoot = Join-Path $env:LOCALAPPDATA 'UnlearnLoop\logs'
$statePath = Join-Path $runRoot 'stage5c-integration.json'
$launchState = $null
$newlyStartedBackendPid = 0
$newlyStartedFrontendPid = 0

New-Item -ItemType Directory -Force -Path $runRoot, $logRoot | Out-Null

function Get-ProcessDetails([int]$ProcessId) {
    Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-ManagedProcess($Process, [string]$Kind, $State) {
    if (-not $Process -or -not $State) { return $false }
    if ($Kind -eq 'backend') {
        if ($Process.ProcessId -eq $State.backend_launcher_pid) {
            return ($Process.ExecutablePath -eq $State.backend_executable -and
                $Process.CommandLine -match 'uvicorn app\.main:app' -and
                $Process.CommandLine -match '--port 18000')
        }
        if ($Process.ProcessId -ne $State.backend_pid) { return $false }
        if ($Process.CommandLine -notmatch 'uvicorn app\.main:app' -or $Process.CommandLine -notmatch '--port 18000') { return $false }
        if ($Process.ExecutablePath -eq $State.backend_executable) { return $true }
        $parentId = [int]$Process.ParentProcessId
        for ($depth = 0; $depth -lt 8 -and $parentId -gt 0; $depth++) {
            if ($parentId -eq [int]$State.backend_launcher_pid) { return $true }
            $parent = Get-ProcessDetails $parentId
            if (-not $parent) { break }
            $parentId = [int]$parent.ParentProcessId
        }
        return $false
    }
    if ($Process.ProcessId -eq $State.frontend_launcher_pid) {
        return ($Process.ExecutablePath -eq $State.frontend_executable -and
            $Process.CommandLine -match 'node_modules[\\/]vite[\\/]bin[\\/]vite\.js' -and
            $Process.CommandLine -match '--port 15173')
    }
    if ($Process.ProcessId -ne $State.frontend_pid) { return $false }
    if ($Process.CommandLine -notmatch 'node_modules[\\/]vite[\\/]bin[\\/]vite\.js' -or $Process.CommandLine -notmatch '--port 15173') { return $false }
    if ($Process.ExecutablePath -eq $State.frontend_executable) { return $true }
    $parentId = [int]$Process.ParentProcessId
    for ($depth = 0; $depth -lt 8 -and $parentId -gt 0; $depth++) {
        if ($parentId -eq [int]$State.frontend_launcher_pid) { return $true }
        $parent = Get-ProcessDetails $parentId
        if (-not $parent) { break }
        $parentId = [int]$parent.ParentProcessId
    }
    return $false
}

function Stop-VerifiedProcess([int]$ProcessId, [string]$Kind, $State) {
    if (-not $ProcessId) { return }
    $process = Get-ProcessDetails $ProcessId
    if (-not $process) { return }
    if (-not (Test-ManagedProcess $process $Kind $State)) {
        Write-Warning "未停止 PID $ProcessId：进程信息与 UnlearnLoop 启动记录不匹配。"
        return
    }
    Stop-Process -Id $ProcessId -Force
    Write-Host "已停止本脚本启动的 $Kind 进程（PID $ProcessId）。"
}

if ($Stop) {
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Host '没有找到本脚本保存的服务进程记录；没有停止任何进程。'
        exit 0
    }
    $savedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Stop-VerifiedProcess ([int]$savedState.frontend_pid) 'frontend' $savedState
    if ($savedState.frontend_launcher_pid -and $savedState.frontend_launcher_pid -ne $savedState.frontend_pid) {
        Stop-VerifiedProcess ([int]$savedState.frontend_launcher_pid) 'frontend' $savedState
    }
    Stop-VerifiedProcess ([int]$savedState.backend_pid) 'backend' $savedState
    if ($savedState.backend_launcher_pid -and $savedState.backend_launcher_pid -ne $savedState.backend_pid) {
        Stop-VerifiedProcess ([int]$savedState.backend_launcher_pid) 'backend' $savedState
    }
    Remove-Item -LiteralPath $statePath -Force
    Write-Host 'UnlearnLoop 启动记录已清除。数据库和日志均已保留。'
    exit 0
}

function Get-ListenerProcesses([int]$Port) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        Get-ProcessDetails ([int]$listener.OwningProcess)
    }
}

function Resolve-PythonExecutable {
    $candidates = @(
        (Join-Path $backendRoot '.venv\Scripts\python.exe'),
        'D:\Temp\unlearnloop-stage5c2-final-venv\Scripts\python.exe'
    )
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython) { $candidates += $systemPython.Source }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        & $candidate -c 'import alembic, fastapi, pydantic_settings, sqlalchemy, uvicorn' 2>$null
        if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw "未找到含 FastAPI、SQLAlchemy、Alembic 和 Uvicorn 的 Python 环境。请先按 backend/requirements.txt 配置 Python 环境。"
}

function Invoke-DirectHttp([string]$Url, [string]$Origin = '') {
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        if ($Origin) { $null = $client.DefaultRequestHeaders.TryAddWithoutValidation('Origin', $Origin) }
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $allowOrigin = $null
        if ($response.Headers.Contains('Access-Control-Allow-Origin')) {
            $allowOrigin = ($response.Headers.GetValues('Access-Control-Allow-Origin') | Select-Object -First 1)
        }
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Body = $body
            AllowOrigin = $allowOrigin
        }
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

try {
    if (-not (Test-Path -LiteralPath $backendRoot)) { throw "未找到后端目录：$backendRoot" }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'))) {
        throw '前端依赖未安装。请先在 frontend 目录运行 npm ci。'
    }
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm) { throw '未找到 Node.js 或 npm，请先安装项目所需的 Node.js。' }
    & $node.Source --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 无法正常运行。' }
    & $npm.Source --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'npm 无法正常运行。' }
    $vitePath = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
    & $node.Source $vitePath --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '项目中的 Vite 无法正常运行。' }
    $python = Resolve-PythonExecutable

    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } catch { $state = $null }
    }

    $backendListeners = @(Get-ListenerProcesses $backendPort)
    $frontendListeners = @(Get-ListenerProcesses $frontendPort)
    $backendProcess = $null
    $frontendProcess = $null
    if ($backendListeners.Count -gt 0) {
        if ($backendListeners.Count -ne 1 -or -not (Test-ManagedProcess $backendListeners[0] 'backend' $state)) {
            $owner = $backendListeners[0]
            throw "端口 $backendPort 已由其他或无法确认的进程占用（PID $($owner.ProcessId)，$($owner.Name)）。未停止该进程。"
        }
        $backendProcess = $backendListeners[0]
    }
    if ($frontendListeners.Count -gt 0) {
        if ($frontendListeners.Count -ne 1 -or -not (Test-ManagedProcess $frontendListeners[0] 'frontend' $state)) {
            $owner = $frontendListeners[0]
            throw "端口 $frontendPort 已由其他或无法确认的进程占用（PID $($owner.ProcessId)，$($owner.Name)）。未停止该进程。"
        }
        $frontendProcess = $frontendListeners[0]
    }

    $newBackendPid = if ($backendProcess) { [int]$backendProcess.ProcessId } else { 0 }
    $newFrontendPid = if ($frontendProcess) { [int]$frontendProcess.ProcessId } else { 0 }
    $backendExecutable = if ($backendProcess) { $backendProcess.ExecutablePath } else { $python }
    $frontendExecutable = if ($frontendProcess) { $frontendProcess.ExecutablePath } else { (Resolve-Path -LiteralPath $node.Source).Path }
    $launchState = [pscustomobject]@{
        backend_pid = $newBackendPid
        backend_launcher_pid = if ($backendProcess) { [int]$backendProcess.ProcessId } elseif ($state) { [int]$state.backend_launcher_pid } else { 0 }
        backend_executable = $backendExecutable
        frontend_pid = $newFrontendPid
        frontend_launcher_pid = if ($frontendProcess) { [int]$frontendProcess.ProcessId } elseif ($state) { [int]$state.frontend_launcher_pid } else { 0 }
        frontend_executable = $frontendExecutable
    }

    if (-not $backendProcess) {
        $env:APP_ENV = 'development'
        $env:BACKEND_HOST = '127.0.0.1'
        $env:BACKEND_PORT = "$backendPort"
        $env:CORS_ORIGINS = "http://127.0.0.1:$frontendPort,http://localhost:$frontendPort"
        $env:MODEL_PROVIDER = 'fake'
        $env:MODEL_API_KEY = ''
        $env:ALLOW_REMOTE_MODEL_CALLS = 'false'
        $env:VITE_API_BASE_URL = $backendUrl

        $backendOut = Join-Path $logRoot 'backend.stdout.log'
        $backendErr = Join-Path $logRoot 'backend.stderr.log'
        $process = Start-Process -FilePath $python -ArgumentList @(
            '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$backendPort"
        ) -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
        $launchState.backend_pid = $process.Id
        $launchState.backend_launcher_pid = $process.Id
        $newBackendPid = $process.Id
        $newlyStartedBackendPid = $process.Id
        $launchState | ConvertTo-Json | Set-Content -LiteralPath $statePath
    }

    if (-not $frontendProcess) {
        $env:VITE_API_BASE_URL = $backendUrl
        $viteOut = Join-Path $logRoot 'vite.stdout.log'
        $viteErr = Join-Path $logRoot 'vite.stderr.log'
        $process = Start-Process -FilePath $node.Source -ArgumentList @(
            $vitePath, '--host', '127.0.0.1', '--port', "$frontendPort", '--strictPort'
        ) -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $viteOut -RedirectStandardError $viteErr
        $launchState.frontend_pid = $process.Id
        $launchState.frontend_launcher_pid = $process.Id
        $newFrontendPid = $process.Id
        $newlyStartedFrontendPid = $process.Id
        $launchState | ConvertTo-Json | Set-Content -LiteralPath $statePath
    }

    $deadline = (Get-Date).AddSeconds(45)
    $backendReady = $false
    $frontendReady = $false
    $proxyReady = $false
    while ((Get-Date) -lt $deadline -and (-not $backendReady -or -not $frontendReady -or -not $proxyReady)) {
        try {
            $health = Invoke-DirectHttp "$backendUrl/api/v1/health" "http://127.0.0.1:$frontendPort"
            if ($health.StatusCode -eq 200 -and ($health.Body | ConvertFrom-Json).status -eq 'ok') {
                if ($health.AllowOrigin -ne "http://127.0.0.1:$frontendPort") {
                    throw '后端健康检查成功，但 CORS 未允许前端来源。'
                }
                $backendReady = $true
            }
        } catch { }

        try {
            $homeResponse = Invoke-DirectHttp $frontendUrl
            if ($homeResponse.StatusCode -eq 200 -and $homeResponse.Body -match 'id="root"') { $frontendReady = $true }
        } catch { }

        try {
            $proxyUrl = "$($frontendUrl.TrimEnd('/'))/api/v1/health"
            $proxy = Invoke-DirectHttp $proxyUrl
            if ($proxy.StatusCode -eq 200 -and ($proxy.Body | ConvertFrom-Json).status -eq 'ok') {
                $proxyReady = $true
            }
        } catch { }

        if (-not $backendReady -or -not $frontendReady -or -not $proxyReady) {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $backendReady -or -not $frontendReady -or -not $proxyReady) {
        $backendError = Join-Path $logRoot 'backend.stderr.log'
        $viteError = Join-Path $logRoot 'vite.stderr.log'
        Write-Host "后端 stderr：$backendError"
        Write-Host "前端 stderr：$viteError"
        if (Test-Path -LiteralPath $backendError) { Get-Content -LiteralPath $backendError -Tail 30 }
        if (Test-Path -LiteralPath $viteError) { Get-Content -LiteralPath $viteError -Tail 30 }
        throw "启动检查失败（backend=$backendReady, homepage=$frontendReady, vite_api_proxy=$proxyReady）。"
    }

    $backendListener = @(Get-ListenerProcesses $backendPort | Select-Object -First 1)
    $frontendListener = @(Get-ListenerProcesses $frontendPort | Select-Object -First 1)
    if ($backendListener.Count -ne 1 -or $frontendListener.Count -ne 1) {
        throw 'HTTP 检查成功，但无法确认固定端口的监听进程。'
    }
    $launchState.backend_pid = [int]$backendListener[0].ProcessId
    $launchState.frontend_pid = [int]$frontendListener[0].ProcessId
    $launchState | ConvertTo-Json | Set-Content -LiteralPath $statePath
    Write-Host 'UnlearnLoop 已启动并通过本机 HTTP 检查。'
    Write-Host '模型：FakeModelProvider（不发起远程模型请求）'
    Write-Host '数据库：沿用 backend/.env、项目 .env 或 DATABASE_URL；未设置时使用 backend/unlearnloop.db。启动不会清空已有数据。'
    Write-Host "后端健康检查：$backendUrl/api/v1/health"
    Write-Host "Vite /api 代理健康检查：$($frontendUrl.TrimEnd('/'))/api/v1/health"
    Write-Host "网站地址：$frontendUrl"
    Write-Host "停止服务：& '$($MyInvocation.MyCommand.Path)' -Stop"
    if (-not $NoBrowser) { Start-Process $frontendUrl }
} catch {
    if ($launchState) {
        if ($newlyStartedFrontendPid) {
            $frontendOwners = @(Get-ListenerProcesses $frontendPort)
            foreach ($owner in $frontendOwners) { Stop-VerifiedProcess ([int]$owner.ProcessId) 'frontend' $launchState }
            Stop-VerifiedProcess $newlyStartedFrontendPid 'frontend' $launchState
            $launchState.frontend_pid = 0
            $launchState.frontend_launcher_pid = 0
        }
        if ($newlyStartedBackendPid) {
            $backendOwners = @(Get-ListenerProcesses $backendPort)
            foreach ($owner in $backendOwners) { Stop-VerifiedProcess ([int]$owner.ProcessId) 'backend' $launchState }
            Stop-VerifiedProcess $newlyStartedBackendPid 'backend' $launchState
            $launchState.backend_pid = 0
            $launchState.backend_launcher_pid = 0
        }
        if ($launchState.backend_pid -or $launchState.frontend_pid) {
            $launchState | ConvertTo-Json | Set-Content -LiteralPath $statePath
        } elseif (Test-Path -LiteralPath $statePath) {
            Remove-Item -LiteralPath $statePath -Force
        }
    }
    Write-Host "启动失败：$_" -ForegroundColor Red
    Write-Host "诊断日志目录：$logRoot"
    exit 1
}
