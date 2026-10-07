# gamebot 启动器 —— 双击就开，**不带控制台窗口**
#
# ===========================================================================
# 为什么必须"以管理员身份运行"
# ===========================================================================
#
# 这台机器上**游戏是提权运行的**，而 Windows 有一条硬规则：
#
#     UIPI —— 发送方进程的完整性级别必须 >= 目标窗口的级别
#
# 级别不够时表现**全部是静默的**，看起来像代码写错了：
#
#   * 鼠标指针**会**移到正确位置（SetCursorPos 不受 UIPI 限制）；
#   * 但点击**不生效**（SendInput 返回成功，消息被悄悄丢掉）；
#   * 失焦后全局快捷键也收不到（低级键盘钩子收不到高完整性窗口的按键）。
#
# 实测（这台机器）：
#
#     普通终端（Low）         -> 点击无效、监听无效
#     普通双击（Medium）      -> 点击无效、监听无效
#     **以管理员身份运行（High） -> 能点击、能失焦监听** ✓
#
# 所以本脚本检测到级别不够时会**主动请求提权**（弹 UAC，点一下"是"）。
#
# ===========================================================================
# 为什么用 pythonw.exe 而不是 uv run
# ===========================================================================
#
# ``uv run`` 和 ``python.exe`` 都是**控制台程序**：双击会先弹一个黑窗口，
# 而且那个窗口要一直开着（关掉就等于杀掉脚本）。
#
# ``.venv\Scripts\pythonw.exe`` 是同一个解释器的**无控制台版本** ——
# 用它启动就只有一个 Qt 窗口，没有黑框。代码一个字都不用改。
#
# ===========================================================================
# 用法
# ===========================================================================
#
# * 双击桌面快捷方式 ``gamebot 界面``（它带 UAC 标志，会自动提权）；
# * 或右键本文件 -> 以管理员身份运行。

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$root = $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$logFile = Join-Path $root 'logs\ui-launch.log'

# ---------------------------------------------------------------------------
# 组装一个"能弹窗报错"的小工具（powershell.exe 不是控制台程序时也能用）
# ---------------------------------------------------------------------------
function Write-Note([string]$Text, [string]$Title = 'gamebot') {
    try {
        $null = [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
        [System.Windows.Forms.MessageBox]::Show($Text, $Title) | Out-Null
    } catch {
        Write-Host $Text
    }
}

# ---------------------------------------------------------------------------
# 1) 解释器在不在
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $pythonw)) {
    Write-Note @"
找不到解释器:

  $pythonw

这个目录应该有一个已装好依赖的 .venv。请先在项目目录里跑一次:

  uv sync --extra windows --extra ui

（uv 会把 .venv 建出来并装齐依赖。）
"@ 'gamebot —— 找不到解释器'
    exit 1
}

# ---------------------------------------------------------------------------
# 2) 权限级别：不够就提权重来
# ---------------------------------------------------------------------------
Add-Type -Namespace Dsh3 -Name Token -MemberDefinition @'
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
    $h = [Dsh3.Token]::OpenProcess($PROCESS_QUERY_LIMITED_INFORMATION, $false, $ProcessId)
    if ($h -eq [IntPtr]::Zero) { return $null }
    try {
        $token = [IntPtr]::Zero
        if (-not [Dsh3.Token]::OpenProcessToken($h, $TOKEN_QUERY, [ref]$token)) { return $null }
        try {
            $needed = 0
            [Dsh3.Token]::GetTokenInformation($token, $TokenIntegrityLevel, [IntPtr]::Zero, 0, [ref]$needed) | Out-Null
            if ($needed -eq 0) { return $null }
            $buf = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($needed)
            try {
                if (-not [Dsh3.Token]::GetTokenInformation($token, $TokenIntegrityLevel, $buf, $needed, [ref]$needed)) { return $null }
                $sid = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($buf)
                $cntPtr = [Dsh3.Token]::GetSidSubAuthorityCount($sid)
                $cnt = [System.Runtime.InteropServices.Marshal]::ReadByte($cntPtr)
                $lastPtr = [Dsh3.Token]::GetSidSubAuthority($sid, [int]($cnt - 1))
                $value = [System.Runtime.InteropServices.Marshal]::ReadInt32($lastPtr)
                if ($names.ContainsKey($value)) { return $names[$value] }
                return ('0x{0:X4}' -f $value)
            } finally { [System.Runtime.InteropServices.Marshal]::FreeHGlobal($buf) }
        } finally { [Dsh3.Token]::CloseHandle($token) | Out-Null }
    } finally { [Dsh3.Token]::CloseHandle($h) | Out-Null }
}

$mine = Get-IntegrityLevel -ProcessId $PID
if ($mine -and $mine -notin @('High', 'System')) {
    # 级别不够 —— 弹 UAC 提权重来。
    #
    # **自动提权而不是"提示用户自己去右键"**：这个失败是静默的
    # （程序看起来完全正常，只有游戏没反应），所以不能指望用户记得。
    $argList = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', "`"$PSCommandPath`""
    )
    if ($args.Count -gt 0) { $argList += $args }
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList | Out-Null
        exit 0
    } catch {
        # 用户点了"否"，或者这个账户提不了权
        Write-Note @"
当前权限级别: $mine  —— 不够。

这台机器上游戏是**提权运行**的，而 Windows 规定
发送方进程的完整性级别必须 >= 目标窗口的级别（UIPI）。

级别不够时点击和全局快捷键都会**静默失效**：
  * 鼠标会移到正确位置，但点击不生效；
  * 失焦后快捷键没反应。
而且**不会报任何错** —— 看起来完全像代码写错了。

请允许管理员权限（UAC 弹窗里点"是"），或右键本文件
-> 以管理员身份运行。
"@ 'gamebot —— 需要管理员权限'
        exit 1
    }
}

# ---------------------------------------------------------------------------
# 3) 用 pythonw 启动（无控制台窗口、日志由应用自己写文件）
# ---------------------------------------------------------------------------
$logDir = Join-Path $root 'logs'
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# ## 这一段踩了三个坑，都记下来
#
# **坑 1：不能让 PowerShell 做输出重定向。**
# ``Start-Process -RedirectStandardOutput`` 和 ``.NET Process.Start`` 配
# ``RedirectStandard*`` **都会一直等到子进程退出**才返回 —— 对 GUI 来说就是
# 永远不返回（实测分别卡 300 秒和 45 秒）。窗口虽然不可见，但会留一个
# 永不退出的脚本进程。
#
# **坑 2：Windows PowerShell 5.1 的 ``ProcessStartInfo`` 没有 ``ArgumentList``。**
# 它是 .NET Core / PowerShell 7 才有的。5.1 上写 ``$psi.ArgumentList.Add(...)``
# 会抛 "You cannot call a method on a null-valued expression"，
# **参数全部被丢掉** —— 进程起来了、什么都没做、立刻退出。极难查。
# 5.1 上要用 ``$psi.Arguments``（一整条字符串）。
#
# **坑 3：日志不能靠 stdout。**
# ``pythonw`` 没有控制台，不重定向时日志没地方去。所以让**应用自己写文件**
# （``-m gamebot ui`` 会写 ``logs/ui.log``，见 ``gamebot/__main__.py``）。
# 这比在外面包一层重定向干净得多，而且不依赖启动方式。
$uiArgs = @('-m', 'gamebot', 'ui') + $args
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pythonw
$psi.Arguments = ($uiArgs | ForEach-Object { '"' + $_ + '"' }) -join ' '
$psi.WorkingDirectory = $root
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
try {
    $proc = [System.Diagnostics.Process]::Start($psi)
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  权限=$mine  pid=$($proc.Id) ===" |
        Add-Content -LiteralPath (Join-Path $logDir 'ui-launch.marker.log') -Encoding UTF8
} catch {
    Write-Note "启动失败:`n`n$_`n`n解释器: $pythonw" 'gamebot —— 启动失败'
    exit 1
}

# 本脚本立刻退出 —— 界面是独立进程，关掉它不影响界面。
exit 0
