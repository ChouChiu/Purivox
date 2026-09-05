# 更新日志 / Changelog

每个已发布版本一节。发布流程会取出与标签同名的小节作为 GitHub Release 的说明，
应用内的「检查更新」弹窗显示的也是它。

Each released version gets one section. The release workflow uses the section
matching the tag as the GitHub Release notes, which is also what the in-app
update dialog shows.

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
