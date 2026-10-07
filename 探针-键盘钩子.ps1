# 一体化探针：完整性级别 + 低级键盘钩子
#
# 不依赖 Python、不依赖本项目 —— 纯 PowerShell + Win32 调用，
# 所以"跑不起来"的原因只可能是环境，不可能是代码。
#
# 用法：在**你自己的终端**里运行
#     powershell -NoProfile -ExecutionPolicy Bypass -File 探针-键盘钩子.ps1
# 或者在这个文件上右键 -> 使用 PowerShell 运行。
#
# 它会：
#   1. 报出本进程的**完整性级别**（Low / Medium / High）；
#   2. 装一个低级键盘钩子（WH_KEYBOARD_LL），报出句柄和 GetLastError；
#   3. 让你按几个键，把收到的每个键打出来。
#
# 判读：
#   级别 = Medium 且收到按键  -> 环境没问题，那就该从"这个终端"启动 gamebot
#   级别 = Low               -> 太低，低级钩子会被系统静默禁掉（零回调）
#   级别够高但零回调          -> 另有原因，把这整段输出发给我

$ErrorActionPreference = 'Stop'

Add-Type -Namespace Dsh2 -Name Hook -MemberDefinition @'
// ---- 完整性级别 ----
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

// ---- 低级键盘钩子 ----
public delegate IntPtr HookProc(int code, IntPtr wparam, IntPtr lparam);

[DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
public static extern IntPtr SetWindowsHookExW(int idHook, HookProc callback, IntPtr hMod, uint threadId);
[DllImport("user32.dll", SetLastError=true)]
public static extern bool UnhookWindowsHookEx(IntPtr hook);
[DllImport("user32.dll", SetLastError=true)]
public static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wparam, IntPtr lparam);
[DllImport("user32.dll", CharSet=CharSet.Unicode)]
public static extern int GetMessageW(out MSG msg, IntPtr hwnd, uint min, uint max);
[DllImport("user32.dll")]
public static extern bool TranslateMessage(ref MSG msg);
[DllImport("user32.dll", CharSet=CharSet.Unicode)]
public static extern IntPtr DispatchMessageW(ref MSG msg);
[DllImport("user32.dll", CharSet=CharSet.Unicode)]
public static extern bool PeekMessageW(ref MSG msg, IntPtr hwnd, uint min, uint max, uint remove);
[DllImport("user32.dll")]
public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll", CharSet=CharSet.Unicode)]
public static extern int GetWindowTextW(IntPtr hwnd, System.Text.StringBuilder text, int max);

[StructLayout(LayoutKind.Sequential)]
public struct POINT { public int x; public int y; }

[StructLayout(LayoutKind.Sequential)]
public struct MSG {
    public IntPtr hwnd; public uint message; public IntPtr wParam;
    public IntPtr lParam; public uint time; public POINT pt;
}

// ---- 自测用：注入一个按键（SendInput）----
[StructLayout(LayoutKind.Sequential)]
public struct KEYBDINPUT {
    public ushort wVk; public ushort wScan; public uint dwFlags;
    public uint time; public IntPtr dwExtraInfo;
}

[StructLayout(LayoutKind.Explicit)]
public struct INPUTUNION {
    [FieldOffset(0)] public KEYBDINPUT ki;
    [FieldOffset(0)] public byte pad;
}

[StructLayout(LayoutKind.Sequential)]
public struct INPUT { public uint type; public INPUTUNION u; }

[DllImport("user32.dll", SetLastError=true)]
public static extern uint SendInput(uint count, INPUT[] inputs, int size);
'@

function Get-IntegrityLevel([int]$ProcessId) {
    $PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    $TOKEN_QUERY = 0x0008
    $TokenIntegrityLevel = 25
    $names = @{ 0x0000='Untrusted'; 0x1000='Low'; 0x2000='Medium'; 0x2100='Medium+'; 0x3000='High'; 0x4000='System' }

    $h = [Dsh2.Hook]::OpenProcess($PROCESS_QUERY_LIMITED_INFORMATION, $false, $ProcessId)
    if ($h -eq [IntPtr]::Zero) { return $null }
    try {
        $token = [IntPtr]::Zero
        if (-not [Dsh2.Hook]::OpenProcessToken($h, $TOKEN_QUERY, [ref]$token)) { return $null }
        try {
            $needed = 0
            [Dsh2.Hook]::GetTokenInformation($token, $TokenIntegrityLevel, [IntPtr]::Zero, 0, [ref]$needed) | Out-Null
            if ($needed -eq 0) { return $null }
            $buf = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($needed)
            try {
                if (-not [Dsh2.Hook]::GetTokenInformation($token, $TokenIntegrityLevel, $buf, $needed, [ref]$needed)) { return $null }
                $sid = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($buf)
                $cntPtr = [Dsh2.Hook]::GetSidSubAuthorityCount($sid)
                $cnt = [System.Runtime.InteropServices.Marshal]::ReadByte($cntPtr)
                $lastPtr = [Dsh2.Hook]::GetSidSubAuthority($sid, [int]($cnt - 1))
                $value = [System.Runtime.InteropServices.Marshal]::ReadInt32($lastPtr)
                if ($names.ContainsKey($value)) { return $names[$value] }
                return ('0x{0:X4}' -f $value)
            } finally { [System.Runtime.InteropServices.Marshal]::FreeHGlobal($buf) }
        } finally { [Dsh2.Hook]::CloseHandle($token) | Out-Null }
    } finally { [Dsh2.Hook]::CloseHandle($h) | Out-Null }
}

Write-Host '====================================================================' -ForegroundColor Cyan
Write-Host ' 键盘钩子探针（纯 PowerShell，不依赖任何项目代码）' -ForegroundColor Cyan
Write-Host '====================================================================' -ForegroundColor Cyan
Write-Host ''

$level = Get-IntegrityLevel -ProcessId $PID
Write-Host "本进程 PID     : $PID"
Write-Host "完整性级别     : " -NoNewline
if ($level -in @('Medium','Medium+','High','System')) {
    Write-Host $level -ForegroundColor Green
} elseif ($level -in @('Low','Untrusted')) {
    Write-Host "$level  <-- 太低了！" -ForegroundColor Red
} else {
    Write-Host $level -ForegroundColor DarkGray
}

$fg = [Dsh2.Hook]::GetForegroundWindow()
$sb = New-Object System.Text.StringBuilder 256
[Dsh2.Hook]::GetWindowTextW($fg, $sb, 256) | Out-Null
Write-Host "当前前台窗口   : $($sb.ToString())"
Write-Host ''

# 保持回调委托不被 GC（被回收 = 崩）
$script:hits = New-Object System.Collections.ArrayList
$script:callback = [Dsh2.Hook+HookProc]{
    param($code, $wparam, $lparam)
    if ($code -ge 0) {
        $msg = [int]$wparam
        if ($msg -eq 0x0100 -or $msg -eq 0x0104) {
            $vk = [System.Runtime.InteropServices.Marshal]::ReadInt32($lparam)
            [void]$script:hits.Add($vk)
            Write-Host ("    [收到] vk=0x{0:X2} ({1})" -f $vk, $vk) -ForegroundColor Yellow
        }
    }
    return [Dsh2.Hook]::CallNextHookEx([IntPtr]::Zero, $code, $wparam, $lparam)
}

Write-Host '正在装低级键盘钩子（WH_KEYBOARD_LL）…'
$hook = [Dsh2.Hook]::SetWindowsHookExW(13, $script:callback, [IntPtr]::Zero, 0)
$err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
if ($hook -eq [IntPtr]::Zero) {
    Write-Host "  SetWindowsHookExW 失败，GetLastError=$err" -ForegroundColor Red
    Read-Host '按回车关闭'
    exit 1
}
Write-Host "  钩子句柄 = $hook   GetLastError = $err" -ForegroundColor Green
Write-Host ''

# ---------------------------------------------------------------------------
# 自测：给自己注入一个 F9，看钩子收不收得到
#
# 这一步把"钩子机制通不通"和"用户手按的键收不收得到"分开：
# 注入的键和手按的键走**同一条钩子链**，只是拦截点可能不同。
# 如果连注入的都收不到，那这台机器上这条链就是不通的（权限/环境）。
# ---------------------------------------------------------------------------
if ($args -contains '-SelfTest') {
    Write-Host '自测：注入一个 F9 …' -ForegroundColor Cyan
    $down = New-Object Dsh2.Hook+INPUT
    $down.type = 1
    $down.u.ki = New-Object Dsh2.Hook+KEYBDINPUT
    $down.u.ki.wVk = 0x78   # VK_F9
    $up = New-Object Dsh2.Hook+INPUT
    $up.type = 1
    $up.u.ki = New-Object Dsh2.Hook+KEYBDINPUT
    $up.u.ki.wVk = 0x78
    $up.u.ki.dwFlags = 0x0002   # KEYEVENTF_KEYUP

    $sent = [Dsh2.Hook]::SendInput(2, @($down, $up), [System.Runtime.InteropServices.Marshal]::SizeOf([type][Dsh2.Hook+INPUT]))
    Start-Sleep -Milliseconds 400
    # 泵一下消息，让钩子回调有机会跑
    $m = New-Object Dsh2.Hook+MSG
    while ([Dsh2.Hook]::PeekMessageW([ref]$m, [IntPtr]::Zero, 0, 0, 1)) {
        [Dsh2.Hook]::TranslateMessage([ref]$m) | Out-Null
        [Dsh2.Hook]::DispatchMessageW([ref]$m) | Out-Null
    }
    Write-Host "  SendInput 返回 $sent（2 = 两条都发出去了）" -ForegroundColor Cyan
    Write-Host "  钩子收到 $($script:hits.Count) 个按键" -ForegroundColor $(if ($script:hits.Count) { 'Green' } else { 'Red' })
    if ($script:hits.Count -gt 0) {
        Write-Host '  ✓ 钩子机制在这个级别下是**通的** —— 环境没问题。' -ForegroundColor Green
        Write-Host '    那"按了没反应"就只是"进程级别不对"或"键被游戏占了"。' -ForegroundColor Green
    } else {
        Write-Host '  ✗ 连注入的都收不到 —— 这条链在这个级别下就是不通的。' -ForegroundColor Red
    }
    Write-Host ''
    [Dsh2.Hook]::UnhookWindowsHookEx($hook) | Out-Null
    Read-Host '按回车关闭'
    exit 0
}

Write-Host '现在：**用鼠标点一下别的窗口**（让这个控制台失焦），' -ForegroundColor Cyan
Write-Host '      然后按 F9 / F5 / A / B 几个键。' -ForegroundColor Cyan
Write-Host '      按 Ctrl+C 结束。' -ForegroundColor Cyan
Write-Host ''

$msgStruct = New-Object Dsh2.Hook+MSG
try {
    while ([Dsh2.Hook]::GetMessageW([ref]$msgStruct, [IntPtr]::Zero, 0, 0) -gt 0) {
        [Dsh2.Hook]::TranslateMessage([ref]$msgStruct) | Out-Null
        [Dsh2.Hook]::DispatchMessageW([ref]$msgStruct) | Out-Null
    }
} finally {
    [Dsh2.Hook]::UnhookWindowsHookEx($hook) | Out-Null
}

Write-Host ''
Write-Host "结束：一共收到 $($script:hits.Count) 个按键" -ForegroundColor Cyan
if ($script:hits.Count -eq 0) {
    Write-Host '零回调。对照上面的"完整性级别"：' -ForegroundColor Yellow
    Write-Host '  * 如果是 Low/Untrusted -> 就是这个原因：低完整性进程的低级钩子会被系统静默禁掉。' -ForegroundColor Yellow
    Write-Host '    解决办法：从普通权限的终端启动（双击脚本 / 资源管理器 / 正常打开的终端）。' -ForegroundColor Yellow
    Write-Host '  * 如果已经是 Medium 以上 -> 把这整段输出发给我，另有原因。' -ForegroundColor Yellow
}
Write-Host ''
Read-Host '按回车关闭'
