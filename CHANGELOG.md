# 更新日志 / Changelog

每个已发布版本一节。发布流程会取出与标签同名的小节作为 GitHub Release 的说明，
应用内的「检查更新」弹窗显示的也是它。

Each released version gets one section. The release workflow uses the section
matching the tag as the GitHub Release notes, which is also what the in-app
update dialog shows.

## v1.1.1 — 2026-09-10

**改进**

- **垫音轨改为从歌曲音源渲染**：以前的垫音是舞台 / 现场录音减去消音结果，音质跟着现场拾音走；
  现在是把对消估计出的传递套回歌曲音源重新渲染，因此保留音源本身的音质，同时带着垫音在舞台上
  实际的音量与频响。未识别的区间仍然是静音，强度为 0 时垫音也是静音

**修复**

- **网页版：超过两分钟的录音识别不了**。频谱特征在浏览器里会撞上 wasm32 两 GB 的视图上限，
  分析的第一步就抛错。现在逐块计算，峰值内存也不再随录音长度增长
- **网页版：时间轴里的时间输入框压住右边一列**，音源范围和倍速被遮住；输入不合法的时间也没有
  任何提示。现在每一列有自己的宽度，不合法的值标成红色

---

**Improved**

- **The backing track is rendered from the song source**: it used to be the
  stage/live recording with the vocal taken back out of it, which meant it
  carried the capture rather than the music. It is now the source re-rendered
  through the transfer the cancellation estimated, so it keeps the source's own
  quality while carrying the level and response the backing actually had on
  stage. Unmatched ranges are still silent, and so is the backing at zero
  strength

**Fixed**

- **Browser: a recording longer than two minutes could not be analysed**. The
  spectral feature hit wasm32's two-gigabyte ceiling on a strided view and threw
  at the first step of the analysis. It is computed block by block now, which
  also keeps peak memory off the recording's length
- **Browser: the timeline's time fields covered the column beside them**, hiding
  the source range and the speed, and a time the parser rejected showed nothing
  at all. Every column has a width of its own now, and a rejected value is
  marked in red

**下载 / Downloads**

- Windows：`Purivox.exe`
- macOS（arm64）：`purivox-macos-arm64.tar.gz`
- Linux：`purivox_1.1.1-1_amd64.deb`、`purivox-1.1.1-1.x86_64.rpm`，
  或免安装的 `purivox-linux-x86_64.tar.gz`
- Python 包：`purivox-1.1.1-py3-none-any.whl` / `purivox-1.1.1.tar.gz`
- 校验：`SHA256SUMS-windows`、`SHA256SUMS-macos`、`SHA256SUMS-linux`、
  `SHA256SUMS-python`

## v1.1.0 — 2026-09-06

**新增**

- **从链接获取音源**：单曲页的两个文件行、整场页的舞台音频与音源列表都新增「获取」按钮。
  粘贴 YouTube 或 YouTube Music 链接直接下载，或输入关键词搜索 YouTube 后双击结果下载。
  链接里带播放列表时只取它指向的那一首。YouTube Music 只支持链接——它的搜索接口不返回
  可下载的歌曲条目
- **下载记录**：下载过的文件列在「已下载」里，换个任务可以再选一次，同一首不会重复下载，
  链接换个形式（例如 YouTube 自动加上的 `&list=…`）也认得出是同一首。文件保存在应用数据
  目录的 `downloads` 下，可以在对话框里打开文件夹查看，或连同文件一起删除
- **命令行 `purivox fetch`**：`fetch <链接>` 直接下载，`fetch <关键词> --pick N` 搜索后下载
  第 N 个，`fetch --list` 列出下载过的文件。成功时把路径打印到标准输出，可以直接接给
  `purivox mr`

**移除**

- **AI 人声分离**：不使用歌曲音源的神经网络分离页面和 `purivox ai` 命令已经移除。
  它与 Purivox 的其余部分不共享任何东西——不取歌曲音源，不做匹配、对齐和参考对消，
  结果也无法与垫音消除的输出相比较——却让安装包一直背着 onnxruntime。
  这类需求请交给 UVR5 等专用工具。首页原来的 AI 入口卡片改为打开整场垫音消除

**改进**

- 安装包明显变小：随神经网络分离一起移除的 onnxruntime，加上不再打包那些从未被加载的
  图像编解码器与 Qt 插件，Linux 免安装包从约 127 MB 降到约 99 MB
- 装有 ffmpeg 时下载结果转成 WAV，没有时保留原始容器（通常是 WebM/Opus）交给 Qt Multimedia
  解码，两条路管线都读得了；`.webm` 也进了文件对话框的音频格式过滤器
- 窄窗口下路径字段会让位，而不是把整页撑宽

---

**Added**

- **Fetch a source from a link**: both file rows on the Single page, and the stage
  audio and source list on the Full Stage page, gained a **Fetch** button. Paste a
  YouTube or YouTube Music link to download it, or type keywords to search YouTube
  and double-click a result. A link carrying a playlist yields the one track it
  points at. YouTube Music is link-only — its search does not answer with
  downloadable songs
- **Downloads are remembered**: what has been fetched is listed under **Downloaded**
  and stays available for later jobs. A track is never fetched twice: a link in
  another shape — the `&list=…` YouTube adds on its own, say — is still recognised
  as the same track. Files live under `downloads` in the application data
  directory, and the dialog can open that folder or delete an entry with its file
- **`purivox fetch` on the command line**: `fetch <link>` downloads it,
  `fetch <keywords> --pick N` searches and takes the Nth result, and
  `fetch --list` shows what has been downloaded. On success the path is printed to
  standard output, ready to hand to `purivox mr`

**Removed**

- **Neural separation**: the AI page and the `purivox ai` command are gone. That
  workflow shared nothing with the rest of Purivox — it took no song source and
  ran none of the matching, alignment or reference cancellation the product is
  built around, and its result could not be compared against a vocal isolation
  one — while onnxruntime rode along in every installer. Reach for a dedicated
  tool such as UVR5 instead. The home page's AI card now opens Full Stage

**Improved**

- A much smaller download: dropping onnxruntime along with neural separation, and
  no longer packaging image codecs and Qt plugins the build carried but never
  loaded, takes the Linux onefile from about 127 MB to about 99 MB
- With ffmpeg installed a download is converted to WAV; without it the original
  container is kept — usually WebM/Opus — and Qt Multimedia decodes it, so the
  pipelines read either one. `.webm` joined the audio filter in the file dialogs
- In a narrow window the path fields give way instead of widening the page

**下载 / Downloads**

- Windows：`Purivox.exe`
- macOS（arm64）：`purivox-macos-arm64.tar.gz`
- Linux：`purivox_1.1.0-1_amd64.deb`、`purivox-1.1.0-1.x86_64.rpm`，
  或免安装的 `purivox-linux-x86_64.tar.gz`
- Python 包：`purivox-1.1.0-py3-none-any.whl` / `purivox-1.1.0.tar.gz`
- 校验：`SHA256SUMS-windows`、`SHA256SUMS-macos`、`SHA256SUMS-linux`、
  `SHA256SUMS-python`

## v1.0.1 — 2026-09-05

**新增**

- **导出内容**：单曲与整场垫音消除都可以选择导出「仅消音结果」「仅垫音」或两者。
  垫音轨是舞台 / 现场音频减去消音结果，因此带着垫音在舞台上的实际音量，
  两条轨相加即还原原始录音。命令行对应 `--tracks vocal|backing|both`
- **崩溃报告**：桌面版每天写一个日志文件到应用数据目录，保留 14 天；
  程序遇到未捕获的异常时记录完整堆栈、打开当天的日志，并可一键跳到已填好版本、
  系统与构建信息的问题反馈表单。日志内容不会进入链接，由你自己决定粘贴哪一段
- **macOS 下载**：新增 arm64 应用包

**改进**

- 三个处理页面的状态卡统一由同一处构建，进度与状态文字的行为不再各写一遍

---

**Added**

- **Export choice**: single-song and full-stage vocal isolation can now export the
  vocal only, the backing track only, or both. The backing track is the
  stage/live audio minus the vocal, so it carries the level the accompaniment
  actually had on stage, and the two stems add back up to the original
  recording. On the command line: `--tracks vocal|backing|both`
- **Crash reporting**: desktop runs append to one log file a day under the
  application data directory, kept for 14 days. An uncaught exception is logged
  with its traceback, opens that day's log, and offers an issue form prefilled
  with the version, platform and build. Nothing from the log travels in the
  link — you choose what to paste
- **macOS download**: an arm64 app bundle

**Improved**

- The status card on the three processing pages is now built in one place
  instead of three

**下载 / Downloads**

- Windows：`Purivox.exe`
- macOS（arm64）：`purivox-macos-arm64.tar.gz`
- Linux：`purivox_1.0.1-1_amd64.deb`、`purivox-1.0.1-1.x86_64.rpm`，
  或免安装的 `purivox-linux-x86_64.tar.gz`
- Python 包：`purivox-1.0.1-py3-none-any.whl` / `purivox-1.0.1.tar.gz`
- 校验：`SHA256SUMS-windows`、`SHA256SUMS-macos`、`SHA256SUMS-linux`、
  `SHA256SUMS-python`

## v1.0.0 — 2026-09-04

首个正式版本。

**功能**

- **单曲垫音消除**：给出舞台 / 现场音频与对应的歌曲音源，自动对齐后消除垫音，
  保留音源里没有的现场人声、讲话、欢呼与环境声
- **整场垫音消除**：用多个歌曲音源在整场录音里定位每首歌，时间轴可编辑，只处理勾选的片段
- **AI 音轨分离**：4 个可选 MDX-Net 模型，缺文件时自动下载并校验 SHA-256
- **浏览器版**：同一套处理管线跑在 Pyodide 上，无需后端，不含 AI 音轨分离
- Fluent Design 界面，中文 / English / 日本語 / 한국어，浅色、深色与跟随系统主题
- 导出沿用输入文件的采样率与位深；长音频分块处理，任务可随时取消
- 设置页可检查新版本，有更新时弹窗显示 Changelog 并跳转 Release 页面，不做自动更新
- 图形界面与命令行共用同一套处理管线

**下载**

- Windows：`Purivox.exe`
- Linux：`purivox_1.0.0-1_amd64.deb`、`purivox-1.0.0-1.x86_64.rpm`，
  或免安装的 `purivox-linux-x86_64.tar.gz`
- Python 包：`purivox-1.0.0-py3-none-any.whl` / `purivox-1.0.0.tar.gz`
- 校验：`SHA256SUMS`

---

First release.

**Features**

- **Single vocal isolation**: give it a stage recording and the matching song
  source; it aligns the two and cancels the backing track, keeping the live
  vocals, talking and room the source cannot explain
- **Full stage vocal isolation**: locate every song of a continuous recording
  from several sources, edit the timeline, process only the clips you keep
- **AI vocal extraction**: four optional MDX-Net models, downloaded on demand
  and verified with SHA-256
- **Browser build**: the same pipelines under Pyodide, no backend, no AI
  extraction
- Fluent Design UI in Chinese, English, Japanese and Korean, with light, dark
  and system themes
- Exports keep the input's sample rate and bit depth; long audio is processed
  in blocks and any job can be cancelled
- The settings page checks for new releases: an update opens one dialog with
  its changelog and a link to the release page — nothing updates itself
- The GUI and the CLI run the same pipelines
