[English README](#layrics-english) · [中文 README](#layrics)

> [!NOTE]
> **免责声明／Disclaimer**
>
> 本项目的开发过程大量使用了 AI 辅助编程工具。代码可能存在未预料的行为或缺陷，请自行评估风险后使用。
>
> This project was developed with extensive use of AI-assisted coding tools. The code may contain unexpected behavior or bugs. Use at your own risk.

---

# layrics

layrics 是一款桌面歌词软件：从 MPRIS 兼容的播放器（Spotify、mpd 等）中获取播放状态，自动搜索并匹配当前歌曲的歌词，以卡拉 OK（逐字）或纯文本形式悬浮显示在桌面上。通过 `wlr-layer-shell` 创建覆盖层，使用 libass 渲染 ASS 字幕，支持 Hook 的引擎通过 libplacebo 渲染逐字特效，支持 Sway、Hyprland、KDE Plasma 等 Wayland 合成器。

https://github.com/user-attachments/assets/6b443cf9-284a-4800-afc5-e7a7fb488092










## 功能

- **MPRIS 集成**：自动发现并同步 MPRIS 兼容播放器（spotify、mpd 等），跟随播放状态自动切换歌词；(同时也提供对mpd的第一方支持)
- **多源歌词搜索**：跨 QQ 音乐（QM）、网易云音乐（NE）、酷狗（KG）、LRCLIB 多源并行搜索，自动匹配歌曲
- **Layer Shell 覆盖层**：基于 wlr-layer-shell 协议自动悬浮，无需在窗口管理器额外设置规则
- **libass 渲染**：支持 ASS 字幕全部特性，包括卡拉 OK（`\k`）、样式、字体和特效
- **硬件加速**：基于 Vulkan 提供 GPU 硬件加速
- **卡拉 OK 模板**：默认在基础歌词样式上逐字扫色，支持切换光晕模板或普通 ASS
- **歌曲-歌词缓存**：匹配结果本地缓存
- **拖拽支持**：点击拖拽覆盖层重新定位字幕位置
- **右键菜单**：悬停字幕时右键弹出菜单（搜索歌词/显示/锁定/ASS 配置/帧率/播放器/缓存等）
- **系统托盘**：托盘图标（StatusNotifierItem）左键切换歌词显隐，右键菜单与歌词右键一致
- **歌词显隐动画**：显示/隐藏覆盖层时播放转场动画（淡入淡出、上浮、缩放、逐字错峰等 11 种）
- **IPC控制**：通过 `layctl` 命令行或脚本控制
- **可配置输出**：TOML 配置字体、颜色、定位、渲染模式、歌词轨道选择

## 安装

### 系统依赖

- C/C++ 编译器、`pkg-config`
- `wayland`
- `vulkan`、`vulkan-headers`
- `shaderc`
- `libplacebo >= 6.338` (Vulkan)
- `libass`
- `fontconfig`
- `uv`

`asslayer` 当前以源码包分发，安装时会编译叠加引擎，因此需要上述库的开发头文件。layrics 本身是纯 Python 包。

### 安装

layrics 使用 Python 3.14 或更新版本。源码安装会从 PyPI 安装 kara-templater 1.2.2 或更新的兼容版本。

```bash
# uv / pipx
uv tool install git+https://github.com/sitiyou/layrics
pipx install git+https://github.com/sitiyou/layrics

# AUR
yay -S layrics-git
paru -S layrics-git

# install from source
git clone https://github.com/sitiyou/layrics
cd layrics
uv tool install .
```

叠加引擎由独立依赖 `asslayer>=0.2.0,<0.3.0` 提供，安装时自动从 PyPI 获取，无需单独克隆引擎仓库。Wayland layer namespace 保持为 `layrics`，已有合成器规则无需修改。

## 使用

### 启动叠加层守护进程

```bash
layrics
```

守护进程会：
1. 连接 Wayland 并创建覆盖层 surface
2. 同时监测本机所有播放器，跟随正在播放的源
3. 轮询曲目变化并自动获取歌词
4. 在系统托盘显示图标：左键切换歌词显隐，右键打开操作菜单

可选参数：
- `--socket, -s PATH`  — 自定义当前用户专用的 IPC socket 路径（默认：`$XDG_RUNTIME_DIR/layrics.sock`）

### 使用 layctl 控制

```bash
# 列出可用播放源
layctl players

# 固定跟随某个播放源（bus name 或 "mpd"），传 auto 恢复自动
layctl set-player org.mpris.MediaPlayer2.mpd
layctl set-player auto

# 搜索歌曲
layctl search "Eternal Feather"

# 获取指定歌曲的 ASS 内容
layctl fetch QM248672467

# 获取当前曲目歌词的 ASS 内容
layctl fetch

# 设置当前曲目的歌词并更新缓存
layctl set-lrc QM248672467

# 交互式菜单：搜索歌曲 / 切换显示、锁定 / 复位拖拽 / 修改 ASS 配置、帧率、播放器、缓存、状态
layctl dmenu

# 显示/隐藏覆盖层
layctl hide              # 隐藏（默认）
layctl hide true         # 隐藏
layctl hide false        # 显示
layctl hide toggle       # 切换可见性
layctl unhide            # 等同于 hide false

# 锁定/解锁（锁定后鼠标点击穿透）
layctl lock              # 锁定（默认）
layctl lock true         # 锁定
layctl lock false        # 解锁
layctl lock toggle       # 切换锁定状态
layctl unlock            # 等同于 lock false

# 复位拖拽偏移
layctl reset

# 设置目标帧率
layctl set-fps 30
layctl set-fps -1   # vsync

# 查看当前状态
layctl status

# 歌曲-歌词缓存管理
layctl cache list
layctl cache set QM248672467   # 为当前曲目绑定歌词
layctl cache remove            # 删除当前曲目缓存

# 运行时修改 ASS 渲染配置
layctl ass karaoke false
layctl ass line_mode single
layctl ass secondary toggle

# 查看当前 ASS 渲染配置
layctl ass-get
```

`layctl` 等待命令完成后返回，搜索或获取歌词较慢时可按 Ctrl+C 取消等待。保存 ASS 文件可用 `layctl fetch > lyrics.ass`。

### 快捷键控制

#### overlay 内建快捷键（悬停歌词时捕获键盘）

> **WIP**：暂不支持自定义按键绑定。

悬停歌词时 overlay 捕获键盘，当前可用的内建快捷键：

| 按键 | 功能 |
|---|---|
| `Z` | 歌词推迟 100ms |
| `X` | 歌词提前 100ms |
| `C` | 重置延迟（重新对齐播放器当前位置） |
| `R` | 复位拖拽偏移 |

> 延迟按歌曲保存，再次播放同一首歌时自动恢复，且 seek / 暂停 / 播放切换后保持。

仅当指针悬停在歌词区域时按键才生效，移出歌词区域后按键恢复正常。

#### 通过桌面环境绑定（Hyprland 示例）

以Hyprland为例，示例快捷键如下：
```lua
-- 长按左ctrl控制锁定，长按左alt控制显示/隐藏，SUPER + SHIFT + M 打开操作菜单
hl.bind("Control_L", hl.dsp.exec_cmd [[layctl lock toggle]], { long_press = true })
hl.bind("Alt_L", hl.dsp.exec_cmd [[layctl hide toggle]], { long_press = true })
hl.bind("SUPER + SHIFT + M", hl.dsp.exec_cmd [[layctl dmenu]])
```

## 配置

配置文件路径：`~/.config/layrics/config.toml`（可通过 `XDG_CONFIG_HOME` 改变配置根目录，或用 `LAYRICS_CONFIG_DIR` 直接指定 layrics 的配置目录）。

> 详细配置请参考 [examples/config.toml](examples/config.toml)。

默认的 `gradient-outline` 根据逐字时间把字面从基础 ASS 的 `SecondaryColour` 扫到 `PrimaryColour`，扫色前沿略微弯曲，带起一道窄亮边；扫到的字轻轻上浮后落回原位。待唱和唱完时都沿用基础样式的字色和描边。渲染设置继承自 `[assprovider.default]`。

本地开发时，将 layrics、asslayer 和 kara-templater 检出到同一父目录。编译支持 Hook 的本地 asslayer 还需要 libplacebo ≥ 6.338 的开发文件。在 layrics 目录运行：

```sh
uv sync --locked
uv pip install --python .venv/bin/python --reinstall --no-deps ../asslayer ../kara-templater
.venv/bin/layrics
```

引擎缺少 Hook 输入时，逐字歌词自动使用原生 ASS 扫色。如果重新运行了 `uv sync`，请再执行上面的 `uv pip install`。播放逐字歌词时，日志中的 `Loaded libplacebo Hook` 表示引擎已载入 Hook。

`layctl load song.hook` 可载入外部 Hook，`layctl fetch > lyrics.ass` 导出原生 ASS。逐行歌词、无时间轴提示和关闭扫色时均使用基础 ASS。逐字歌词导出到 ASS 时保留原生扫色。解锁后可按住可见的 Hook 歌词拖动。若要使用原版单层 ASS，可显式设置 `provider = "default"`；若要使用旧版光晕模板，可显式选择：

```toml
[assprovider]
provider = "kara-templater"
```

修改后重启 layrics。`kara-templater` 1.2.2 或更新的兼容版本随应用安装，支持单行和双行模式；非逐字歌词或关闭 `karaoke` 时使用普通 ASS 输出。
逐词时间直接来自歌词源，排版使用 kara-templater 的结构化字词与注音接口。每个可见词或注音生成四条原生 ASS 事件，数量与音符时长无关。光晕模板包含四层光晕／轮廓、音节缩放脉冲和变速扫光；主色取主歌词的 `PrimaryColour`，光晕颜色自动派生。单行模式的副歌词配色沿用 `[style.secondary]`，字间距、描边和模糊按字号比例缩放，保留自身字体、字号及位置，不带动画。模板的 `spacing` 控制字间距，默认为 `5`。
它继承 `[assprovider.default]` 的渲染设置，可在 `[assprovider.kara-templater]` 中覆盖；特效参数放在 `[assprovider.kara-templater.template]`。`layctl ass` 和右键菜单修改当前 provider 的设置。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LAYRICS_DEBUG` | 启用调试日志。逗号分隔模块名 (`lyrics`, `main`, `match`, `assprovider`)；`core` 自动设置 `ASSLAYER_DEBUG=1` 启用叠加引擎日志 | 空 |
| `LAYRICS_CONFIG_DIR` | 配置文件目录 | `~/.config/layrics/` |
| `LAYRICS_SOCK` | IPC socket 路径 | `$XDG_RUNTIME_DIR/layrics.sock` |
| `LAYRICS_DMENU` | `layctl dmenu` 使用的菜单程序（覆盖 `[dmenu] program`） | `dmenu` |

## 歌词渲染

- **卡拉 OK**（`karaoke=true`）：逐字扫色，普通 ASS provider 用 `SecondaryColour` 作为扫色前的填充，用 `PrimaryColour` 作为扫色后的填充
- **单行模式**（`line_mode="single"`）：一行居中，可附带翻译/罗马音
- **双行模式**（`line_mode="double"`）：两行左右交替显示；启用 `advance_ms` 时提前显示为暗色，到播放时间点亮

自动识别歌词语言后，优先使用 `[fonts]` 的语言字体，其次是对应轨道显式设置的 `font_name`，最后使用 `fonts.default`。

获取歌词时在所有配置的歌词源中搜索，按标题、时长、歌手相似度选出最佳匹配。

## 路线图

- [x] **Python 输入事件接口** — 将 overlay 接收到的键盘/鼠标事件封装为 Python 接口，支持在 Python 层面处理输入事件
- [x] **延迟控制** — 字幕延迟偏移功能（offset）
- [x] **卡拉 OK 模板 provider** — 使用 kara-templater 生成模板特效字幕
- [ ] **自定义配置快捷键支持** — 支持用户自定义快捷键绑定（当前为内置快捷键）

---

## 参考致谢

- [Waifuland](https://github.com/shinkuan/Waifuland) — 拖拽实现与全局光标获取的参考
- [wob](https://github.com/francma/wob) — wlr-layer-shell C 实现，架构与结构体设计参考
- [waynav](https://github.com/kovetskiy/waynav) — 输入区域管理的参考
- [LDDC](https://github.com/chenmozhijin/LDDC) — 多源歌词搜索与获取库
- [waylyrics](https://github.com/waylyrics/waylyrics) — 功能设计与整体思路的灵感来源

---

# layrics (English)

---

layrics is a desktop lyrics overlay: it fetches playback state from MPRIS-compatible players (Spotify, mpd, ...), automatically searches and matches lyrics for the current track, and floats karaoke (word-by-word) or plain-text lyrics on your desktop. The overlay uses `wlr-layer-shell` and Vulkan, with libass for ASS subtitles and libplacebo for word-timed effects on Hook-capable engines. Supported compositors include Sway, Hyprland and KDE Plasma.

https://github.com/user-attachments/assets/6b443cf9-284a-4800-afc5-e7a7fb488092

---

## Features

- **MPRIS integration**: auto-detects and syncs with MPRIS-compatible players (spotify, mpv, mpd, etc.), following play/pause/track changes (also provides first-party MPD support)
- **Multi-source lyric fetching**: parallel search across QQ Music (QM), NetEase (NE), Kugou (KG), LRCLIB with automatic song matching
- **Layer Shell overlay**: auto-floating layer based on `wlr-layer-shell`, no compositor-specific setup required
- **libass rendering**: supports ASS subtitle features including karaoke (`\k`), styling, fonts, and effects
- **Vulkan hardware acceleration**: GPU-accelerated rendering
- **Karaoke templates**: timed word wipes in the base lyric style by default, with a glow template and plain ASS also available
- **Song-to-lyrics cache**: local song match cache
- **Drag support**: click and drag the overlay to reposition subtitles
- **Right-click menu**: right-click the lyrics to open a menu (search songs / show / lock / ASS config / FPS / player / cache, etc.)
- **System tray**: tray icon (StatusNotifierItem); left click toggles the overlay, right click opens the same menu as the in-overlay right click
- **Show/hide animation**: transition effects when the overlay appears or disappears (fade, rise, zoom, per-glyph stagger, 11 effects in total)
- **IPC control**: control via the `layctl` CLI or scripts
- **Configurable output**: TOML configuration for fonts, colors, positioning, render modes, and lyric track selection

## Installation

### System dependencies

- A C/C++ compiler, `pkg-config`
- `wayland`
- `vulkan`, `vulkan-headers`
- `shaderc`
- `libplacebo >= 6.338` (Vulkan)
- `libass`
- `fontconfig`
- `uv`

`asslayer` currently ships as a source distribution, so installation compiles the overlay engine and requires development headers for the libraries above. Layrics itself is a pure Python package.

### Install

Layrics uses Python 3.14 or later. A source installation installs kara-templater 1.2.2 or a compatible newer release from PyPI.

```bash
# uv / pipx
uv tool install git+https://github.com/sitiyou/layrics
pipx install git+https://github.com/sitiyou/layrics

# AUR
yay -S layrics-git
paru -S layrics-git

# install from source
git clone https://github.com/sitiyou/layrics
cd layrics
uv tool install .
```

The overlay engine is provided by the independent dependency `asslayer>=0.2.0,<0.3.0`, fetched automatically from PyPI during installation. No separate engine checkout is needed. The Wayland layer namespace remains `layrics`, so existing compositor rules continue to apply.

## Usage

### Start the overlay daemon

```bash
layrics
```

The daemon:
1. Connects to Wayland and creates an overlay surface
2. Watches all players on the machine, following the playing source
3. Polls for track changes and fetches lyrics automatically
4. Shows a system tray icon: left click toggles the overlay, right click opens the menu

Optional arguments:
- `--socket, -s PATH`  — custom path for the user-only IPC socket (default: `$XDG_RUNTIME_DIR/layrics.sock`)

### Control with layctl

```bash
# List available sources
layctl players

# Pin a source (a bus name or "mpd"); pass auto to follow the playing one
layctl set-player org.mpris.MediaPlayer2.mpd
layctl set-player auto

# Search for songs
layctl search "Eternal Feather"

# Fetch ASS content for a specific song
layctl fetch QM248672467

# Fetch ASS content for the current track
layctl fetch

# Set lyrics for current track and update cache
layctl set-lrc QM248672467

# Interactive menu: search songs / toggle visibility, lock / reset drag / change ASS config, FPS, player, cache, status
layctl dmenu

# Show/hide overlay
layctl hide              # hide (default)
layctl hide true         # hide
layctl hide false        # show
layctl hide toggle       # toggle visibility
layctl unhide            # alias for hide false

# Lock/unlock (locked = click-through)
layctl lock              # lock (default)
layctl lock true         # lock
layctl lock false        # unlock
layctl lock toggle       # toggle lock
layctl unlock            # alias for lock false

# Reset the drag offset
layctl reset

# Set target frame rate
layctl set-fps 30
layctl set-fps -1   # vsync

# Get current status
layctl status

# Song-to-lyrics cache management
layctl cache list
layctl cache set QM248672467   # bind lyrics for current track
layctl cache remove            # remove current track's cache entry

# Change ASS renderer config at runtime
layctl ass karaoke false
layctl ass line_mode single
layctl ass secondary toggle

# Show current ASS renderer config
layctl ass-get
```

`layctl` waits for commands to complete; press Ctrl+C to stop waiting if a search or lyric fetch takes too long. Use `layctl fetch > lyrics.ass` to save the ASS output.

### Hotkeys

#### Built-in hotkeys (the overlay captures the keyboard while hovering lyrics)

> **WIP**: custom key bindings are not supported yet.

| Key | Action |
|---|---|
| `Z` | delay lyrics by 100ms |
| `X` | advance lyrics by 100ms |
| `C` | reset the delay (re-align to the player's position) |
| `R` | reset the drag offset |

> The delay is saved per song and restored when the song plays again, and survives seeking / pausing / play-pause switching.

The keys only apply while the pointer hovers the lyrics; they return to normal after the pointer leaves.

#### Desktop keybindings (Hyprland example)

Example Hyprland keybindings:

```lua
-- Long-press Left Ctrl to toggle lock, Left Alt to toggle hide/show, SUPER + SHIFT + M to open the action menu
hl.bind("Control_L", hl.dsp.exec_cmd [[layctl lock toggle]], { long_press = true })
hl.bind("Alt_L", hl.dsp.exec_cmd [[layctl hide toggle]], { long_press = true })
hl.bind("SUPER + SHIFT + M", hl.dsp.exec_cmd [[layctl dmenu]])
```

## Configuration

Configuration is loaded from `~/.config/layrics/config.toml` (respecting `XDG_CONFIG_HOME`, with `LAYRICS_CONFIG_DIR` overriding the layrics directory).

> See [examples/config.toml](examples/config.toml) for the full configuration reference.

The default `gradient-outline` provider wipes each timed word from the base ASS style’s `SecondaryColour` to its `PrimaryColour`, with a curved leading edge and a brief glint. Each glyph lifts slightly as the front passes, then settles into the base style. Rendering options inherit from `[assprovider.default]`.

For local Hook development, check out asslayer and kara-templater alongside layrics. Building this asslayer checkout also requires libplacebo ≥ 6.338 development files. From the layrics directory run:

```sh
uv sync --locked
uv pip install --python .venv/bin/python --reinstall --no-deps ../asslayer ../kara-templater
.venv/bin/layrics
```

An engine without Hook input uses native ASS karaoke for word-timed lyrics. After another `uv sync`, repeat the `uv pip install` step. During word-timed playback, the engine logs `Loaded libplacebo Hook` when the Hook loads successfully.

Use `layctl load song.hook` to load an external Hook and `layctl fetch > lyrics.ass` to export native ASS. Line-timed lyrics, the untimed-lyrics hint and playback with karaoke disabled use the base ASS style. ASS exports preserve native karaoke timing for word-timed lyrics. Drag visible Hook lyrics while the overlay is unlocked. Set `provider = "default"` for the original single-layer plain ASS, or select the older glow template explicitly:

```toml
[assprovider]
provider = "kara-templater"
```

Restart layrics after changing the provider. `kara-templater` 1.2.2 or a compatible newer version is installed with the application and supports single- and double-line modes. Non-word-timed lyrics, or disabling `karaoke`, use ordinary ASS output.
Word clocks come directly from the lyric source. The provider uses kara-templater’s structured word and ruby layout and emits four native ASS events per visible word or reading, independent of note duration. The glow template combines four glow/outline layers, syllable scale pulses, and a variable-speed highlight sweep. Its main colour follows the primary lyric style's `PrimaryColour`, with glow colours derived automatically. In single-line mode, secondary lyrics use the colours from `[style.secondary]`, with spacing, border widths, and blur scaled to their font size. They retain their own font, size, and position, without animation. The template's `spacing` controls character spacing and defaults to `5`.
It inherits rendering settings from `[assprovider.default]`; override them in `[assprovider.kara-templater]` and configure effects in `[assprovider.kara-templater.template]`. `layctl ass` and the context menu update the current provider's settings.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `LAYRICS_DEBUG` | Enable debug logging. Comma-separated module names (`lyrics`, `main`, `match`, `assprovider`); `core` automatically sets `ASSLAYER_DEBUG=1` for engine debug logs | unset |
| `LAYRICS_CONFIG_DIR` | Config directory | `~/.config/layrics/` |
| `LAYRICS_SOCK` | IPC socket path | `$XDG_RUNTIME_DIR/layrics.sock` |
| `LAYRICS_DMENU` | menu program used by `layctl dmenu` (overrides `[dmenu] program`) | `dmenu` |

## Lyrics rendering

- **Karaoke** (`karaoke=true`): syllable-by-syllable colour fill. The plain ASS provider uses `SecondaryColour` before the wipe and `PrimaryColour` after it
- **Single line** (`line_mode="single"`): one centered line, optionally with a translation/romaji second line
- **Double line** (`line_mode="double"`): two lines shown side by side; with `advance_ms` they appear dimmed before their play time and light up when it starts

Font selection uses the detected language’s entry in `[fonts]`, then the track’s explicit `font_name`, then `fonts.default`.

When fetching, all configured lyric sources are searched and the best match is chosen by title, duration and artist similarity.

## Roadmap

- [x] **Python input event interface** — expose keyboard/mouse events from the overlay as Python interfaces for Python-level input handling
- [x] **Delay control** — subtitle delay offset
- [x] **Karaoke template provider** — generate template effects with kara-templater
- [ ] **Configurable custom hotkeys** — user-configurable key bindings (currently built-in only)

## License

GNU General Public License v3.0 only

---

## Credits

- [Waifuland](https://github.com/shinkuan/Waifuland) — reference for drag implementation and global cursor tracking
- [wob](https://github.com/francma/wob) — wlr-layer-shell C implementation, architecture and struct design reference
- [waynav](https://github.com/kovetskiy/waynav) — reference for input region management
- [LDDC](https://github.com/chenmozhijin/LDDC) — multi-source lyric search and fetching library
- [waylyrics](https://github.com/waylyrics/waylyrics) — inspiration for feature design and overall approach
