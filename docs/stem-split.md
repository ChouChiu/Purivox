# 声学分轨

<p align="left">
  <strong>简体中文</strong> · <a href="en/stem-split.md">English</a>
</p>

## 目标与边界

这是项目里第二条工作流，也是唯一一条不需要歌曲音源的：给一个音频文件，按它的声道关系把它拆成若干
分轨。入口是 `run_stem_split_job(job, token, progress)`，GUI 的分轨页和 `purivox split` 都调用它。

它不做的事：这里没有参考、没有匹配、没有时间线。要把现场录音里的垫音消掉，用的是
[参考对消](reference-removal.md)和[音源匹配](matching.md)那条管线，不是这一条。也没有神经网络——
这条管线是纯矩阵与滤波，理由和当初移除神经分离一样：为一个不需要模型的工作流背 58 MB 的运行时不
划算。

**分出哪些轨由声道数决定**，因为声道数决定了什么是能够诚实分出来的：多声道母带自己带着中置声道，
立体声母带只是隐含一个中置。

| 声道数 | 路径 | 分轨数 |
|---|---|---|
| ≥ 6 | 离散解码（`_surround_stems`） | 8 |
| 2（3–5 折叠为前两声道） | 声像自适应 + 互补分频（`_stereo_stems`） | 6 |
| 1 | 互补分频（`_mono_stems`） | 3 |

三到五声道没有对应的解码矩阵，所以折叠成前两声道按立体声处理，而不是去猜它的布局。

能不能拿到 6 声道取决于解码器：libsndfile 打得开的容器（WAV、FLAC）原样给出全部声道；压缩容器走
`shared/audio/io.py` 里的 Qt Multimedia 回退时，声道数由 Qt 的后端决定。项目不为此引入额外的解码
依赖。

## 分轨清单

文件名是 `<输入文件名>_<marker>.wav`。marker 固定英文，不随界面语言变化——会跟着语言改名的文件，
换一次语言就变成了另一个文件。

**立体声（6 轨）**

| marker | 声道 | 内容 |
|---|---|---|
| `center` | 单声道 | 声像自适应中置：主唱与居中乐器 |
| `instrumental` | 立体声 | 去掉中置之后的伴奏 |
| `side` | 单声道 | M/S 侧边 $(L-R)/2$ |
| `mid` | 单声道 | M/S 中间 $(L+R)/2$ |
| `low` | 立体声 | LR4 低通（低于分频点） |
| `high` | 立体声 | 互补高通 $x - \text{low}$ |

**多声道（8 轨）**：`surround`（SL+SR）、`center`（FC）、`lfe`、`front`（FL/FR）、
`front_no_center`、`downmix`（ITU-R BS.775 降混）、`low`、`high`（后两者取自 downmix）。

**单声道（3 轨）**：`low`、`mid_band`、`high`，三者相加精确还原原信号。

## 互补分频

低通是 Linkwitz-Riley（两级二阶 Butterworth 串联，`STAGE_ORDER = 2`），**高通不是另一个滤波器，
而是 $x - \text{low}$**。

这不是实现上的偷懒，而是唯一能让两条带轨加得回去的做法：一个独立的 Butterworth 低通加上一个独立
的 Butterworth 高通，在分频点附近既有幅度凹陷也有相位错位，两条相加不等于原信号。差分定义没有这
个问题。

代价是高频轨承担了互补相位，低频轨本身有单向 `sosfilt` 的相位位移。不用零相位的 `sosfiltfilt`，
是因为它要倒着再走一遍映射缓冲；在长录音上这笔开销换来的东西，不如“精确还原”这条不变量值钱。

滤波是分块做的，`zi` 状态跨 `BLOCK_FRAMES` 传递，结果与一次性滤完整个文件逐位相同——
`tests/features/stem_split/test_crossover.py` 盯着这一条。

## 声像自适应分离

立体声母带没有中置声道，只有两个声道的关系。逐频点 $(f, t)$，对短时自谱与互谱做时间平滑后：

$$\psi = \frac{2\,|\Phi_{LR}|}{\Phi_{LL} + \Phi_{RR}},\qquad
\tau = \frac{\Phi_{LL} - \Phi_{RR}}{\Phi_{LL} + \Phi_{RR}}$$

$\psi$ 是两个声道在这一格里有多像——单一被声像定位的源接近 1，混响尾巴和镲片噪声接近 0；$\tau$
是它落在左右之间的什么位置，居中为 0。中置权重是两者之积：

$$w = \psi \cdot \exp\!\left(-\frac{\tau^2}{2\sigma_{\text{pan}}^2}\right) \cdot g(f)$$

$\sigma_{\text{pan}} = 0.25$（`PAN_WIDTH`）是“还算居中”的容差：略微偏移或做了加倍的主唱仍在里面，
硬摆到一侧的吉他不在。

$g(f)$ 是低频保护（`BASS_PROTECT_HZ = 100`，到 `BASS_PROTECT_EDGE_HZ = 200` 升到 1）。底鼓和贝斯
居中是因为惯例，不是因为它们是主唱；把它们跟着主唱一起拿走，正是每条相位抵消卡拉OK都会挨的骂。
这条保护带压得比较窄，因为男声基频就紧贴在它上面——再往上保护，就会把一部分人声留在伴奏里。

两条轨由此得到：

$$\text{center} = w\,M, \qquad
\text{instrumental}_{L} = L - w\,t_{L}\,M, \qquad
\text{instrumental}_{R} = R - w\,t_{R}\,M$$

其中 $M = (L+R)/2$，$t_{L}, t_{R}$ 是按 $\sqrt{\Phi_{LL}}, \sqrt{\Phi_{RR}}$ 归一化得到的左右分摊
系数。有了 $t$，偏离正中的源是**按它自己的声像位置**从每个声道里减掉对应的份量，而不是从两边各减
一半。把中置轨按估计出的声像位置放回去，仍然得到原混音——这两条轨仍然是一个分解。

相减在复数域进行，不是按幅度衰减，所以相位一并对上。

长文件按约 45 秒一块、重叠 ≥2 秒处理，块间 $\cos^2/\sin^2$ 交叉淡化。整首歌的频谱图是音频本身的
上百倍，浏览器版跑同一套管线的那条内存上限也在这里适用。

## 按频点复数 α 的前置减中置

多声道母带的中置声道会漏进前置声道。Atome 用全曲一个实数标量 $\alpha$ 做正交投影；真实的泄漏是
一个滤波器——有延时、有搁架、每个频率都不一样，一个标量消不掉。

这里用两趟：第一趟累计每个频点的 $\sum F_L \overline{F_C}$ 与 $\sum |F_C|^2$，得到全曲、逐频点、
**复数**的 $\alpha_L(f)$；相干度 $|\Phi_{LC}|^2 / (\Phi_{LL}\Phi_{CC})$ 低于 `COHERENCE_FLOOR`
的频点令 $\alpha = 0$，这样前置声道里与中置无关的内容不会被减掉。第二趟输出
$\text{istft}(F_L - \alpha_L(f) F_C)$。

取全曲估计而不是逐帧估计：母带里 FC 到前置的泄漏基本是静态的，全曲估计更稳。

## 电平与削波

**能相加还原的一组分轨共用一个增益，其余按原电平写出。**

Atome 把每条分轨各自归一化到 0.999，这恰恰是让一组分轨不再是一个分解的做法：每个文件回到各自的
电平，相加不再等于原混音。这里的规则是 `fit_group()`：一组分轨先全部渲染完，量出组内最大峰值，
要么整组同乘一个系数，要么一个都不动。

成组的是：`center` 与 `instrumental`、两条带轨、单声道的三条带轨、多声道的 `downmix` 与它的两条
带轨。不属于任何一组的分轨（离散声道、`side`、`mid`、`front_no_center`）按原电平写出——离散声道
和 M/S 分量都被原始峰值约束住，不可能超过它；真超了，`export_audio()` 原有的削波警告仍在后面兜着。

多声道降混另有一层：按 ITU-R BS.775 折叠时三个声道相加可以到 2.41 倍，所以先按各声道实测峰值算出
一个 `downmix_gain()`，再交给上面的分组规则。

## 衡量

分轨质量用 `tools/eval_stems.py` 量，用法与 `eval_cancellation.py` 一致：

```bash
uv run --locked python tools/eval_stems.py --save baseline.json
uv run --locked python tools/eval_stems.py --compare baseline.json
```

场景是合成的，每个成分都已知，所以“主唱在伴奏轨里低了多少 dB”是对已知信号的投影，不是对结果的
印象。指标：`lead_removed_db`（主唱在伴奏轨里相对入混电平的变化，越负越好）、`lead_kept_db`
（主唱在中置轨里的保留）、`arrangement_kept_db` / `bass_kept_db`（配器与贝斯在伴奏轨里的保留，
越接近 0 越好）、`centre_leak_db`（前置减中置的抑制）、`band_rmse`（带轨重建误差）。

合成指标只用来发现回退，不构成对真实音乐质量的结论。
