# Создаёт ярлыки с иконками на рабочем столе. Запускается через make_shortcuts.bat
$scripts = Split-Path -Parent $MyInvocation.MyCommand.Path
$root    = Split-Path -Parent $scripts
$desktop = [Environment]::GetFolderPath("Desktop")
$ws      = New-Object -ComObject WScript.Shell

$items = @(
  @{ Name = "Farcipal Bot";       Bat = "run_bot.bat";        Icon = "bot.ico"   },
  @{ Name = "Farcipal Web";       Bat = "run_web.bat";        Icon = "web.ico"   },
  @{ Name = "Telegram Login";     Bat = "login_telegram.bat"; Icon = "login.ico" },
  @{ Name = "VK Check";           Bat = "check_vk.bat";       Icon = "check.ico" },
  @{ Name = "Farcipal Setup";     Bat = "setup.bat";          Icon = "setup.ico" }
)

foreach ($i in $items) {
  $path = Join-Path $desktop ($i.Name + ".lnk")
  $lnk  = $ws.CreateShortcut($path)
  $lnk.TargetPath       = Join-Path $scripts $i.Bat
  $lnk.WorkingDirectory = $root
  $lnk.IconLocation     = (Join-Path $scripts ("icons\" + $i.Icon)) + ",0"
  $lnk.Description      = $i.Name
  $lnk.Save()
  Write-Host ("Создан ярлык: " + $path)
}
