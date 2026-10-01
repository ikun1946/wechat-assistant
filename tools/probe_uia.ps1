# probe_uia.ps1 -- Read-only probe: does the WeChat (Weixin) window expose a usable UIAutomation control tree?
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\probe_uia.ps1
# Notes: attaches as a standard UIA client (read-only). Sends nothing, clicks nothing, writes nothing.
# Keep this file ASCII-only (Windows PowerShell 5.1 reads non-BOM files as ANSI).

$ErrorActionPreference = 'Continue'

Write-Output '=== [1] load UIA assemblies ==='
try {
  Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop
  Add-Type -AssemblyName UIAutomationTypes -ErrorAction Stop
  Write-Output 'UIA assemblies loaded.'
} catch {
  Write-Output ('FAILED to load UIA assemblies: ' + $_.Exception.Message)
  exit 1
}

$AE = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]

Write-Output '=== [2] find Weixin/WeChat processes ==='
$procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'Weixin' -or $_.ProcessName -eq 'WeChat' }
if (-not $procs) { Write-Output 'No Weixin/WeChat process found. Start WeChat first.'; exit 0 }
$pids = @($procs | ForEach-Object { [int]$_.Id })
$procs | ForEach-Object { Write-Output ('process: {0} pid={1} mainHwnd={2}' -f $_.ProcessName, $_.Id, $_.MainWindowHandle) }

Write-Output '=== [3] list top-level windows owned by these processes ==='
$kids = $AE::RootElement.FindAll($scope::Children, [System.Windows.Automation.Condition]::TrueCondition)
$targets = @()
foreach ($k in $kids) {
  $pidOfK = -1
  try { $pidOfK = [int]$k.Current.ProcessId } catch { continue }
  if ($pids -notcontains $pidOfK) { continue }
  $nm = ''
  $cls = ''
  $hw = 0
  try { $nm = $k.Current.Name; $cls = $k.Current.ClassName; $hw = [int]$k.Current.NativeWindowHandle } catch {}
  Write-Output ('  pid={0} hwnd={1} class={2} name={3}' -f $pidOfK, $hw, $cls, $nm)
  if ($hw -ne 0) { $targets += @{ il = $k; pid = $pidOfK; name = $nm } }
}
if ($targets.Count -eq 0) { Write-Output 'No top-level window found (WeChat may be hidden in tray / not logged in).'; exit 0 }

# prefer named windows, then longer names (main window usually has a name)
$sorted = $targets | Sort-Object -Property @{ Expression = { if ($_.name) { 0 } else { 1 } } }, @{ Expression = { $_.name.Length }; Descending = $true }
$pick = @($sorted | Select-Object -First 4)

Write-Output '=== [4] walk control tree (ControlView, max depth 5, max 200 nodes per window) ==='
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
foreach ($t in $pick) {
  Write-Output ('--- window pid={0} name={1} ---' -f $t.pid, $t.name)
  $count = 0
  $maxNodes = 200
  $maxDepth = 5
  $q = New-Object System.Collections.Queue
  $q.Enqueue(@($t.il, 0))
  while ($q.Count -gt 0 -and $count -lt $maxNodes) {
    $item = $q.Dequeue()
    $el = $item[0]
    $d = $item[1]
    $count++
    try {
      $ctName = $el.Current.ControlType.ProgrammaticName -replace '^ControlType\.', ''
      $nm = $el.Current.Name
      if ($nm -and $nm.Length -gt 60) { $nm = $nm.Substring(0, 60) + '...' }
      Write-Output (('{0}{1} | name={2}' -f ('  ' * $d), $ctName, $nm))
      if ($d -lt $maxDepth) {
        $c = $walker.GetFirstChild($el)
        while ($null -ne $c) { $q.Enqueue(@($c, $d + 1)); $c = $walker.GetNextSibling($c) }
      }
    } catch {
      Write-Output '  <element read error>'
    }
  }
  Write-Output ('TOTAL_NODES: {0} (cap {1})' -f $count, $maxNodes)
  if ($count -ge 50) { Write-Output 'VERDICT: rich tree -> UIA route likely viable' }
  else { Write-Output 'VERDICT: sparse tree -> prefer vision/OCR route' }
}
Write-Output '=== done ==='
