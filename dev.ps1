# gamebot 开发终端启动器
#
# ===========================================================================
# 它解决什么
# ===========================================================================
#
# 在 **VS Code 的集成终端**里跑脚本时，进程继承 VS Code 的权限级别
# （普通启动的 VS Code 是 Medium），而**这台机器上游戏是提权运行的**。
# Windows 的 UIPI 规定：
#
#     发送方进程的完整性级别必须 >= 目标窗口的级别
#
# 级别不够时**一切都是静默失效**的：
#
#   * 鼠标指针**会**移到正确位置，但点击不生效；
#   * 失焦后全局快捷键收不到；
#   * 而程序退出码 0、识别命中、动作返回 success —— 只有游戏没反应。
#
# 实测：普通终端（Low）/ VS Code 终端（Medium）都不行，
# **管理员（High）才可以**。
#
# 这个脚本做两件事：**确保自己是管理员**，然后把环境装好、直接给你一个
# 可以用的终端（venv 已激活、常用命令已说明）。
#
# ===========================================================================
# 用法
# ===========================================================================
#
#   # 交互式：右键 -> 以管理员身份运行；或已提权的终端里跑
#   .\dev.ps1
#
#   # 一条命令（跑完就退，适合 VS Code 的任务）
#   .\dev.ps1 -Command "uv run python -m games doctor mingjiangsha/jingji"
#   .\dev.ps1 -Command "uv run python -m games run mingjiangsha/jingji --max-ticks 20"
#   .\dev.ps1 -Command "uv run pytest tests/ -q"
#
# ## 在 VS Code 里怎么用
#
# 集成终端本身提不了权（VS Code 不是管理员时，它的子进程也不是）。
# 两个选择：
#
#   1. **以管理员身份启动 VS Code** —— 之后集成终端里跑什么都够权限；
#      最省事，推荐；
#   2. 保持 VS Code 普通权限，需要真机操作时用 `.\.dev.ps1 -Command "..."`，
#      它会自己弹 UAC。
#
# 只在 VS Code 里改代码 / 跑单元测试的话，**不需要管理员** ——
# 单元测试不碰真机输入。要碰真机（games run / games poke）才需要。

param(
    [string]$Command = ''
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$root = $PSScriptRoot

# ---------------------------------------------------------------------------
# 读完整性级别（纯 Win32）
# ---------------------------------------------------------------------------
Add-Type -Namespace DshDev -Name Token -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError=true)]
public static extern IntPtr OpenProcess(int access, bool inherit, int pid);
[DllImport("kernel32.dll", SetLastError=true)]
public static extern bool CloseHandle(IntPtr handle);
[DllImport("advapi32.dll", SetLastError=true)]
public static extern bool OpenProcessToken(IntPtr process, int access, out IntPtr token);
[DllImport("advapi32.dll", SetLastError=true)]
public static extern bool GetTokenInformation(IntPtr token, int cls, IntPtr info, int len, out int needed);
[DllImport("advapi32.dll")]
public static extern IntPtr GetSidSubAuthority(IntPtr sid, int index);
[DllImport("advapi32.dll")]
public static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);
'@

function Get-IntegrityLevel([int]$ProcessId) {
    $PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    $TOKEN_QUERY = 0x0008
    $TokenIntegrityLevel = 25
    $names = @{ 0x0000='Untrusted'; 0x1000='Low'; 0x2000='Medium'; 0x2100='Medium+'; 0x3000='High'; 0x4000='System' }
    $h = [DshDev.Token]::OpenProcess($PROCESS_QUERY_LIMITED_INFORMATION, $false, $ProcessId)
    if ($h -eq [IntPtr]::Zero) { return $null }
    try {
        $token = [IntPtr]::Zero
        if (-not [DshDev.Token]::OpenProcessToken($h, $TOKEN_QUERY, [ref]$token)) { return $null }
        try {
            $needed = 0
            [DshDev.Token]::GetTokenInformation($token, $TokenIntegrityLevel, [IntPtr]::Zero, 0, [ref]$needed) | Out-Null
            if ($needed -eq 0) { return $null }
            $buf = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($needed)
            try {
                if (-not [DshDev.Token]::GetTokenInformation($token, $TokenIntegrityLevel, $buf, $needed, [ref]$needed)) { return $null }
                $sid = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($buf)
                $cntPtr = [DshDev.Token]::GetSidSubAuthorityCount($sid)
                $cnt = [System.Runtime.InteropServices.Marshal]::ReadByte($cntPtr)
                $lastPtr = [DshDev.Token]::GetSidSubAuthority($sid, [int]($cnt - 1))
                $value = [System.Runtime.InteropServices.Marshal]::ReadInt32($lastPtr)
                if ($names.ContainsKey($value)) { return $names[$value] }
                return ('0x{0:X4}' -f $value)
            } finally { [System.Runtime.InteropServices.Marshal]::FreeHGlobal($buf) }
        } finally { [DshDev.Token]::CloseHandle($token) | Out-Null }
    } finally { [DshDev.Token]::CloseHandle($h) | Out-Null }
}

# ---------------------------------------------------------------------------
# 权限不够就提权重来
# ---------------------------------------------------------------------------
$mine = Get-IntegrityLevel -ProcessId $PID
if ($mine -and $mine -notin @('High', 'System')) {
    Write-Host "当前权限: $mine —— 不够（游戏是提权运行的），正在请求管理员权限…" -ForegroundColor Yellow
    Write-Host '（UAC 弹窗里点"是"）' -ForegroundColor Yellow
    # 把 -Command 原样带过去
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Command) { $argList += @('-Command', "`"$Command`"") }
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList | Out-Null
    } catch {
        Write-Host ''
        Write-Host '提权被拒绝（或者这个账户提不了权）。' -ForegroundColor Red
        Write-Host '真机操作（games run / poke）在这个级别下会静默失效：' -ForegroundColor Red
        Write-Host '  鼠标会动，但点击不生效；失焦后热键也收不到。' -ForegroundColor Red
        Write-Host ''
        Write-Host '只跑单元测试 / 改代码的话不需要管理员，可以直接用普通终端。' -ForegroundColor DarkGray
        exit 1
    }
    exit 0
}

Write-Host "gamebot 开发终端   权限: $mine" -ForegroundColor Green
Write-Host "目录: $root"
Write-Host ''

# ---------------------------------------------------------------------------
# 环境：venv 里的可执行文件直接加进 PATH（不依赖 uv，也不依赖 activate 脚本）
# ---------------------------------------------------------------------------
$venvScripts = Join-Path $root '.venv\Scripts'
if (-not (Test-Path -LiteralPath (Join-Path $venvScripts 'python.exe'))) {
    Write-Host '[错误] 没有找到 .venv。请先跑:' -ForegroundColor Red
    Write-Host '    uv sync --extra windows --extra ui' -ForegroundColor Yellow
    Write-Host ''
    if (-not $Command) { Read-Host '按回车关闭' }
    exit 1
}
$env:PATH = "$venvScripts;$env:PATH"
$env:VIRTUAL_ENV = Join-Path $root '.venv'
$env:GAMEBOT_DEV = '1'

# ---------------------------------------------------------------------------
# 一条命令模式
# ---------------------------------------------------------------------------
if ($Command) {
    Write-Host "> $Command" -ForegroundColor Cyan
    Write-Host ''
    # 用 Invoke-Expression 是为了让管道/引号之类原样生效（这是开发者自己的命令）
    Invoke-Expression $Command
    $rc = $LASTEXITCODE
    Write-Host ''
    if ($rc -ne 0) {
        Write-Host "[退出码 $rc]" -ForegroundColor Red
        # **归一成 1**：原样传负数（外层 PowerShell 会给出 -1）在某些调用方
        # 那里会被当成成功（只看到低字节）。这里只保证"非零 = 失败"。
        exit 1
    }
    Write-Host '[完成]' -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# 交互模式：给一段提示，然后进 PowerShell（venv 已激活）
# ---------------------------------------------------------------------------
Write-Host 'venv 已激活。常用命令：' -ForegroundColor Cyan
Write-Host '  python -m games list                      # 有哪些脚本'
Write-Host '  python -m games doctor mingjiangsha/jingji # **跑之前先自检**（权限/前台/模板/抓屏）'
Write-Host '  python -m games run mingjiangsha/jingji --dry-run --max-ticks 5   # 空跑：只识别不动手'
Write-Host '  python -m games run mingjiangsha/jingji    # 真跑'
Write-Host '  python -m games poke  mingjiangsha/jingji 1365 585   # 点一下并报告全过程'
Write-Host '  pytest tests/ -q                          # 单元测试（不需要管理员）'
Write-Host ''
Write-Host '真机操作前请先跑 doctor：它会查权限级别、前台窗口、模板、抓屏。' -ForegroundColor DarkGray
Write-Host '这个项目有一类失败是彻底静默的（退出码 0、识别命中、动作成功，只有游戏没反应）。' -ForegroundColor DarkGray
Write-Host ''
Write-Host '输入 exit 退出。' -ForegroundColor DarkGray
Write-Host ''

# 起一个子 PowerShell：这样 exit 只退子壳，不会把 UAC 提权的那层也带走
& powershell -NoProfile -NoExit -Command "Set-Location -LiteralPath '$root'"
