# gamebot 界面启动器
#
# ## 必须"以管理员身份运行"
#
# 这台机器上**游戏是提权运行的**，而 Windows 有一条硬规则：
#
#     UIPI —— 发送方进程的完整性级别必须 >= 目标窗口的级别
#
# 级别不够时的表现**全部是静默的**，看起来像代码写错了：
#
#   * 鼠标指针**会**移到正确位置（SetCursorPos 不受 UIPI 限制）；
#   * 但点击**不生效**（SendInput 返回成功，消息被悄悄丢掉）；
#   * 失焦后全局快捷键也收不到（低级键盘钩子收不到高完整性窗口的按键）。
#
# 实测（这台机器）：
#
#     从普通终端启动（Low）      -> 点击无效、监听无效
#     普通双击（Medium）         -> 点击无效、监听无效
#     以管理员身份运行（High）    -> **能点击、能失焦监听** ✓
#
# 所以：**右键本文件 -> 以管理员身份运行**（或在管理员终端里跑
# `uv run python -m gamebot ui`）。
#
# ## 为什么要检查并拦下来
#
# 因为失败是静默的：级别不够时程序**看起来完全正常**（启动成功、识别命中、
# 动作层返回 success），只有游戏没反应。不拦的话下一步一定是去调坐标、
# 重裁模板、换输入引擎 —— 全都无效，因为原因在权限上。
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
if ($mine -in @('High', 'System')) {
    Write-Host "权限: $mine" -ForegroundColor Green -NoNewline
    Write-Host '  —— 管理员级别，比游戏高，输入送得进去'
} elseif ($mine -in @('Medium', 'Medium+', 'Low', 'Untrusted')) {
    Write-Host "权限: $mine" -ForegroundColor Red -NoNewline
    Write-Host '  —— 可能不够，输入会**静默失效**！' -ForegroundColor Red
    Write-Host ''
    Write-Host '  这台机器上游戏是**提权运行**的，而 Windows 规定：' -ForegroundColor Yellow
    Write-Host '    发送方进程的完整性级别必须 >= 目标窗口的级别（UIPI）。' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  级别不够的表现（全都不报错，看起来像代码写错了）：' -ForegroundColor Yellow
    Write-Host '    * 鼠标会移到正确位置，但点击不生效；' -ForegroundColor Yellow
    Write-Host '    * 失焦后全局快捷键也收不到（键盘钩子收不到高权限窗口的按键）。' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  实测对照：' -ForegroundColor Cyan
    Write-Host '    Low / Medium -> 点击无效、监听无效' -ForegroundColor Cyan
    Write-Host '    High（管理员）-> **能点击、能失焦监听** ✓' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  请改成：**右键本文件 -> 以管理员身份运行**，' -ForegroundColor Green
    Write-Host '  或者在一个**管理员**终端里跑 uv run python -m gamebot ui。' -ForegroundColor Green
    Write-Host ''
    $answer = Read-Host '  现在就用管理员权限重新启动吗？(Y/n)'
    if ($answer -eq '' -or $answer -match '^[Yy]') {
        Write-Host ''
        Write-Host '  正在请求管理员权限…（会弹 UAC）' -ForegroundColor Yellow
        # 用 Start-Process -Verb RunAs 重新拉起自己（提权）
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', "`"$PSCommandPath`""
        )
        exit 0
    }
    Write-Host ''
    Write-Host '  （继续启动，但输入很可能送不进去）' -ForegroundColor DarkGray
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
