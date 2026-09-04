# 更新日志 / Changelog

每个已发布版本一节。发布流程会取出与标签同名的小节作为 GitHub Release 的说明，
应用内的「检查更新」弹窗显示的也是它。

Each released version gets one section. The release workflow uses the section
matching the tag as the GitHub Release notes, which is also what the in-app
update dialog shows.

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
