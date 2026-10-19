# Yuezheng

[English](README.md) | [简体中文](README.zh-CN.md)

**由 Agent 驱动的音乐制作助理：把音乐想法和素材变成可编辑工程。**
Yuezheng 由 Skill、可复用程序和 CLI／MCP 接口组成。Agent 理解用户的自然语言，
理解乐谱、图片、PDF 或音频，整理音乐内容，再执行用户需要的文件输出或软件工作流。
图片／音频转谱是第一项核心工作流；制谱和 DAW 适配器为后续更完整的音乐制作任务提供基础。
MuseScore 和 Sibelius 是当前制谱适配器，ACE Studio 是首个原生 DAW 适配器，项目定位不局限于某一个软件。

## 工作流程

```text
自然语言需求＋PDF／图片／音频
→ Agent 内部判断输入、可用能力和任务目标
→ 直接识别，或选择配套转录／分轨工具
→ 内部音乐／制谱施工计划
→ 生成文件或调用音乐软件接口
→ 用户需要的可编辑交付文件
```

## main 分支已有功能

| 功能 | 当前实现 |
| --- | --- |
| PDF 和图片输入 | 页面准备、页序映射、原图／增强图；由 Agent 读谱 |
| 可编辑乐谱 | Agent 施工计划通过 MuseScore 创建 MSCZ，或通过 Sibelius Connect 创建 SIB |
| 音频转录 | 可选 Basic Pitch、Transkun、YourMT3；独立环境、失败切换、任务缓存 |
| 音频辅助 | 可选 Demucs 分轨、波形／频谱证据、多候选结果组合 |
| 统一计划和输出 | 原始演奏时间与记谱并存；按需生成 MSCZ、MusicXML、PDF、多轨 MIDI |
| 原生 DAW 工程 | ACE 官方 CLI：音符导入、真实 AI／插件音源、保存并重新打开回读 |
| 评测 | 分别测量音高／起音、结束时间、鼓事件和乐器归属 |

识别由 Agent 主导，配套引擎提供带来源位置的候选结果；Agent 的判断与精细记谱
进入统一音乐计划，再由文件生成器和软件适配器落实。参见
[音乐计划及输出范围](skills/yuezheng/references/music-plan.md)和
[开发实测结果](demos/audio-to-score/README.zh-CN.md)。

## 安装并接入 Agent

```bash
git clone https://github.com/achou666666-code/Yuezheng.git
cd Yuezheng
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e '.[mcp,image,audio,websocket]'
.venv/bin/yuezheng doctor
```

需要可复现的开发环境时，可安装 [uv](https://docs.astral.sh/uv/)，然后在仓库根目录运行
`uv sync --all-extras`。

Windows 使用 `.venv\Scripts\python.exe` 和 `.venv\Scripts\yuezheng.exe`。
将 `skills/yuezheng` 安装到 Agent 的技能目录。有终端的 Agent 可调用 CLI；
使用 MCP 时，配置对应环境的 Python 和 `mcp_server/server.py` 的绝对路径：

```bash
.venv/bin/python mcp_server/server.py
```

生成原生 MSCZ 需要支持 `--extension` 的 MuseScore Studio，已在 macOS Studio 4.7.4
验证。提供 Windows／Linux 扩展路径，但尚未进行这些平台的真实软件验收。
音频模型使用独立的 Python 3.10／3.11；缺少兼容版本且已有 uv 时，工具会在私有目录
安装所需 Python。压缩音频解码需要 ffmpeg。
配套依赖和模型权重按需安装、缓存，不打包到工具本体；可复用已有的外部模型环境。

## 兼容性

| 层级 | 已验证 | 范围 |
| --- | --- | --- |
| Python 包 | CI 中的 Python 3.10、3.11、3.12 | 包安装和测试 |
| MuseScore 扩展宿主 | macOS／MuseScore Studio 4.7.4 | 原生 MSCZ 创建和实时编辑检查 |
| ACE Studio 适配器 | macOS、ACE Studio 和官方 CLI | 原生工程保存和回读 |
| Sibelius 适配器 | 本机 Sibelius Connect 集成 | 安装 Sibelius 后生成原生 SIB |
| Linux／Windows 原生制谱软件 | 尚未验证 | Python 包可能可安装，原生软件验收待补 |

MCP extra 要求 Python 3.10 或更高版本。音频后端另有自己的运行时和模型要求。

## PDF／图片制谱

Agent 准备素材、读谱并提供制谱步骤：

```bash
yuezheng prepare score.pdf --output work/source
yuezheng build-score work/plan.json --output score.mscz
```

MCP 对应 `score_transcribe` 和 `musescore_build_score`。
[examples/native-plan.json](examples/native-plan.json) 提供原创演示音乐。
修改使用 `musescore_apply_plan` 或 `yuezheng apply-plan`，保留创建时返回的准确目标。
文件后端在私有副本中执行，检查匹配的执行记录后才发布结果。
参见[记谱指令和支持范围](skills/yuezheng/references/editor-plan.md)。
Audiveris 保留为可选辅助；原图和页序映射都会保留。

## 音频转为音乐事件

```bash
yuezheng audio-backends
yuezheng transcribe-audio recording.wav --output work/audio --hint mixed
# 有需要时：
yuezheng separate-audio recording.wav --output work/stems
```

MCP 对应 `audio_backends`、`audio_transcribe`、`audio_separate`。
Agent 在内部决定提示和工具，用户无需选择模型。
`--hint piano` 优先 Transkun，`solo` 优先 Basic Pitch，`mixed`／`auto` 优先 YourMT3。
推理失败会切换引擎。`--combine` 保留两份候选供 Agent 判断，不会机械叠加两份音符。
相同任务复用经过检查的文件，失败时保留素材和尝试记录，供后续恢复。

单独配置后端使用 `yuezheng audio-install ENGINE`。
通过 `SCOREBRIDGE_AUDIO_HOME` 或 `--cache-dir` 设置模型目录。
导入检查与实际推理验证分别记录，两者都不是识别准确率。
Basic Pitch 不识别乐器，不能把它默认写出的钢琴程序号当成识别到了钢琴。
鼓音轨需要支持打击乐的转录后端。

## 按需输出文件与原生工程

```bash
yuezheng music-plan work/events.json --output work/music-plan.json --bpm 96
yuezheng deliver-music work/music-plan.json --output final --formats mscz
# 用户需要时：
yuezheng deliver-music work/music-plan.json --output final --formats musicxml pdf midi ace sib
```

MCP 对应 `music_plan`、`music_deliver`、`ace_status`、`sibelius_status` 和
`sibelius_create_score`。Agent 在内部提供音乐上下文，
用户不必填写施工计划。已有图片制谱计划也可装入同一格式。演奏 MIDI 保留原始事件
时间；音频自动记谱使用暂定网格，独立于演奏数据。精细记谱仍通过 Agent 编写的
软件编辑指令实现。

ACE Studio 需已运行并开启 External Agent Access。官方 CLI 适配器创建独立工程，
绑定已安装的真实音源，保存并重新打开回读，随后恢复原工程。工程路径取自 ACE
保存响应。AI 乐器使用原生表情参数；普通 MIDI／插件轨保留并验证 MIDI CC 和力度，
AI 轨尚未映射的表情会明确记录。多乐器插件需要真正选择预设或状态。
参见[音乐计划及 ACE 说明](skills/yuezheng/references/music-plan.md)。

Sibelius 输出使用官方本机 Sibelius Connect WebSocket 和随工具提供的 ManuScript
桥接插件。先运行 `yuezheng sibelius-install-plugin`，在 Sibelius 中开启 1898
端口的 Sibelius Connect，再在 `deliver-music` 中请求 `sib`；适配器只在 Sibelius
确认保存成功且文件真实存在后发布 `.sib`。

## 编辑接口与开发

可选 MuseScore 实时编辑使用仓库内的 QML／WebSocket 插件：
运行 `bash scripts/install_musescore_plugin.sh`，在 MuseScore 启用后，用
`yuezheng editor-status` 检查。默认文件工作流无需实时插件。
参见[编辑接口](skills/yuezheng/references/editor-plan.md)、
[真实软件验证](tests/LIVE_EDITOR_RESULTS.md)和[交付记录](DELIVERY.md)。

本次升级实现约定的五个工作包：引擎路由、统一音乐计划、按需文件输出、首个原生
DAW 适配器、统一 Skill／CLI／MCP 验收。后续软件复用同一音乐计划扩展。
复杂录音准确度按输入类别实测，不用一个百分比代表所有音乐。中英文项目说明同步维护。

Yuezheng 使用 Apache License 2.0，详见 [LICENSE](LICENSE)；版本历史见
[CHANGELOG.md](CHANGELOG.md)。

公开品牌和主命令现在使用 **Yuezheng**。为兼容已有项目，`scorebridge` Python
导入路径、CLI 别名、内部计划格式和旧环境变量仍然保留。

```bash
python -m pip install -e '.[test,image,audio,mcp,websocket]'
pytest -q
```
