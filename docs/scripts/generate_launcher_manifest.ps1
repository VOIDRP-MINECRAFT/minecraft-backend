param(
    [string]$PackRoot          = "E:\VoidRP\LauncherDist\pack",
    [string]$OutputFile        = "E:\VoidRP\LauncherDist\manifests\manifest.json",
    [string]$BaseUrl           = "https://void-rp.ru/launcher/pack",
    [string]$PackName          = "VoidRP Better MC 5",
    [string]$PackVersion       = "1.0.0",
    [string]$MinecraftVersion  = "1.21.1",
    [string]$Loader            = "neoforge",
    [int]   $JavaVersion       = 21,
    [string]$ServerHost        = "void-rp.ru",
    [int]   $ServerPort        = 25565,
    [string]$MinLauncherVersion    = "0.1.0",
    [string]$PackDisplayVersion    = "VOID-RP",
    [string]$LauncherProfileId     = "neoforge-21.1.218",
    [string]$NeoForgeVersion       = "21.1.218",
    [string]$FmlVersion            = "4.0.42",
    [string]$NeoFormVersion        = "20240808.144430"
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# MATCHING LOGIC
#
# Jar filename -> slug:
#   1. lowercase
#   2. strip version suffix (anything from first [-_+]digit onward)
#   3. strip trailing -forge/-neoforge/-fabric etc.
#   "sodium-0.5.8+mc1.21.1.jar"     -> "sodium"
#   "HoldMyItems-1.2.3-neoforge.jar" -> "holdmyitems"
#   "do-a-barrel-roll-1.0.jar"       -> "do-a-barrel-roll"
#
# Key -> normalised key for comparison:
#   lowercase, remove all spaces/hyphens/underscores
#   "Hold My Items"   -> "holdmyitems"
#   "Do a Barrel Roll"-> "doabarrelroll"
#   "entity-culling"  -> "entityculling"
#
# A key matches when:
#   normalise(slug) == normalise(key)           -- primary match
#   OR slug starts with key + '-' / '_'         -- prefix match for plain keys
# ---------------------------------------------------------------------------

$alwaysOverwritePrefixes = @( "config/fancymenu/" )

# Античит / авторизация -- отображаются на вкладке «Моды», но переключатель ЗАБЛОКИРОВАН (required=true)
$requiredLockedMods = [ordered]@{
    "FancyMod"          = @{ displayName = "FancyMod (Античит)";        description = "Обязательный античит-модуль. Нельзя отключить." }
    "AntiFraud"         = @{ displayName = "AntiFraud";                 description = "Обязательный модуль защиты. Нельзя отключить." }
    "VoidRP Auth"       = @{ displayName = "VoidRP Auth Bridge";        description = "Обязательный модуль авторизации. Нельзя отключить." }
    "VoidRP AuthBridge" = @{ displayName = "VoidRP Auth Bridge";        description = "Обязательный модуль авторизации. Нельзя отключить." }
}

# Опциональные моды -- отображаются с переключателем, который игрок может менять
$optionalMods = [ordered]@{

    # -- Производительность / рендеринг ----------------------------------------
    "Embeddium"                = @{ displayName = "Embeddium";                  description = "Увеличение FPS (порт Sodium для NeoForge)." }
    "Rubidium"                 = @{ displayName = "Rubidium";                   description = "Увеличение FPS (порт Sodium для Forge)." }
    "Sodium"                   = @{ displayName = "Sodium";                     description = "Увеличение FPS и оптимизация рендеринга." }
    "Oculus"                   = @{ displayName = "Oculus (Шейдеры)";           description = "Поддержка шейдерпаков (порт Iris для Forge)." }
    "Iris"                     = @{ displayName = "Iris Shaders";               description = "Поддержка шейдерпаков." }
    "Reeses Sodium Options"    = @{ displayName = "Reese's Sodium Options";     description = "Улучшенное меню настроек видео." }
    "Sodium Extra"             = @{ displayName = "Sodium Extra";               description = "Дополнительные настройки Sodium." }
    "Entity Culling"           = @{ displayName = "Entity Culling";             description = "Скрывает невидимые сущности для улучшения FPS." }
    "ImmediatelyFast"          = @{ displayName = "ImmediatelyFast";            description = "Оптимизация рендеринга GUI." }
    "FerriteCore"              = @{ displayName = "FerriteCore";                description = "Снижение потребления оперативной памяти." }
    "Ferrite Core"             = @{ displayName = "FerriteCore";                description = "Снижение потребления оперативной памяти." }
    "Memory Leak Fix"          = @{ displayName = "Memory Leak Fix";            description = "Исправляет утечки памяти в Minecraft." }
    "Dynamic FPS"              = @{ displayName = "Dynamic FPS";                description = "Снижает FPS когда игра свёрнута или не в фокусе." }
    "Exordium"                 = @{ displayName = "Exordium";                   description = "Оптимизация рендеринга интерфейса и HUD." }
    "Clumps"                   = @{ displayName = "Clumps";                     description = "Объединяет частицы опыта — меньше лагов на фермах." }
    "Krypton"                  = @{ displayName = "Krypton";                    description = "Оптимизация сетевого стека Minecraft." }
    "LazyDFU"                  = @{ displayName = "LazyDFU";                    description = "Ускорение запуска игры." }
    "Smooth Boot"              = @{ displayName = "Smooth Boot";                description = "Сглаживает нагрузку CPU при загрузке." }
    "ModernFix"                = @{ displayName = "ModernFix";                  description = "Комплексная оптимизация запуска и памяти." }
    "Noisium"                  = @{ displayName = "Noisium";                    description = "Ускорение генерации мира." }
    "Canary"                   = @{ displayName = "Canary";                     description = "Оптимизация логики сервера и клиента." }
    "Radon"                    = @{ displayName = "Radon";                      description = "Оптимизация движка освещения (Phosphor port)." }
    "Starlight"                = @{ displayName = "Starlight";                  description = "Полная переработка движка освещения." }

    # -- Мини-карта / карта мира -----------------------------------------------
    "Xaeros Minimap"           = @{ displayName = "Xaero's Minimap";            description = "Мини-карта с маркерами и синхронизацией с картой мира." }
    "Xaero Minimap"            = @{ displayName = "Xaero's Minimap";            description = "Мини-карта с маркерами и синхронизацией с картой мира." }
    "Xaeros World Map"         = @{ displayName = "Xaero's World Map";          description = "Полная карта мира с зумом и вейпоинтами." }
    "Xaero World Map"          = @{ displayName = "Xaero's World Map";          description = "Полная карта мира с зумом и вейпоинтами." }
    "JourneyMap"               = @{ displayName = "JourneyMap";                 description = "Карта мира и мини-карта в реальном времени." }
    "VoxelMap"                 = @{ displayName = "VoxelMap";                   description = "Мини-карта и карта мира." }

    # -- Просмотр рецептов -----------------------------------------------------
    "JEI"                      = @{ displayName = "JEI (Just Enough Items)";    description = "Просмотр рецептов крафта и применений предметов." }
    "Just Enough Items"        = @{ displayName = "JEI (Just Enough Items)";    description = "Просмотр рецептов крафта и применений предметов." }
    "Roughly Enough Items"     = @{ displayName = "REI (Roughly Enough Items)"; description = "Просмотр рецептов крафта." }
    "REI"                      = @{ displayName = "REI (Roughly Enough Items)"; description = "Просмотр рецептов крафта." }
    "EMI"                      = @{ displayName = "EMI";                        description = "Просмотр рецептов и менеджер крафтовых книг." }

    # -- HUD / интерфейс -------------------------------------------------------
    "Jade"                     = @{ displayName = "Jade";                       description = "Информация о блоках и сущностях при наведении." }
    "WAILA"                    = @{ displayName = "WAILA";                      description = "Информация о блоках при наведении." }
    "WTHIT"                    = @{ displayName = "WTHIT";                      description = "Информация о блоках при наведении." }
    "AppleSkin"                = @{ displayName = "AppleSkin";                  description = "Отображение сытости и восстановления здоровья от еды." }
    "Inventory HUD"            = @{ displayName = "Inventory HUD+";             description = "Дисплей инвентаря, зелий и брони прямо в игре." }
    "Durability Viewer"        = @{ displayName = "Durability Viewer";          description = "Прочность предметов в HUD." }
    "Status Effect Bars"       = @{ displayName = "Status Effect Bars";         description = "Полоски эффектов зелий в HUD." }
    "Chat Heads"               = @{ displayName = "Chat Heads";                 description = "Аватарки игроков рядом с их сообщениями в чате." }
    "Zoomify"                  = @{ displayName = "Zoomify";                    description = "Приближение камеры (как в OptiFine)." }
    "Ok Zoomer"                = @{ displayName = "Ok Zoomer";                  description = "Приближение камеры." }
    "Mouse Tweaks"             = @{ displayName = "Mouse Tweaks";               description = "Удобное управление инвентарём мышью." }
    "Better Ping Display"      = @{ displayName = "Better Ping Display";        description = "Показывает пинг в мс в списке игроков." }
    "Screenshot to Clipboard"  = @{ displayName = "Screenshot to Clipboard";    description = "Скриншоты копируются в буфер обмена." }
    "Mod Menu"                 = @{ displayName = "Mod Menu";                   description = "Список установленных модов в главном меню." }
    "Configured"               = @{ displayName = "Configured";                 description = "Настройка модов прямо из игры." }
    "Catalogue"                = @{ displayName = "Catalogue";                  description = "Экран списка модов с поиском." }
    "Controlify"               = @{ displayName = "Controlify";                 description = "Поддержка геймпадов." }
    "Simple Voice Chat"        = @{ displayName = "Simple Voice Chat";          description = "Голосовой чат в игре." }
    "Plasmo Voice"             = @{ displayName = "Plasmo Voice";               description = "Голосовой чат в игре." }

    # -- Визуальные / атмосфера ------------------------------------------------
    "LambDynamicLights"        = @{ displayName = "LambDynamicLights";          description = "Динамическое освещение от предметов в руках." }
    "Dynamic Lights"           = @{ displayName = "Dynamic Lights";             description = "Динамическое освещение от предметов в руках." }
    "Falling Leaves"           = @{ displayName = "Falling Leaves";             description = "Анимация опадающих листьев с деревьев." }
    "Sound Physics Remastered" = @{ displayName = "Sound Physics Remastered";   description = "Реалистичная физика и эхо звуков." }
    "Sound Physics"            = @{ displayName = "Sound Physics Remastered";   description = "Реалистичная физика и эхо звуков." }
    "Ambient Sounds"           = @{ displayName = "Ambient Sounds";             description = "Атмосферные звуки окружения в разных биомах." }
    "Presence Footsteps"       = @{ displayName = "Presence Footsteps";         description = "Реалистичные звуки шагов по материалу блока." }
    "Blur"                     = @{ displayName = "Blur";                       description = "Размытие фона при открытии меню." }
    "Not Enough Animations"    = @{ displayName = "Not Enough Animations";      description = "Дополнительные анимации от первого лица." }
    "First Person Model"       = @{ displayName = "First Person Model";         description = "Видимое тело от первого лица." }
    "Cosmetic Armor Reworked"  = @{ displayName = "Cosmetic Armor";             description = "Визуальная броня поверх основной (косметика)." }
    "Show Me Your Skin"        = @{ displayName = "Show Me Your Skin";          description = "Показывает скин под бронёй." }

    # -- Разное / QoL ----------------------------------------------------------
    "Hold My Items"            = @{ displayName = "Hold My Items";              description = "Сохраняет предметы из рук при смерти." }
    "Do a Barrel Roll"         = @{ displayName = "Do a Barrel Roll";           description = "Выполнение бочкового ролла при полёте." }
    "Carry On"                 = @{ displayName = "Carry On";                   description = "Переноска блоков и сущностей на руках." }
    "Enchantment Descriptions" = @{ displayName = "Enchantment Descriptions";   description = "Описания заклинаний на книгах и предметах." }
    "Toast Control"            = @{ displayName = "Toast Control";              description = "Управление всплывающими подсказками." }
    "Better F3"                = @{ displayName = "BetterF3";                   description = "Улучшенный экран F3 (debug)." }
    "BetterF3"                 = @{ displayName = "BetterF3";                   description = "Улучшенный экран F3 (debug)." }
    "Jade Addons"              = @{ displayName = "Jade Addons";                description = "Дополнительные модули для Jade." }
    "Just Enough Resources"    = @{ displayName = "Just Enough Resources";      description = "Отображение способов получения ресурсов в JEI." }
}

# Если мод попадает в этот список — он ИСКЛЮЧАЕТСЯ из манифеста (серверный)
$serverOnlyMods = @(
    "bukkit", "craftbukkit", "spigot", "paper", "purpur", "mohist",
    "arclight", "ketting", "luckperms", "essentialsx", "worldguard",
    "worldedit", "coreprotect", "plugmanx", "viaversion", "geyser",
    "bluemap", "dynmap", "authme", "nlogin"
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

function Get-RelativePath {
    param([string]$BasePath, [string]$TargetPath)
    $baseFull   = [System.IO.Path]::GetFullPath($BasePath)
    $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
    $baseUri    = [System.Uri]::new(($baseFull.TrimEnd('\') + '\'))
    $targetUri  = [System.Uri]::new($targetFull)
    return ([System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString()) -replace '\\', '/')
}

function Get-EncodedUrlPath {
    param([string]$RelativePath)
    return (($RelativePath -split '/') |
        ForEach-Object { [System.Uri]::EscapeDataString([string]$_) }) -join '/'
}

function Should-ExcludeFile {
    param([string]$RelativePath)
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { return $true }
    $n = $RelativePath.Replace('\', '/').TrimStart('/')
    foreach ($p in @(
        ".mixin.out/","logs/","log/","crash-reports/","screenshots/","saves/",
        "downloads/","tmp/","temp/","debug/","fancymenu_data/","local/",
        "dynamic-resource-pack-cache/","moddata/","moonlight-global-datapacks/",
        "patchouli_books/","server-resource-packs/","natives/","telemetry/",
        "journeymap/data/","xaeroworldmap/","xaerominimap/","xaero/","mods/.connector/"
    )) { if ($n.StartsWith($p, [System.StringComparison]::OrdinalIgnoreCase)) { return $true } }
    $fn = [System.IO.Path]::GetFileName($n)
    if ([string]::IsNullOrWhiteSpace($fn)) { return $true }
    foreach ($name in @(
        ".ds_store","thumbs.db","desktop.ini","usercache.json","servers.dat_old",
        "command_history.txt","patchouli_data.json","immersivetips.json","hash.txt"
    )) { if ($fn.Equals($name, [System.StringComparison]::OrdinalIgnoreCase)) { return $true } }
    foreach ($pat in @("*.tmp","*.bak","*.log","*.log.gz","*.info","*.pid",
        "win_event*.txt","renderer_pid*.tmp","successful_launch_pid*.tmp")
    ) { if ($fn -like $pat) { return $true } }
    return $false
}

function Should-AlwaysOverwrite {
    param([string]$RelativePath)
    $n = $RelativePath.Replace('\', '/').TrimStart('/')
    foreach ($p in $alwaysOverwritePrefixes) {
        if ($n.StartsWith($p, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

# Returns the slug of a jar: lowercase stem with version/loader suffixes stripped.
# "sodium-0.5.8+mc1.21.1.jar"      -> "sodium"
# "HoldMyItems-1.2.3-neoforge.jar" -> "holdmyitems"
# "do-a-barrel-roll-1.0.jar"       -> "do-a-barrel-roll"
function Get-ModSlug {
    param([string]$FileName)
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($FileName).ToLowerInvariant()
    $stem = [regex]::Replace($stem, '[-_+][0-9].*$', '')
    $stem = [regex]::Replace($stem, '[-_](forge|neoforge|fabric|quilt|mc\d.*)$', '')
    return $stem
}

# Compact form used for fuzzy comparison: all separators removed.
# "do-a-barrel-roll" -> "doabarrelroll"
# "Hold My Items"    -> "holdmyitems"
function Get-CompactSlug {
    param([string]$Value)
    return ($Value.ToLowerInvariant() -replace '[-_ ]', '')
}

function Get-ModClassification {
    param([string]$RelativePath)
    $n = $RelativePath.Replace('\', '/').TrimStart('/')
    if ($n -notmatch '^mods/[^/]+\.jar$') { return $null }

    $slug        = Get-ModSlug    -FileName ([System.IO.Path]::GetFileName($n))
    $compactSlug = Get-CompactSlug -Value $slug

    # Server-only check
    foreach ($key in $serverOnlyMods) {
        $ckey = Get-CompactSlug -Value $key
        if ($compactSlug -eq $ckey -or
            $slug -eq $key -or
            $slug.StartsWith($key + '-') -or $slug.StartsWith($key + '_')) {
            return @{ serverOnly = $true }
        }
    }

    # Matching helper: normalised-equal OR slug starts with plain key
    function Test-KeyMatch([string]$slug, [string]$compactSlug, [string]$key) {
        $ckey = Get-CompactSlug -Value $key
        return ($compactSlug -eq $ckey -or
                $slug -eq $key.ToLowerInvariant() -or
                $slug.StartsWith(($key.ToLowerInvariant()) + '-') -or
                $slug.StartsWith(($key.ToLowerInvariant()) + '_'))
    }

    # Required-locked (anti-cheat)
    foreach ($key in $requiredLockedMods.Keys) {
        if (Test-KeyMatch $slug $compactSlug $key) {
            return @{
                optional    = $true
                required    = $true
                displayName = $requiredLockedMods[$key].displayName
                description = $requiredLockedMods[$key].description
            }
        }
    }

    # Optional
    foreach ($key in $optionalMods.Keys) {
        if (Test-KeyMatch $slug $compactSlug $key) {
            return @{
                optional    = $true
                required    = $false
                displayName = $optionalMods[$key].displayName
                description = $optionalMods[$key].description
            }
        }
    }

    return $null  # required-hidden: always synced silently
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $PackRoot)) { throw "PackRoot not found: $PackRoot" }
$packRootFull = [System.IO.Path]::GetFullPath($PackRoot)
$outputDir    = Split-Path -Path $OutputFile -Parent
if (-not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$files              = New-Object System.Collections.Generic.List[object]
$processed          = 0; $skipped = 0; $errors = 0; $alwaysOverwriteCount = 0
$modsOptional       = New-Object System.Collections.Generic.List[string]
$modsRequiredLocked = New-Object System.Collections.Generic.List[string]
$modsRequiredHidden = New-Object System.Collections.Generic.List[string]
$modsServerOnly     = New-Object System.Collections.Generic.List[string]

Get-ChildItem -LiteralPath $packRootFull -Recurse -File -Force | ForEach-Object {
    $item = $_
    try {
        $rel = Get-RelativePath -BasePath $packRootFull -TargetPath $item.FullName
        if (Should-ExcludeFile -RelativePath $rel) { $skipped++; return }

        $cls = Get-ModClassification -RelativePath $rel
        if ($cls -ne $null -and $cls.serverOnly -eq $true) {
            $modsServerOnly.Add($rel) | Out-Null
            Write-Warning "EXCLUDED server-only: $rel"
            $skipped++; return
        }

        $hash  = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
        $url   = "$BaseUrl/$(Get-EncodedUrlPath -RelativePath $rel)"
        $entry = [PSCustomObject]@{ path = $rel; size = [int64]$item.Length; sha256 = $hash; url = $url }

        if (Should-AlwaysOverwrite -RelativePath $rel) {
            $entry | Add-Member -MemberType NoteProperty -Name alwaysOverwrite -Value $true
            $alwaysOverwriteCount++
        }

        if ($cls -ne $null -and $cls.optional -eq $true) {
            $entry | Add-Member -MemberType NoteProperty -Name optional    -Value $true
            $entry | Add-Member -MemberType NoteProperty -Name required    -Value ([bool]$cls.required)
            $entry | Add-Member -MemberType NoteProperty -Name displayName -Value $cls.displayName
            $entry | Add-Member -MemberType NoteProperty -Name description -Value $cls.description
            if ($cls.required) { $modsRequiredLocked.Add("$rel  ->  $($cls.displayName)") | Out-Null }
            else                { $modsOptional.Add("$rel  ->  $($cls.displayName)") | Out-Null }
        } else {
            if ($rel -match '^mods/[^/]+\.jar$') {
                $modsRequiredHidden.Add($rel) | Out-Null
            }
        }

        $files.Add($entry); $processed++
    }
    catch {
        $errors++
        Write-Warning "FAILED: $($item.FullName) -- $($_.Exception.Message)"
    }
}

# Неопознанные моды -- вывести с пометкой [?] чтобы добавить их в таблицу
foreach ($rel in $modsRequiredHidden) {
    $slug = Get-ModSlug -FileName ([System.IO.Path]::GetFileName($rel))
    Write-Host "  [?] неизвестный мод: $slug  ($rel)" -ForegroundColor DarkYellow
}

$sortedFiles = $files | Sort-Object path
$manifest = [PSCustomObject]@{
    packName           = $PackName
    packVersion        = $PackVersion
    packDisplayVersion = $PackDisplayVersion
    launcherProfileId  = $LauncherProfileId
    neoForgeVersion    = $NeoForgeVersion
    fmlVersion         = $FmlVersion
    neoFormVersion     = $NeoFormVersion
    buildDateUtc       = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    minecraftVersion   = $MinecraftVersion
    loader             = $Loader
    javaVersion        = $JavaVersion
    minLauncherVersion = $MinLauncherVersion
    fullSyncFallback   = $true
    notes              = "VoidRP launcher manifest for Better MC 5 NeoForge client"
    server             = [PSCustomObject]@{ host = $ServerHost; port = $ServerPort }
    files              = $sortedFiles
}

$manifest | ConvertTo-Json -Depth 20 | Set-Content -Path $OutputFile -Encoding UTF8

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  $OutputFile" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  Файлов: $processed обработано, $skipped пропущено, $errors ошибок"
Write-Host "  AlwaysOverwrite: $alwaysOverwriteCount   Всего: $($sortedFiles.Count)"
Write-Host ""

if ($modsRequiredLocked.Count -gt 0) {
    Write-Host "-- ЗАБЛОКИРОВАННЫЕ (отображаются на вкладке Моды, переключатель отключён) --" -ForegroundColor Yellow
    $modsRequiredLocked | Sort-Object | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    Write-Host ""
}
if ($modsOptional.Count -gt 0) {
    Write-Host "-- ОПЦИОНАЛЬНЫЕ (игрок может включить/выключить в лаунчере) ----------------" -ForegroundColor Green
    $modsOptional | Sort-Object | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
    Write-Host ""
}
if ($modsRequiredHidden.Count -gt 0) {
    Write-Host "-- ОБЯЗАТЕЛЬНЫЕ СКРЫТЫЕ (всегда синхронизируются, не видны на вкладке Моды) -" -ForegroundColor DarkGray
    $modsRequiredHidden | Sort-Object | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Write-Host ""
}
if ($modsServerOnly.Count -gt 0) {
    Write-Host "-- СЕРВЕРНЫЕ (исключены из манифеста) ---------------------------------------" -ForegroundColor Red
    $modsServerOnly | Sort-Object | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host ""
}

Write-Host "  Опциональных: $($modsOptional.Count)  |  Заблокированных: $($modsRequiredLocked.Count)  |  Скрытых: $($modsRequiredHidden.Count)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [?] — неопознанные моды выведены выше. Скопируй slug в `$optionalMods." -ForegroundColor DarkCyan
Write-Host ""
