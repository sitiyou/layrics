[English README](#layrics-english) · [中文 README](#layrics)

> [!NOTE]
> **免责声明／Disclaimer**
>
> 本项目的开发过程大量使用了 AI 辅助编程工具。代码可能存在未预料的行为或缺陷，请自行评估风险后使用。
>
> This project was developed with extensive use of AI-assisted coding tools. The code may contain unexpected behavior or bugs. Use at your own risk.

---

# layrics

layrics 是一款桌面歌词软件：从 MPRIS 兼容的播放器（Spotify、mpd 等）中获取播放状态，自动搜索并匹配当前歌曲的歌词，以卡拉 OK（逐字）或纯文本形式悬浮显示在桌面上。渲染基于 `wlr-layer-shell` 协议与 libass（ASS 字幕），支持 Sway、Hyprland、KDE Plasma 等 Wayland 合成器。

<video src="https://github.com/user-attachments/assets/aaeeeda9-e5b5-434f-95f4-e1daaa7d91a1" controls></video>




## 功能

- **MPRIS 集成**：自动发现并同步 MPRIS 兼容播放器（spotify、mpd 等），跟随播放状态自动切换歌词；(同时也提供对mpd的第一方支持)
- **多源歌词搜索**：跨 QQ 音乐（QM）、网易云音乐（NE）、酷狗（KG）、LRCLIB 多源并行搜索，自动匹配歌曲
- **Layer Shell 覆盖层**：基于 wlr-layer-shell 协议自动悬浮，无需在窗口管理器额外设置规则
- **libass 渲染**：支持 ASS 字幕全部特性，包括卡拉 OK（`\k`）、样式、字体和特效
- **硬件加速**：基于 Vulkan 提供 GPU 硬件加速
- **Aegisub 卡拉 OK 模板**：可选用 aegisub-cli 的 kara-templater 处理逐字歌词，实现高级卡拉 OK 效果
- **歌曲-歌词缓存**：匹配结果本地缓存
- **拖拽支持**：点击拖拽覆盖层重新定位字幕位置
- **右键菜单**：悬停字幕时右键弹出菜单（搜索歌词/显示/锁定/ASS 配置/帧率/播放器/缓存等）
- **IPC控制**：通过 `layctl` 命令行或脚本控制
- **可配置输出**：TOML 配置字体、颜色、定位、渲染模式、歌词轨道选择

## 安装

### 系统依赖

- `meson`、`pkg-config`
- `wayland`
- `vulkan`、`vulkan-headers`
- `shaderc`
- `libass`
- `fontconfig`
- `uv`

### 安装

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

## 使用

### 启动叠加层守护进程

```bash
layrics
```

守护进程会：
1. 连接 Wayland 并创建覆盖层 surface
2. 同时监测本机所有播放器，跟随正在播放的源
3. 轮询曲目变化并自动获取歌词

可选参数：
- `--socket, -s PATH`  — 自定义 IPC socket 路径（默认：`$XDG_RUNTIME_DIR/layrics.sock`）

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

# 交互式菜单：搜索歌曲 / 切换显示、锁定 / 修改 ASS 配置、帧率、播放器、缓存、状态
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

# 设置目标帧率
layctl set-fps 30
layctl set-fps -1   # vsync

# 查看当前状态
layctl status

# 歌曲-歌词缓存管理
layctl cache list
layctl cache set QM248672467   # 为当前曲目绑定歌词
layctl cache remove            # 删除当前曲目缓存

# 停止/重启 overlay 渲染（IPC 服务保持运行）
layctl stop
layctl start

# 运行时修改 ASS 渲染配置
layctl ass karaoke false
layctl ass line_mode single
layctl ass secondary toggle

# 查看当前 ASS 渲染配置
layctl ass-get
```

### 快捷键控制

#### overlay 内建快捷键（悬停歌词时捕获键盘）

> **WIP**：暂不支持自定义按键绑定。

悬停歌词时 overlay 捕获键盘，当前可用的内建快捷键：

| 按键 | 功能 |
|---|---|
| `Z` | 歌词推迟 100ms |
| `X` | 歌词提前 100ms |
| `C` | 重置延迟（重新对齐播放器当前位置） |

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

配置文件路径：`~/.config/layrics/config.toml`（或 `$LAYRICS_CONFIG_DIR/config.toml`）。

> 详细配置请参考 [examples/config.toml](https://github.com/sitiyou/layrics/blob/main/examples/config.toml)。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LAYRICS_DEBUG` | 启用调试日志。逗号分隔模块名 (`lyrics`, `main`, `match`, `assprovider`)，或 `core` 启用 C++ 调试日志 | 空 |
| `LAYRICS_CONFIG_DIR` | 配置文件目录 | `~/.config/layrics/` |
| `LAYRICS_SOCK` | IPC socket 路径 | `$XDG_RUNTIME_DIR/layrics.sock` |
| `LAYRICS_DMENU` | `layctl dmenu` 使用的菜单程序（覆盖 `[dmenu] program`） | `dmenu` |

## 歌词渲染

- **卡拉 OK**（`karaoke=true`）：逐字填色，`PrimaryColour` 为已唱色、`SecondaryColour` 为未唱色
- **单行模式**（`line_mode="single"`）：一行居中，可附带翻译/罗马音
- **双行模式**（`line_mode="double"`）：两行左右交替显示；启用 `advance_ms` 时提前显示为暗色，到播放时间点亮

歌词语言（日语/韩语/中文/英语）自动识别，并从 `[fonts]` 选择对应字体。

获取歌词时在所有配置的歌词源中搜索，按标题、时长、歌手相似度选出最佳匹配。

## 路线图

- [x] **Python 输入事件接口** — 将 overlay 接收到的键盘/鼠标事件封装为 Python 接口，支持在 Python 层面处理输入事件
- [x] **延迟控制** — 字幕延迟偏移功能（offset）
- [ ] **Aegisub CLI 集成** — 调用 aegisub-cli 处理 kara-templater 模板（`aegisub_karaoke` 配置，双行模式 + 逐字歌词时生效）
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

layrics is a desktop lyrics overlay: it fetches playback state from MPRIS-compatible players (Spotify, mpd, ...), automatically searches and matches lyrics for the current track, and floats karaoke (word-by-word) or plain-text lyrics on your desktop. Rendering is built on `wlr-layer-shell`, libass (ASS subtitles) and Vulkan GPU compositing, supported on Sway, Hyprland, KDE Plasma, etc.

<video src="https://github.com/user-attachments/assets/4b4c9c43-a00d-4ffd-9f7f-82a77b99e076" controls></video>

---

## Features

- **MPRIS integration**: auto-detects and syncs with MPRIS-compatible players (spotify, mpv, mpd, etc.), following play/pause/track changes (also provides first-party MPD support)
- **Multi-source lyric fetching**: parallel search across QQ Music (QM), NetEase (NE), Kugou (KG), LRCLIB with automatic song matching
- **Layer Shell overlay**: auto-floating layer based on `wlr-layer-shell`, no compositor-specific setup required
- **libass rendering**: supports ASS subtitle features including karaoke (`\k`), styling, fonts, and effects
- **Vulkan hardware acceleration**: GPU-accelerated rendering
- **Aegisub karaoke templating**: optionally processes word-timed lyrics through aegisub-cli's kara-templater for advanced karaoke effects
- **Song-to-lyrics cache**: local song match cache
- **Drag support**: click and drag the overlay to reposition subtitles
- **Right-click menu**: right-click the lyrics to open a menu (search songs / show / lock / ASS config / FPS / player / cache, etc.)
- **IPC control**: control via the `layctl` CLI or scripts
- **Configurable output**: TOML configuration for fonts, colors, positioning, render modes, and lyric track selection

## Installation

### System dependencies

- `meson`, `pkg-config`
- `wayland`
- `vulkan`, `vulkan-headers`
- `shaderc`
- `libass`
- `uv`

### Install

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

## Usage

### Start the overlay daemon

```bash
layrics
```

The daemon:
1. Connects to Wayland and creates an overlay surface
2. Watches all players on the machine, following the playing source
3. Polls for track changes and fetches lyrics automatically

Optional arguments:
- `--socket, -s PATH`  — custom IPC socket path (default: `$XDG_RUNTIME_DIR/layrics.sock`)

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

# Interactive menu: search songs / toggle visibility, lock / change ASS config, FPS, player, cache, status
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

# Set target frame rate
layctl set-fps 30
layctl set-fps -1   # vsync

# Get current status
layctl status

# Song-to-lyrics cache management
layctl cache list
layctl cache set QM248672467   # bind lyrics for current track
layctl cache remove            # remove current track's cache entry

# Stop/restart overlay rendering (IPC server keeps running)
layctl stop
layctl start

# Change ASS renderer config at runtime
layctl ass karaoke false
layctl ass line_mode single
layctl ass secondary toggle

# Show current ASS renderer config
layctl ass-get
```

### Hotkeys

#### Built-in hotkeys (the overlay captures the keyboard while hovering lyrics)

> **WIP**: custom key bindings are not supported yet.

| Key | Action |
|---|---|
| `Z` | delay lyrics by 100ms |
| `X` | advance lyrics by 100ms |
| `C` | reset the delay (re-align to the player's position) |

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

Configuration is loaded from `~/.config/layrics/config.toml` (or `$LAYRICS_CONFIG_DIR/config.toml`).

> See [examples/config.toml](https://github.com/sitiyou/layrics/blob/main/examples/config.toml) for the full configuration reference.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `LAYRICS_DEBUG` | Enable debug logging. Comma-separated module names (`lyrics`, `main`, `match`, `assprovider`), or `core` for C++ debug | unset |
| `LAYRICS_CONFIG_DIR` | Config directory | `~/.config/layrics/` |
| `LAYRICS_SOCK` | IPC socket path | `$XDG_RUNTIME_DIR/layrics.sock` |
| `LAYRICS_DMENU` | menu program used by `layctl dmenu` (overrides `[dmenu] program`) | `dmenu` |

## Lyrics rendering

- **Karaoke** (`karaoke=true`): syllable-by-syllable colour fill; `PrimaryColour` is the sung colour, `SecondaryColour` the upcoming one
- **Single line** (`line_mode="single"`): one centered line, optionally with a translation/romaji second line
- **Double line** (`line_mode="double"`): two lines shown side by side; with `advance_ms` they appear dimmed before their play time and light up when it starts

Lyrics language (Japanese/Korean/Chinese/English) is detected automatically and the matching font is picked from `[fonts]`.

When fetching, all configured lyric sources are searched and the best match is chosen by title, duration and artist similarity.

## Roadmap

- [x] **Python input event interface** — expose keyboard/mouse events from the overlay as Python interfaces for Python-level input handling
- [x] **Delay control** — subtitle delay offset
- [ ] **Aegisub CLI integration** — invoke aegisub-cli for kara-templater processing (`aegisub_karaoke` config, active in double-line mode with word-timed lyrics)
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
