# 音频扒谱与可编辑交付

[English](README.md) | [简体中文](README.zh-CN.md)

Agent 在内部选择自身音频理解能力或配套转录引擎，理解候选结果，再编写统一音乐
计划。软件适配器负责写入可编辑音乐，不调用 ACE 自带的音频转 MIDI 功能识谱。

已实现：解码和证据准备、独立模型环境、失败自动切换、可选 Demucs 分轨、带来源
关联的计划、按需输出 MSCZ／MusicXML／PDF／多轨 MIDI，以及使用官方 CLI 的 ACE
工程适配器，包含真实音源绑定和保存后回读。

## 模型实际测量

[engine-validation.json](engine-validation.json) 固定预测、独立参考事件、哈希、随机
种子、运行时版本和测量结果。起音容差 50 毫秒，音高必须相同；结束时间容差
100 毫秒。输入是原创短合成对照和 MuseScore 采样渲染，不是麦克风录音或商业音乐。

| 输入 | 引擎 | 匹配音高／起音 | 音高／起音 F1 | 包含结束时间 F1 | 匹配鼓事件 |
| --- | --- | --- | --- | --- | --- |
| 合成旋律 | Basic Pitch | 12/12 | 1.000 | 1.000 | — |
| 合成多声部 | Transkun | 13/24 | 0.703 | 0.432 | — |
| 合成混音 | YourMT3 | 25/32 | 0.877 | 0.807 | 17/24 |
| 采样旋律 | Basic Pitch | 10/12 | 0.800 | 0.160 | — |
| 采样钢琴 | Transkun | 24/24 | 1.000 | 0.375 | — |
| 采样钢琴、低音钢琴、标准鼓组 | YourMT3 | 31/32 | 0.969 | 0.875 | 22/24 |
| 随机休止与音符时长 | Basic Pitch | 9/9 | 1.000 | 0.889 | — |

这些是具体样例的测量，不是产品对任意音乐的准确率。钢琴音高／起音准确，不代表
结束时间也准确。乐器类别和管弦乐同类演奏者分离尚未独立验收。之前的一份混音
渲染使用了通用 Percussion 音色（程序号 48）；修正样例先核验为 Drumset／程序号 0，
再评价鼓事件识别。

四个后端都已在 macOS arm64／Python 3.11／CPU 实际运行。本机模型环境约为
Basic Pitch 515 MiB、Transkun 949 MiB、YourMT3 1077 MiB、Demucs 818 MiB，下载权重
约 620 MiB。这是开发机器测量；用户仅按需安装引擎，工具本体不打包模型环境和权重。

## 复现

```bash
python -m pip install -e '.[audio]'
python scripts/make_audio_benchmark.py --output work/controls --seed 2026100407
# 采样测试需 MuseScore 和 ffmpeg：
python scripts/make_audio_benchmark.py --output work/sampled --seed 2026100407 --musescore /path/to/mscore
scorebridge transcribe-audio work/sampled/inputs/mixed.wav --output work/inference --hint mixed
# 固定预测后才打开参考答案：
scorebridge evaluate-audio work/sampled/answers/mixed.json work/inference/transcription-JOB/events.json
scorebridge music-plan work/inference/transcription-JOB/events.json --output work/plan.json --bpm 120
scorebridge deliver-music work/plan.json --output final --formats mscz musicxml pdf midi ace
```

此处 120 BPM 是原创样例的创作速度，不是速度识别得分。任意来源的任务应由 Agent
内部确定音乐时间。模型直接输出是候选数据，未经音乐理解就直接使用，不等于
完成高精度扒谱。

## 验收范围

实际混音识别输出 54 个事件。同一计划生成 MSCZ、MusicXML、PDF、多轨 MIDI 和
保存后重新打开的双轨 ACE 工程。ACE 回读全部 54 个音高和时间、MIDI 力度，实际
加载钢琴和第 10 通道鼓组。另一个七音符测试加载了 AI 小提琴和单簧管，保留变速、
变拍号并成功重新打开。AI 乐器不使用 MIDI CC／力度，未映射的表情会明确记录；
普通 MIDI／插件轨保留这些控制数据。参见[音乐计划说明](../../skills/scorebridge/references/music-plan.md)。

[validation.json](validation.json) 保留之前 Agent 读取频谱图的自测，作为历史记录，
与模型测量分开。本次固定五个工作包为：引擎路由和配置、统一计划、按需输出、
首个 DAW 适配器、统一 Skill／CLI／MCP 验收。新增适配器和更大规模的真实录音测试
属于后续版本扩展。
