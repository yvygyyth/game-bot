# gamebot 界面启动器
#
# **在资源管理器里双击本文件**（或右键 -> 使用 PowerShell 运行）。
#
# ## 为什么要"双击"这件事很重要
#
# 这个脚本**必须由普通权限启动**，原因是 Windows 的 UIPI：
# **低完整性级别的进程不能给高完整性级别的窗口发输入**。
# 目标游戏是"普通用户"（Medium）级别，而比它低的进程：
#
#   * 鼠标指针**会**移到正确位置（SetCursorPos 不受 UIPI 限制）；
#   * 但点击**不生效**（SendInput 返回成功，消息被悄悄丢掉）；
#   * 失焦后全局快捷键也收不到（键盘钩子装在低权限进程里）。
#
# 这三件事**都不报错** —— 排查时看起来完全像"坐标算错了"或
# "游戏不认合成输入"。真相在权限上。
#
# 从资源管理器双击起来的进程会继承资源管理器（普通用户）的级别，
# 所以"双击"不只是图方便，它是**能用的前提**。
#
# ## 为什么不给 .bat
#
# 批处理的编码（GBK / UTF-8 / chcp）和中文很容易撞车，一旦乱码还会
# 把命令行解析错 —— 试过了，会报
# "'xxx' is not recognized as an internal or external command"。
# PowerShell 脚本对 UTF-8 的处理可靠得多。

Set-Location -LiteralPath $PSScriptRoot

# ---------------------------------------------------------------------------
# 读一个进程的完整性级别（纯 Win32，不依赖项目代码）
# ---------------------------------------------------------------------------
Add-Type -Namespace Dsh -Name Token -MemberDefinition @'
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
    $names = @{
        0x0000 = 'Untrusted'; 0x1000 = 'Low'; 0x2000 = 'Medium'
        0x2100 = 'Medium+';   0x3000 = 'High'; 0x4000 = 'System'
    }
    $h = [Dsh.Token]::OpenProcess($PROCESS_QUERY_LIMITED_INFORMATION, $false, $ProcessId)
    if ($h -eq [IntPtr]::Zero) { return $null }
    try {
        $token = [IntPtr]::Zero
        if (-not [Dsh.Token]::OpenProcessToken($h, $TOKEN_QUERY, [ref]$token)) { return $null }
        try {
            $needed = 0
            [Dsh.Token]::GetTokenInformation($token, $TokenIntegrityLevel, [IntPtr]::Zero, 0, [ref]$needed) | Out-Null
            if ($needed -eq 0) { return $null }
            $buf = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($needed)
            try {
                if (-not [Dsh.Token]::GetTokenInformation($token, $TokenIntegrityLevel, $buf, $needed, [ref]$needed)) { return $null }
                # TOKEN_MANDATORY_LABEL { SID_AND_ATTRIBUTES { Sid, Attributes } }
                $sid = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($buf)
                $countPtr = [Dsh.Token]::GetSidSubAuthorityCount($sid)
                $count = [System.Runtime.InteropServices.Marshal]::ReadByte($countPtr)
                $lastPtr = [Dsh.Token]::GetSidSubAuthority($sid, [int]($count - 1))
                $value = [System.Runtime.InteropServices.Marshal]::ReadInt32($lastPtr)
                if ($names.ContainsKey($value)) { return $names[$value] }
                return ('0x{0:X4}' -f $value)
            } finally {
                [System.Runtime.InteropServices.Marshal]::FreeHGlobal($buf)
            }
        } finally { [Dsh.Token]::CloseHandle($token) | Out-Null }
    } finally { [Dsh.Token]::CloseHandle($h) | Out-Null }
}

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' gamebot 界面' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host "目录: $PWD"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ''
    Write-Host '[错误] 找不到 uv。先装它: https://docs.astral.sh/uv/' -ForegroundColor Red
    Write-Host ''
    Read-Host '按回车关闭'
    exit 1
}

# ---- 权限检查：这是能不能操作游戏的前提 ----
$mine = Get-IntegrityLevel -ProcessId $PID
Write-Host ''
if ($mine -in @('Medium', 'Medium+', 'High', 'System')) {
    Write-Host "权限: $mine" -ForegroundColor Green -NoNewline
    Write-Host '  —— 和游戏同级或更高，输入送得进去'
} elseif ($mine -in @('Low', 'Untrusted')) {
    Write-Host "权限: $mine" -ForegroundColor Red -NoNewline
    Write-Host '  —— 太低了，输入发不进游戏！' -ForegroundColor Red
    Write-Host ''
    Write-Host '  Windows 的 UIPI 规定：低权限进程不能给高权限窗口发输入。' -ForegroundColor Red
    Write-Host '  表现是「鼠标会动，但点击无效、失焦后快捷键也没反应」——而且不报错。' -ForegroundColor Red
    Write-Host ''
    Write-Host '  请换一个方式启动：' -ForegroundColor Yellow
    Write-Host '    * 在资源管理器里双击本文件；或者' -ForegroundColor Yellow
    Write-Host '    * 在一个正常打开的终端（Windows Terminal / PowerShell）里跑' -ForegroundColor Yellow
    Write-Host '        uv run python -m gamebot ui' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  不要从受限宿主（沙箱 / AI 工具自带的终端等）里启动 —— 级别会一直带下来。' -ForegroundColor Yellow
    Write-Host ''
    Read-Host '按回车关闭'
    exit 1
} else {
    Write-Host "权限: $mine （读不出来，跳过判断）" -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '正在启动…（第一次可能要装依赖，会慢一点）' -ForegroundColor Yellow
Write-Host ''

& uv run python -m gamebot ui @args
$rc = $LASTEXITCODE

Write-Host ''
if ($rc -ne 0) {
    Write-Host "[退出码 $rc] 起不来 —— 上面应该有报错。" -ForegroundColor Red
} else {
    Write-Host '界面已关闭。'
}
Write-Host ''
Read-Host '按回车关闭'
