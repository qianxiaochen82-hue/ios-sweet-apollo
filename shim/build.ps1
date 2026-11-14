# Build the apollo shim with the Android NDK clang (no Linux/mkbootimg needed).
#
#   .\build.ps1                         # embed payload/known-good.bin behind Image
#   .\build.ps1 -Payload ..\x.bin       # same, other payload
#   .\build.ps1 -Mode ramdisk           # classic v2: payload in the boot ramdisk
#
# Embed mode appends the payload at the first 4K boundary after _end and grows
# both the arm64 header's image_size (Image+16) and the Android kernel_size, so
# ABL copies shim+payload together. loader.c looks for SWEETXNU there first and
# only then falls back to the ABL initrd.
param(
    [string]$Payload = "payload\known-good.bin",
    [ValidateSet("embed", "ramdisk")][string]$Mode = "embed",
    [string]$Out = "shim\out"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$ndk = $env:ANDROID_NDK_HOME
if (-not $ndk) { $ndk = Join-Path $env:LOCALAPPDATA "Android\Sdk\ndk\25.1.8937393" }
$bin = Join-Path $ndk "toolchains\llvm\prebuilt\windows-x86_64\bin"
$clang = Join-Path $bin "clang.exe"
$objcopy = Join-Path $bin "llvm-objcopy.exe"
$nm = Join-Path $bin "llvm-nm.exe"
$readelf = Join-Path $bin "llvm-readelf.exe"
foreach ($t in @($clang, $objcopy, $nm, $readelf)) {
    if (-not (Test-Path $t)) { throw "missing tool: $t" }
}
function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

New-Item -ItemType Directory -Force $Out | Out-Null

$CFLAGS = @("--target=aarch64-none-elf", "-O2", "-ffreestanding", "-nostdlib",
    "-fno-pic", "-mgeneral-regs-only", "-mstrict-align", "-fno-stack-protector",
    "-Wall", "-Wextra")
$srcs = @("start.S", "shim.c", "console.c", "mmu.c", "fdt.c", "loader.c", "ufs.c")
foreach ($f in $srcs) {
    $obj = Join-Path $Out ([IO.Path]::GetFileNameWithoutExtension($f) + ".o")
    & $clang @CFLAGS -c "shim\$f" -o $obj
    Check "compile $f"
}

# The image runs wherever ABL puts it with no relocation pass: only the header's
# image_size (start.o, linked at 0) may be an absolute address.
$objs = @("shim.o", "console.o", "mmu.o", "fdt.o", "loader.o", "ufs.o") |
    ForEach-Object { Join-Path $Out $_ }
$abs = @(& $readelf -r @objs | Select-String -SimpleMatch "ABS64").Count
if ($abs -ne 0) { throw "$abs absolute relocations in C objects" }

$elf = Join-Path $Out "shim.elf"
& $clang @CFLAGS -static -T shim\shim.ld -fuse-ld=lld "-Wl,--build-id=none" "-Wl,-N" `
    (Join-Path $Out "start.o") @objs -o $elf
Check "link"

$img = Join-Path $Out "Image"
& $objcopy -O binary $elf $img
Check "objcopy"

$nmLine = & $nm $elf | Select-String -Pattern "(^|\s)_end$"
if (-not $nmLine) { throw "_end not found in $elf" }
$size = [Convert]::ToUInt64((($nmLine.Line.Trim() -split "\s+")[0]), 16)

# Pad to _end so .bss/stacks exist as zeroed bytes (ABL copies image_size bytes).
$fs = [IO.File]::Open($img, "Open", "Write")
if ($fs.Length -gt $size) { $fs.Close(); throw "Image larger than _end ($($fs.Length) > $size)" }
$fs.SetLength($size)
$fs.Close()
$shimSize = $size

if ($Mode -eq "embed") {
    if (-not (Test-Path $Payload)) { throw "payload not found: $Payload" }
    $aligned = ($size + 0xfff) -band (-bnot 0xfff)
    $fs = [IO.File]::Open($img, "Open", "Write")
    $fs.SetLength($aligned)
    $fs.Close()
    $bytes = [IO.File]::ReadAllBytes($Payload)
    $fs = [IO.File]::Open($img, "Append", "Write")
    $fs.Write($bytes, 0, $bytes.Length)
    $fs.Close()
    $total = (Get-Item $img).Length
    $fs = [IO.File]::Open($img, "Open", "Write")
    $fs.Seek(16, "Begin") | Out-Null
    $fs.Write([BitConverter]::GetBytes([uint64]$total), 0, 8)
    $fs.Close()

    # Self-check: image_size == file length, SWEETXNU sits at the 4K boundary.
    $chk = [IO.File]::ReadAllBytes($img)
    $declared = [BitConverter]::ToUInt64($chk, 16)
    if ($declared -ne $total) { throw "image_size $declared != $total" }
    $magic = [Text.Encoding]::ASCII.GetString($chk, $aligned, 8)
    if ($magic -ne "SWEETXNU") { throw "no SWEETXNU at offset $aligned (got '$magic')" }
    Write-Host ("shim     {0} bytes, payload at 0x{1:x}, image {2} bytes" -f $shimSize, $aligned, $total)

    & python tools\mkemptyrd.py (Join-Path $Out "ramdisk.bin")
    Check "mkemptyrd"
    $rdOffset = "0x2800000"      # clear of shim+payload (~0x2040000)
} else {
    if (-not (Test-Path $Payload)) { throw "payload not found: $Payload" }
    Copy-Item $Payload (Join-Path $Out "ramdisk.bin") -Force
    Write-Host ("shim     {0} bytes, payload in ramdisk" -f $shimSize)
    $rdOffset = "0x1000000"
}

& python tools\mkbootimg_v2.py --header_version 2 --kernel $img `
    --ramdisk (Join-Path $Out "ramdisk.bin") --ramdisk_offset $rdOffset `
    --cmdline "console=null" --output (Join-Path $Out "shim-boot.apollo-$Mode.img")
Check "mkbootimg_v2"

$boot = Join-Path $Out "shim-boot.apollo-$Mode.img"
$len = (Get-Item $boot).Length
if ($len -gt 128MB) { throw "boot image $len exceeds 128 MiB" }
Write-Host ("boot     {0} ({1:N1} MiB)  mode={2}" -f $boot, ($len / 1MB), $Mode)
