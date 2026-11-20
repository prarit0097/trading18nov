param([string]$Root, [string]$Script, [string]$Argument = '', [int]$TimeoutSeconds = 2400)
$ErrorActionPreference='Stop'
$rootItem=Get-Item -LiteralPath $Root
$Root=$rootItem.FullName
$inside=Join-Path $Root $Script
if (!(Test-Path -LiteralPath $inside -PathType Leaf)) { throw 'Sandbox script is missing' }
Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public static class NonpineSandbox {
    [StructLayout(LayoutKind.Sequential)] public struct StartupInfo {
        public int cb;
        public IntPtr reserved, desktop, title;
        public int x, y, xSize, ySize, xCount, yCount, fill, flags;
        public short show, reservedCount;
        public IntPtr reservedPtr, stdIn, stdOut, stdErr;
    }
    [StructLayout(LayoutKind.Sequential)] public struct StartupInfoEx {
        public StartupInfo si;
        public IntPtr attributes;
    }
    [StructLayout(LayoutKind.Sequential)] public struct ProcessInfo {
        public IntPtr process, thread;
        public uint processId, threadId;
    }
    [StructLayout(LayoutKind.Sequential)] public struct SecurityCapabilities {
        public IntPtr sid, capabilities;
        public int capabilityCount, reserved;
    }
    [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int CreateAppContainerProfile(string name,string title,string description,IntPtr capabilities,int n,out IntPtr sid);
    [DllImport("userenv.dll", CharSet=CharSet.Unicode)] static extern int DeriveAppContainerSidFromAppContainerName(string name,out IntPtr sid);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool ConvertSidToStringSid(IntPtr sid, out IntPtr value);
    [DllImport("advapi32.dll")] static extern IntPtr FreeSid(IntPtr sid);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr ptr);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr attributes,int n,int flags,ref IntPtr size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr attributes,uint flags,IntPtr attribute,ref SecurityCapabilities value,IntPtr size,IntPtr previous,IntPtr ReturnSize);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr attributes);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateProcess(string app,StringBuilder args,IntPtr processAttributes,IntPtr threadAttributes,bool inherit,uint flags,IntPtr environment,string cwd,ref StartupInfoEx startup,out ProcessInfo process);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle,uint timeout);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr handle,uint code);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr handle,out uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    static IntPtr Profile(string name, bool create) {
        IntPtr sid;
        int result = create ? CreateAppContainerProfile(name,name,"Offline public strategy research",IntPtr.Zero,0,out sid) : DeriveAppContainerSidFromAppContainerName(name,out sid);
        if (result == unchecked((int)0x800700B7)) result = DeriveAppContainerSidFromAppContainerName(name,out sid);
        if (result != 0) Marshal.ThrowExceptionForHR(result);
        return sid;
    }
    public static string Sid(string name) {
        IntPtr sid=Profile(name,true), value;
        try {
            if (!ConvertSidToStringSid(sid,out value)) throw new Win32Exception();
            try { return Marshal.PtrToStringUni(value); } finally { LocalFree(value); }
        } finally { FreeSid(sid); }
    }
    public static uint Run(string name,string root,string exe,string args,string environment,uint milliseconds) {
        IntPtr sid=Profile(name,false), size=IntPtr.Zero;
        InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref size);
        IntPtr attrs=Marshal.AllocHGlobal(size), env=Marshal.StringToHGlobalUni(environment);
        bool initialized=false;
        try {
            if (!InitializeProcThreadAttributeList(attrs,1,0,ref size)) throw new Win32Exception();
            initialized=true;
            var caps=new SecurityCapabilities{sid=sid};
            if (!UpdateProcThreadAttribute(attrs,0,new IntPtr(0x00020009),ref caps,new IntPtr(Marshal.SizeOf(caps)),IntPtr.Zero,IntPtr.Zero)) throw new Win32Exception();
            var start=new StartupInfoEx{si=new StartupInfo{cb=Marshal.SizeOf(typeof(StartupInfoEx))},attributes=attrs};
            ProcessInfo pi;
            if (!CreateProcess(exe,new StringBuilder(args),IntPtr.Zero,IntPtr.Zero,false,0x08080400,env,root,ref start,out pi)) throw new Win32Exception();
            try {
                uint code;
                if (WaitForSingleObject(pi.process,milliseconds) != 0) { TerminateProcess(pi.process,124); return 124; }
                if (!GetExitCodeProcess(pi.process,out code)) throw new Win32Exception();
                return code;
            } finally { CloseHandle(pi.thread); CloseHandle(pi.process); }
        } finally {
            if (initialized) DeleteProcThreadAttributeList(attrs);
            Marshal.FreeHGlobal(attrs); Marshal.FreeHGlobal(env); FreeSid(sid);
        }
    }
}
"@
$name='CodexNonpineReplay'+(Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($Root)))).Hash.Substring(0,12)
$sid=[NonpineSandbox]::Sid($name)
& icacls $Root /grant ('*'+$sid+':(OI)(CI)M') /q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not grant sandbox scratch access' }
$python=Join-Path $Root 'python/python.exe'
$envpairs=@('COMSPEC=C:\Windows\System32\cmd.exe','PATH=C:\Windows\System32','PYTHONUTF8=1','OPENBLAS_NUM_THREADS=1','SYSTEMROOT=C:\Windows',"TEMP=$Root","TMP=$Root",'WINDIR=C:\Windows') + @('SystemDrive','HOMEDRIVE','HOMEPATH','USERPROFILE','LOCALAPPDATA','APPDATA','COMPUTERNAME','USERNAME','USERDOMAIN','ProgramFiles','ProgramData','CommonProgramFiles').ForEach({ "$_=$([Environment]::GetEnvironmentVariable($_))" })
$envblock=(($envpairs | Sort-Object) -join [char]0)+[char]0+[char]0
$command='"'+$python+'" -I "'+$inside+'" '+$Argument
$code=[NonpineSandbox]::Run($name,$Root,$python,$command,$envblock,[uint32]($TimeoutSeconds*1000))
Write-Output "Sandbox exit $code"
if ($code -ne 0) { exit 1 }
