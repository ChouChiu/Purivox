# Purivox

<p align="left">
  <strong>简体中文</strong> · <a href="README_EN.md">English</a>
</p>

**[▶ 在浏览器中直接使用](https://purivox.wwchun.top/)**——无需安装，
音频全程留在你自己的标签页里，不会上传到服务器。

Purivox 是一款面向舞台和现场录音的垫音消除工具，有桌面版和浏览器版两种形态，
基于 Python、PySide6 和 PySide6-Fluent-Widgets 开发。核心的 MR Remove 功能支持两种处理方式：

- **单曲垫音消除**：提供舞台 / 现场音频和对应的歌曲音源，程序自动完成同步并去除垫音。
- **整场垫音消除**：提供整场舞台 / 现场音频和多个歌曲音源，
  程序自动定位每首歌出现的位置并分段去除垫音。

垫音消除只处理歌曲音源能够解释的内容，因此会保留音源中没有的现场人声、讲话、欢呼和环境声。
歌曲音源越准确，效果越好；录音削波、明显混响、编曲不同或选错音源，都会影响结果。

需要不依赖歌曲音源的两轨分离，请使用
[Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui)
这类专门的工具，Purivox 只做参考对消。

## 主要功能

- Fluent Design 桌面界面，支持浅色、深色和跟随系统主题
- 中文、英文、日语和韩语界面即时切换
- 全局时间对齐、局部时钟漂移跟踪和基于参考的相干对消
- 整场录音歌曲识别、重复片段识别和可编辑的处理范围
- 长音频分块处理、任务取消和安全的原子写入
- 导出沿用输入文件的采样率与位深，不为凑规格而升采样
- 处理完成后可在应用内试听并查看音频统计信息
- 设置页可检查新版本，有更新时弹窗显示 Changelog 并跳转 Release 页面，不做自动更新
- 每次运行都写入按日期命名的日志文件，未处理的异常会自动打开当天日志并提示提交 Issue
- 常用操作有快捷键：`Ctrl+O` 选择输入、`Ctrl+Return` 开始、
  `F5` 识别歌曲、`Esc` 取消、`Ctrl+P` 试听播放 / 暂停
- 可以直接从 YouTube / YouTube Music 链接获取音源，下载过的文件会记录下来供反复选用
- 图形界面与命令行共用同一套 MR Remove 处理管线

## 安装

不想安装可以直接用[浏览器版](https://purivox.wwchun.top/)：
它跑的是同一套处理管线，只是受浏览器内存上限约束，整场录音过长时会被拒绝。
详见[浏览器版（WebAssembly）](docs/web.md)。

桌面版可以直接从 [Release 页面](https://github.com/ChouChiu/Purivox/releases/latest)
下载：Windows 用 `Purivox.exe`，Linux 用 `.deb`、`.rpm` 或自解压的
`purivox-linux-x86_64.tar.gz`，macOS 用 `purivox-macos-arm64.tar.gz`（Apple Silicon）
或 `purivox-macos-x86_64.tar.gz`（Intel），每次发布都附带 `SHA256SUMS`。

macOS 版解压得到 `Purivox.app`，拖进“应用程序”即可；它只有 ad-hoc 签名，没有 Apple 开发者签名，
所以第一次打开要在访达里右键选“打开”。

从源码运行需要先安装 [uv](https://docs.astral.sh/uv/)。
项目会根据 `.python-version` 自动选择 Python 版本，
并在仓库内维护隔离环境。请不要在该环境中安装其他会导出 `qfluentwidgets` 的 Qt Fluent 组件。

```bash
uv sync --locked
```

启动图形界面：

```bash
uv run --locked purivox
```

## 图形界面使用方法

### 单曲垫音消除

1. 打开“垫音消除”，选择“单曲”。
2. 选择要处理的舞台 / 现场音频，以及内容对应的歌曲音源。
3. 程序会自动对齐。建议先用默认的 75% 强度处理，图形界面使用固定的统计窗口。
4. 在“导出内容”中选择要保存的音轨：仅消音结果、仅垫音，或两者。垫音轨是舞台 / 现场音频
   减去消音结果，因此带着垫音在舞台上的实际音量，两轨相加即还原原始录音。
5. 试听结果后再调整强度。如果声音出现明显的抽吸感，或人声变薄，
   请降低强度，或确认歌曲音源选择是否正确。

请尽量使用与现场一致的歌曲版本。母带不同、经过剪辑、变速、升降调或包含额外内容，都会降低消除效果。

### 整场垫音消除

1. 在“垫音消除”中选择“整场”，载入整场舞台 / 现场音频。
2. 添加可能在整场录音中出现的歌曲音源；文件顺序不影响识别。
3. 点击“识别歌曲”，检查完整歌曲、短片段、未识别区间和匹配度。
4. 必要时双击修改录音时间或音源范围，也可以取消勾选不想处理的片段。
5. 确认保存位置、导出内容和处理选项后，开始处理整场录音。

未识别区间会按原样保留，时长不变，因此串场讲话、观众互动、广告和空场不会被自动剪掉。整场处理
目前只在图形界面中提供。

### 从链接获取音源

单曲页的两个文件行和整场页的舞台音频、音源列表都带有「获取」按钮：

1. 粘贴 YouTube 或 YouTube Music 链接直接下载；也可以输入关键词搜索 YouTube，双击结果下载。
   YouTube Music 只支持链接，它的搜索接口不返回可下载的歌曲条目。
2. 下载完的文件记在「已下载」里，换个任务也可以再选一次。同一首不会重复下载：链接换个形式
   （例如 YouTube 自动加上的 `&list=…`）也认得出是同一首。
3. 链接里带播放列表时只取链接指向的那一首，不会把整个列表拖下来。
4. 选中后点「使用所选」，文件就填进刚才那个字段。整场页的音源列表可以一次选多个。

装有 ffmpeg 时下载结果转成 WAV；没有时保留原始容器（通常是 WebM/Opus），交给 Qt Multimedia
解码，两条路管线都能读。文件保存在应用数据目录的 `downloads` 下，对话框里可以「打开文件夹」
查看，或「删除」连同文件一起清掉。

请只下载你有权使用的内容。

## 命令行使用方法

查看版本和帮助：

```bash
uv run --locked purivox --version
uv run --locked purivox --help
uv run --locked purivox mr --help
```

用默认参数执行参考对消：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav"
```

也可以在命令行中指定强度和统计窗口：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav" \
  --strength 75 --sigma 8 --align
```

常用参考对消参数：

| 参数 | 取值 | 说明 |
|---|---:|---|
| `--strength` | `0`～`100` | 垫音消除强度，默认 `75` |
| `--sigma` | `1`、`3`、`8`、`16` | 统计窗口秒数（进阶参数），默认 `3`；图形界面固定使用 `3` |
| `--align` / `--no-align` | 开 / 关 | 是否自动对齐，默认开启 |
| `--tracks` | `vocal`、`backing`、`both` | 导出内容，默认 `vocal`（仅消音结果）|
| `--lang` | `zh_cn`、`zh_tw`、`en_us`、`ja_jp`、`ko_kr` | 进度信息语言 |

从链接获取音源：

```bash
uv run --locked purivox fetch "https://www.youtube.com/watch?v=..."   # 直接下载
uv run --locked purivox fetch "关键词" --limit 5                      # 只列出搜索结果
uv run --locked purivox fetch "关键词" --pick 2                       # 下载列表中的第 2 个
uv run --locked purivox fetch --list                                  # 列出下载过的文件
```

| 参数 | 取值 | 说明 |
|---|---:|---|
| `--out` | 目录 | 保存位置，默认为应用数据目录下的 `downloads` |
| `--limit` | 整数 | 搜索结果条数，默认 `10` |
| `--pick` | 整数 | 下载搜索结果中的第几个，从 1 开始；不给就只列出不下载 |
| `--list` | 开关 | 列出下载过的文件 |

成功时把文件路径打印到标准输出，可以直接接给 `purivox mr` 使用。

## 输入、输出与注意事项

- WAV、FLAC、OGG 等格式由 libsndfile 直接支持；系统可以解码的其他格式会尝试通过 Qt Multimedia 读取。
- MR Remove 与整场处理全程在舞台 / 现场音频的原始采样率下工作，导出同样保持该采样率。
- 导出的 PCM WAV 沿用输入文件的采样率与位深：8-bit 与 16-bit PCM 输入写出 16-bit，更宽的
  24/32-bit PCM、浮点以及所有有损格式写出 24-bit。升采样不会凭空产生输入里没有的频谱细节，
  只会让文件变大，因此不做这一步。
- 输出路径不能覆盖任何输入文件。按 `Ctrl+C` 可取消命令行任务。
- 下载由 yt-dlp 完成。站点改版时请先更新依赖再排查；同一个链接只会下载一次，重复请求直接
  返回已有文件。
- 合成测试只能说明实现没有明显退化，最终效果请以同一素材处理前后的试听对比为准。

## 技术文档

算法、架构、测试和发布说明已移至 [docs/](docs/README.md)：

- [架构与数据流](docs/architecture.md)
- [参考对消](docs/reference-removal.md)
- [完整舞台实现](docs/full-stage.md)
- [浏览器版（WebAssembly）](docs/web.md)
- [开发与贡献](docs/CONTRIBUTING.md)

## 致谢与许可

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor)：为频域人声提取方向提供启发。
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui)：
  没有歌曲音源时的神经网络分离工具。

本项目以 [AGPL-3.0-or-later](LICENSE) 发布。PySide6-Fluent-Widgets
开源版本使用 GPLv3，商业使用前请先确认其上游许可。
