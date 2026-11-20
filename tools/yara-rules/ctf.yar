// CTF 内存/磁盘题常用规则 —— 找 flag、凭据、内存马、常见恶意工具
// 用法：
//   yara -r tools/yara-rules/ctf.yar work/mem.strings
//   yara -s -r tools/yara-rules/ctf.yar evi/mem.raw        # -s 打印命中偏移
//   yara -w -r ...                                          # -w 关掉警告

rule CTF_Flag_Generic
{
    meta:
        description = "通用 flag 格式"
        author = "fcase"
    strings:
        $f1 = /(flag|FLAG|Flag|ctf|CTF|CTF\{|key|KEY)\{[ -~]{4,120}\}/
        $f2 = /[A-Z0-9]{2,10}\{[A-Za-z0-9_\-!@#$%^&*()+=]{6,80}\}/
    condition:
        any of them
}

rule CTF_Flag_Hex
{
    meta:
        description = "32/40/64 位十六进制串（常见 md5/sha 型 flag）"
    strings:
        $h1 = /flag\{[0-9a-fA-F]{32}\}/
        $h2 = /flag\{[0-9a-fA-F]{40}\}/
        $h3 = /flag\{[0-9a-fA-F]{64}\}/
    condition:
        any of them
}

rule Credentials_In_Memory
{
    meta:
        description = "明文口令/凭据字段"
    strings:
        $p1 = "password" nocase
        $p2 = "passwd" nocase
        $p3 = "pwd=" nocase
        $p4 = "Authorization: Basic" nocase
        $p5 = "BEGIN RSA PRIVATE KEY"
        $p6 = "BEGIN OPENSSH PRIVATE KEY"
        $p7 = "NTLM" nocase
        $p8 = "wdigest" nocase
    condition:
        2 of them
}

rule LSASS_Dump_Artifacts
{
    meta:
        description = "LSASS 内存里的凭据结构痕迹"
    strings:
        $a1 = "msv1_0.dll" nocase
        $a2 = "wdigest.dll" nocase
        $a3 = "kerberos.dll" nocase
        $a4 = "livessp.dll" nocase
        $a5 = "dpapi.dll" nocase
    condition:
        all of them
}

rule Mimikatz_Strings
{
    meta:
        description = "Mimikatz / 凭据窃取工具特征"
    strings:
        $m1 = "sekurlsa::logonpasswords" nocase
        $m2 = "gentilkiwi" nocase
        $m3 = "mimikatz" nocase
        $m4 = "lsadump::sam" nocase
        $m5 = "privilege::debug" nocase
    condition:
        2 of them
}

rule CobaltStrike_Beacon
{
    meta:
        description = "Cobalt Strike beacon 常见字符串"
    strings:
        $c1 = "beacon.dll" nocase
        $c2 = "%s as %s\\%s: %d" ascii
        $c3 = "ReflectiveLoader" nocase
        $c4 = "sleeptime" nocase
        $c5 = "jitter" nocase
        $c6 = "MSSE-%d-server" ascii
    condition:
        2 of them
}

rule Powershell_Encoded
{
    meta:
        description = "PowerShell 编码命令（-enc / -e）"
    strings:
        $p1 = "-encodedcommand" nocase
        $p2 = "-enc " nocase
        $p3 = "FromBase64String" nocase
        $p4 = "IEX(" nocase
        $p5 = "Invoke-Expression" nocase
        $p6 = "DownloadString" nocase
        $p7 = "AMSI" nocase
    condition:
        2 of them
}

rule Process_Injection_Api
{
    meta:
        description = "进程注入 API 组合"
    strings:
        $a1 = "VirtualAllocEx"
        $a2 = "WriteProcessMemory"
        $a3 = "CreateRemoteThread"
        $a4 = "NtUnmapViewOfSection"
        $a5 = "QueueUserAPC"
        $a6 = "SetThreadContext"
    condition:
        2 of them
}

rule Suspicious_Network_IOC
{
    meta:
        description = "反弹 shell / C2 常见载荷字符串"
    strings:
        $n1 = "/bin/sh -i" ascii
        $n2 = "bash -i >& /dev/tcp/" ascii
        $n3 = "nc -e /bin/sh" ascii
        $n4 = "powershell -nop -w hidden" nocase
        $n5 = "cmd.exe /c" nocase
        $n6 = "meterpreter" nocase
    condition:
        any of them
}

rule Wallet_Or_Key_Material
{
    meta:
        description = "钱包/私钥/助记词（区块链题）"
    strings:
        $w1 = "-----BEGIN PRIVATE KEY-----"
        $w2 = "xprv" ascii
        $w3 = "mnemonic" nocase
        $w4 = "keystore" nocase
        $w5 = "wallet.dat"
    condition:
        any of them
}

rule Base64_Flag_Blob
{
    meta:
        description = "像 base64 编码的 flag"
    strings:
        $b1 = /ZmxhZ3t[A-Za-z0-9+\/]{8,}={0,2}/   // "flag{" 的 base64
        $b2 = /Y3Rme1[A-Za-z0-9+\/]{8,}={0,2}/   // "ctf{" 的 base64
    condition:
        any of them
}
