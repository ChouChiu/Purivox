# 开发、测试与发布

<p align="left">
  <strong>简体中文</strong> · <a href="en/development.md">English</a>
</p>

## 开发环境

项目使用 uv 管理 Python、隔离环境和锁文件。安装 uv 后，在仓库根目录安装锁定的运行时依赖和默认开发
依赖：

```bash
uv sync --locked
```

构建 Linux 独立程序时，再安装部署依赖：

```bash
uv sync --locked --group deploy
```

修改依赖时使用 `uv add <包名>`、`uv add --dev <包名>` 或 `uv add --group deploy <包名>`，并提交
同步更新的 `pyproject.toml` 与 `uv.lock`。

请不要同时安装其他会导出 `qfluentwidgets` 的 PyQt 或 PySide Fluent 组件。项目指定的是
`PySide6-Fluent-Widgets[full]`。

## 代码约定

- 新模块使用 `from __future__ import annotations` 和完整类型标注。
- 可变参数少的任务模型优先使用 `frozen=True, slots=True` 数据类，固定字符串集合使用 `StrEnum`。
- 公共基础设施放在 `shared`；功能专属页面、模型和处理逻辑放在对应 `features/<功能>/`。
- 跨功能编排放在 `app`，不要为了复用而让功能包互相导入。
- 被多个功能消费的数据模型应统一放到 `shared`；只在单个功能内部使用的模型，
  不得为了方便从别的功能再导出。
- 常量、取值范围和算法同理：同一个取值若出现在两个功能或 GUI 与 CLI 中，应在 `shared` 定义一次再
  引用，例如 `shared.audio.BLOCK_FRAMES`、`shared.audio.AUDIO_EXTENSIONS`、`shared.jobs.SIGMA_CHOICES`、
  `shared.i18n.SUPPORTED_LANGUAGES` 和 `shared.logging.LOG_LEVELS`。
- Qt 后台任务统一由 `app/job_presenter.py` 协调页面状态，再交给 `app/job_runner.py` 管理线程；
  页面和业务管线不得自行创建线程。
- 跨线程接收信号的槽用 `@Slot(<类型>)` 标注（worker → `JobRunner` → `JobPresenter`），让 Qt 按声明的
  签名派发排队连接。
- Qt 已经处理好的问题优先使用 Qt 提供的方案：可编辑表格用 `QAbstractTableModel` + `TableView`，不要
  用 `QTableWidget` 逐格填 item；HTTP 用 `QNetworkAccessManager`（系统代理、跳转、超时、进度、
  `abort()`）；需要先校验再写入时用 `QSaveFile`；路径用 `QStandardPaths`。标准库已经等价或更好的地方
  保持不变（`hashlib`、`tempfile` + `numpy.memmap`、argparse 子命令、DSP 线程池）。
- 页面中的独立交互控件拆成同功能包内的小模块，例如试听跳转控件位于 `reference_removal/preview.py`。
- 长音频使用 `create_pcm_audio` 与分块循环（块大小取 `shared.audio.BLOCK_FRAMES`），不要把整个文件
  复制到普通内存数组；映射页用 `shared.audio.release_mapped_pages()` 释放。
- 可取消循环必须定期调用 `CancellationToken.raise_if_cancelled()`，且不得忽略取消异常。
- 输出使用 `write_wav_atomic`，不要直接覆盖目标文件。
- 导出规格跟随输入文件：`AudioData` 同时携带解码源的 `sample_rate` 与 `bit_depth`，`resample_audio`
  与 `stereo()` 逐级传递，`write_wav_atomic` 与 `analyze_audio` 直接读取，不再接收格式参数。
  `WAV_BIT_DEPTHS` 为 `(16, 24)`：8-bit 与 16-bit PCM 输入写出 16-bit，更宽的 24/32-bit PCM、浮点
  以及所有有损格式写出 24-bit。不存在导出规格下限，也不得为凑规格而向上重采样。
- 日志通过 `logging.getLogger(__name__)` 写入；只有明确记录的降级路径可以忽略局部失败。

Ruff 行宽为 100，启用 E、F、I、UP、B、SIM 和 RUF 规则，E501 由格式化与评审控制。

## 翻译与配置

界面字符串使用 Qt Linguist 的 `.ts`（XML）作为可编辑来源，编译产物 `.qm` 由 `QTranslator` 加载：

```text
src/resources/i18n/zh_cn.ts   src/resources/i18n/zh_cn.qm
src/resources/i18n/en_us.ts   src/resources/i18n/en_us.qm
src/resources/i18n/ja_jp.ts   src/resources/i18n/ja_jp.qm
src/resources/i18n/ko_kr.ts   src/resources/i18n/ko_kr.qm
```

`.ts` 采用按键索引而非按原文索引：`<source>` 是 `nav_mr` 这样的短标识，`<translation>` 是各语言文本，
四个文件同属 `Purivox` 这一个 context。因此中文改词不会牵动其他语言的条目，`pyside6-lupdate` 也不适用
（它按源码中的字面量提取），翻译条目由人工维护。

修改任一 `.ts` 后必须重新编译，并把 `.ts` 与 `.qm` 一起提交：

```bash
for locale in zh_cn en_us ja_jp ko_kr; do
  uv run --locked pyside6-lrelease "src/resources/i18n/$locale.ts" \
    -qm "src/resources/i18n/$locale.qm"
done
```

增加、删除或重命名翻译键时必须同步修改四个 `.ts`；测试会检查键集合完全一致、`.qm` 与 `.ts` 未过期，
并且源码中出现的每个字面量键都存在于所有语言。调用 `tr(key, **values)` 时不得依赖
“未知键返回键名”的回退行为。

翻译是应用级状态：`shared.i18n.install_language()` 安装对应语言的 `QTranslator`，`tr()` 经
`QCoreApplication.translate()` 查表，因此任务对象和处理管线不再传递语言参数。GUI 在设置页切换语言时
重新安装并调用 `retranslate()`，CLI 则在启动时按 `--lang` 安装一次。

配置由 `src/shared/config.py` 中的 QConfig 单例管理。修改持久化选项时要同时考虑默认值、验证器、页面
重译和测试。

参考引导人声提取采用参考对消。所有用户可选的处理路径都只能从现场原混音重建，不得把音源独有的内容或
它的反相写进结果。DSP 调整不能只看合成指标：先通过自动化检查，
再对固定的真实素材导出可以直接试听对比的版本；技术检查结果不应写成“已确认听感”。

## 增加源码文件

新增源码目录或文件时检查三个发布清单：

1. `pyproject.toml` 的 wheel 包列表；
2. `pyproject.toml` 的 `[tool.pyside6-project].files`；
3. `pysidedeploy.spec` 的 `include-package` 或相应包含项。

遗漏任一清单都可能造成开发环境正常、wheel 或独立程序缺文件。
`tests/test_packaging.py` 会自动比较所有 `src/**/*.py` 与 `[tool.pyside6-project].files`，
并拒绝遗漏或失效条目；新增顶层包时仍需人工确认 wheel 与 Nuitka 的包清单。

## 质量检查

Qt 测试必须使用离屏平台：

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest
uv build
```

慢速基准需要显式开启：

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow
```

当前慢速检查使用 15 分钟、44.1 kHz 双声道音频检查参考对消的输出长度、接缝和峰值常驻内存，
内存上限为 2 GiB。

测试目录与源码结构一一对应，主要覆盖：

- 公共音频读写、重采样、原子写出、短时傅里叶变换和日志；
- 三条产品管线沿用输入采样率与位深的导出契约；
- 参考对消算法、时间对齐、立体声矩阵、回归场景和端到端任务；
- 完整舞台匹配、时间线与分段渲染；
- MDX-Net 分块重叠相加和模型管线；
- CLI 参数、GUI 导航、设置与统计显示；
- 分层导入边界、发布清单和四种语言的翻译键一致性。

测试文件按被测源码归属放置。功能内部算法放在 `tests/features/<功能>/`；同时组合多个功能的应用编排放在
`tests/app/`；公共音频、任务协议和控件放在 `tests/shared/`。Pytest 使用 `importlib` 导入模式，允许
不同目录使用与源码对应的相同测试文件名而不发生模块碰撞。这样测试目录本身也能暴露跨层的依赖问题。

`tests/test_documentation.py` 检查 README 与 `docs/` 中的内部链接，并确保所有技术文档都能从
项目首页到达。重命名文档时应同步修改索引和引用，不要留下失效链接等人发现。

## Python 包构建

```bash
uv build
```

产物写入 `dist/`。版本号以 `src/app/version.py` 为唯一来源，由 Hatch 在构建时读取。ONNX 权重位于忽略
列表，不会进入 wheel 或源码包。构建后应通过 uv 的临时隔离环境安装 wheel 并验证（路径中的版本号按实际
产物调整）：

```bash
uvx --from ./dist/purivox-1.0.0-py3-none-any.whl purivox --version
QT_QPA_PLATFORM=offscreen uvx --from ./dist/purivox-1.0.0-py3-none-any.whl \
  purivox --selftest
```

## 独立程序

项目通过 Qt 官方 `pyside6-deploy` 封装 Nuitka，固定使用 `onefile` 模式：

```bash
uv sync --locked --group deploy
uv run --locked --group deploy pyside6-deploy -c pysidedeploy.spec
```

产物是单个可执行文件——Linux 为 `dist/Purivox.bin`，Windows 为 `dist/Purivox.exe`——内含 Python、Qt、
Fluent Widgets、SciPy、SoundFile、soxr 和 ONNX Runtime，但不包含模型权重。

macOS 上 `mode = onefile` 不生效：`pyside6-deploy` 在这个平台一律传 `--standalone
--macos-create-app-bundle`，产物是应用包 `dist/Purivox.app`，内容同上。CI 只构建 arm64
（Apple Silicon），因为锁文件里 ONNX Runtime 的 macOS wheel 只有 arm64 一种。

onefile 程序每次运行都会把内容解包到临时目录，因此需要足够的临时空间。
启动开销经实测不大：126 MB 的 Linux 产物跑完 `--selftest` 全流程约 3.1 秒，
冷启动和热启动没有明显差别。发布前除自动化测试外，还应实际启动它，检查页面导航、模型查找、音频解码、
任务取消和输出试听——尤其要确认解包路径下的资源文件仍能被找到。

Windows 与 macOS 构建复用同一份 `pysidedeploy.spec`，各自在 CI 里派生一份改写过的副本
（`pysidedeploy-windows.spec` 和 `pysidedeploy-macos.spec`，都不入库）：

- `pyside6-deploy` 只有一个 `icon` 键，在 Windows 上作为 `--windows-icon-from-ico`、在 macOS 上
  作为 `--macos-app-icon` 传给 Nuitka，两者都不接受 Linux 构建用的 SVG。仓库里的
  `deployment/purivox.ico`（16～256 共 7 种尺寸）和 `deployment/purivox.icns`（16～1024 共 10 个
  条目）都由 `src/resources/purivox.svg` 渲染而来；改动图标时三者需要一起更新。不是 `.icns` 的图标
  会被 Nuitka 交给 imageio 转换，而它既没装，也读不了 SVG。
- macOS 应用包的名字和 Info.plist 都取自入口文件，入口是 `deployment/main.py`，不改就会得到一个在
  程序坞和菜单栏里自称 main 的 `main.app`。派生的 spec 因此补上 `--output-folder-name`、
  `--output-filename`、`--macos-app-name`、`--macos-signed-app-name`（按项目主页域名反写成
  `top.wwchun.purivox`）和 `--macos-app-version`（读自 `src/app/version.py`）。
- Nuitka 给应用包打的是 ad-hoc 签名，签名封存了它为 `Contents/Frameworks` 建立的符号链接，而
  `pyside6-deploy` 往 `dist/` 复制时会跟随符号链接：每个 Qt framework 因此多存一份，封签也就此失效。
  改过 `--output-folder-name` 之后它按原名找不到东西可复制（日志里会留一行「找不到可执行文件」），
  `--keep-deployment-files` 则让 Nuitka 的原始产物留在 `deployment/deployment/`，由构建任务直接搬进
  `dist/`，再用 `codesign --verify` 确认封签完好。

共享规格里的 `--assume-yes-for-downloads` 三个平台都要：onefile 会下载打包引导所需的组件，macOS 上
Nuitka 还要下载 ccache；缺少它 Nuitka 会停在确认提示上，Runner 会一直挂起。

`patchelf` 已从规格的 `packages` 中移除：`pyside6-deploy` 在 Linux 上本来就会自行安装它，而在
Windows 和 macOS 上它会尝试安装一个只有 Linux wheel 的包并失败。

## 持续集成

构建步骤只写一遍，放在 `.github/workflows/common.yml` 里：它是一个 `workflow_call` 工作流，不带
参数——发布用的产物必须和分支上构建出来的是同一种东西。两个触发器各自是一层薄壳，只负责调用它：
`build.yml` 在 `main` 分支、Pull Request 和手动触发时跑，`release.yml` 在 `v*` 标签上跑，并在
构建之后多一个 `publish` 任务。被调用的工作流和调用方共用同一次 run，因此 `publish` 能直接下载
这次构建上传的工件。

质量检查通过后，`common.yml` 并行构建 Linux、Windows 与 macOS 产物，再上传：

- pytest JUnit XML；
- 质量检查与构建命令的独立日志；
- wheel、sdist 及 SHA-256 校验文件；
- Linux 可执行文件的 tar.gz（用于保留可执行权限）、`.deb`、`.rpm` 及一份 SHA-256 校验文件；
- Windows 可执行文件及 SHA-256 校验文件；
- macOS 应用包的 tar.gz（用于保留可执行权限和 framework 符号链接）及 SHA-256 校验文件。

`.deb` 和 `.rpm` 由 `deployment/package-linux.sh` 用 fpm 从同一份暂存目录打出：可执行文件装到
`/usr/bin/purivox`，另附 `deployment/purivox.desktop`、图标和许可证。onefile 自带 Python 与 Qt，
因此只声明 Qt 仍要从系统加载的两个库（deb 为 `libegl1`、`libpulse0`，rpm 为 `mesa-libEGL`、
`pulseaudio-libs`）。onefile 的载荷附在可执行文件末尾，任何 strip 都会毁掉它，这也是不用发行版
默认打包流程而交给 fpm 的原因。

质量检查只在 Ubuntu 上运行：Windows 与 macOS 任务只产出可分发的二进制，不重复跑测试。

质量和构建任务都会生成 GitHub Job Summary，列出各项检查结果、缓存命中状态、日志和工件下载链接；
即使前置步骤失败，也会尽可能写入已知结果。

工件保留 14 天。uv 依赖缓存由 `uv.lock` 和 `pyproject.toml` 的内容共同失效，同时缓存 uv 管理的
Python 3.14；不缓存 `.venv` 本身。Linux standalone 额外使用 ccache，根据锁文件、部署规格和
Python 源码失效，上限为 2 GiB；Windows 与 macOS 任务按同一套键缓存 Nuitka 自己的缓存目录——macOS
Runner 上没有 ccache，Nuitka 会下载一份放进去，编译缓存也在那里。
同一分支有新提交时会取消旧任务（`build.yml` 的 `cancel-in-progress`），标签构建不会被取消
（`release.yml` 关掉了它——那是唯一能发布的一次运行）。

Ubuntu Runner 会显式安装 Qt 加载所需的 `libegl1`。所有命令步骤都使用开启 `pipefail` 的 Bash，
因此通过 `tee` 保存日志时不会掩盖原命令的失败状态。JUnit XML 仅在实际生成后上传。

## 发布

发布由标签驱动，除打标签外没有手动步骤：

1. 更新 `src/app/version.py` 里的 `__version__`；
2. 在 `CHANGELOG.md` 顶部新增一节，标题写成 `## v<版本> — <日期>`；
3. 提交后打上同名标签并推送：

```bash
git tag -a v1.0.0 -m "Purivox v1.0.0"
git push origin main --follow-tags
```

标签推送后 `release.yml` 会先跑完 `common.yml` 的整条流水线，`publish` 任务再把这一次构建出来的
产物发布出去：
Windows 可执行文件，Linux 的 tar.gz、`.deb` 和 `.rpm`，macOS 的 tar.gz，wheel 与 sdist，以及重新
生成的一份扁平 `SHA256SUMS`（各构建任务自己的校验文件里写的是 `dist/` 路径，在 Release 页面上无法
对应，故不上传）。

质量检查的第一步会在标签构建里核对标签与 `src/app/version.py` 是否一致，不一致就在几分钟内失败，
不会等编译跑完一个小时。Release 说明取自 `CHANGELOG.md` 中与标签同名的小节——应用内「检查更新」
弹窗显示的正是这段内容；找不到对应小节时退回 GitHub 自动生成的说明。带后缀的标签
（如 `v1.1.0-rc1`）发布为 pre-release，`releases/latest` 不会返回它，因此不会推送给用户。

重新运行同一个标签的构建不会失败：已存在的 Release 会被覆盖上传资产，而不是新建一个。
