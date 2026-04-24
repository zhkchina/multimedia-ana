# Audio SED Pipeline Design

本文档定义 `audio-sed` 新模块的初版设计。当前阶段先搭 worker 调试框架，不实现完整 API，不承诺生产级模型效果。

## 目标

`audio-sed` 用于从电影片段中识别打斗、开枪、撞击、爆炸等音频事件候选，为上层二创剪辑和卡点视频生成流程提供可融合的音频侧时间轴。

PANNs 试验已经证明：封闭 AudioSet 标签模型在当前电影样本上召回不足，不能作为主路线。新方案将本模块范围收敛为两阶段音频流水线：

1. 电影音频源分离，优先得到 `effects` stem。
2. 在 `effects` stem 上做开放词汇声音事件定位。

视频识别、音画融合、最终动作场面判断和最终精确定位不放在本模块内。调用方负责综合 `video-vl` 输出、`audio-sed` 输出和必要的后处理，判断是否存在目标打斗、开枪、爆破场面。

## 当前样本事实

测试文件位于：

```text
/data/multimedia-ana/example-video/proxy_v1.local.*.clip.mp4
```

当前已有两个样本：

```text
proxy_v1.local.00h19m34s-00h19m46s.clip.mp4  12.012s  2.5MB
proxy_v1.local.00h19m46s-00h20m00s.clip.mp4  14.014s  2.0MB
```

两个样本结构一致：

- 1 路 H.264 视频，`640x268`，约 `23.98fps`
- 2 条 AAC 立体声音轨，`48kHz`
- 音轨 `0:1` 是默认音轨
- 音轨 `0:2` 是非默认音轨

因此初版必须逐音轨处理，不能只看默认音轨，也不能在服务端提前把多音轨混成一条。

当前输出约束：两条音轨都必须输出，且必须按音轨独立输出。平台层不合并多音轨事件，也不选择“最佳音轨”。下游调用方根据业务策略决定使用默认音轨、非默认音轨或多音轨融合。

## 工程形态

继续采用双 Docker：

- `audio-sed-api`：轻量常驻，只负责监听、创建任务、拉起 worker。
- `audio-sed-worker`：重型临时容器，内部串行执行两阶段音频 pipeline，任务完成或空闲后释放 GPU。

初版可先不实现完整 API，先实现 worker 容器内的调试入口，例如：

```bash
python3 -m app.audio_sed_worker.pipeline \
  --input /data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4 \
  --work-dir /data/multimedia-ana/audio-sed/runtime/debug/<run_id> \
  --profile action_beats_v1
```

但目录、镜像、配置仍按最终服务设计：

```text
/data/multimedia-ana/audio-sed/
  cache/
  logs/
  models/
  runtime/
    debug/
    tasks/
  output/
```

约束：

- 所有 Python 依赖只进 Docker，不污染宿主机。
- 模型、checkpoint、缓存、大文件只放 `/data/multimedia-ana/audio-sed/`。
- 容器必须以宿主机 UID/GID 运行，避免生成 root 文件。
- 输入必须是容器可见真实路径，推荐 `/data/multimedia-ana/` 或 `/data/assets/`。
- worker 内同一时间只跑一个任务。
- 长视频不直接进入本 worker，必须先切成 scene/clip。
- 平台默认资源策略为：BandIt 使用 GPU，OpenFLAM 使用 CPU。
- 平台默认稳定配置为：BandIt inference `batch_size=8`，避免 `4090D 24GB` 上 batch 24 接近满显存。

### 初版 Docker 选择

`audio-sed-worker` 初版使用：

```dockerfile
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
```

原因：

- 本仓库 `audio-worker` 已使用同系列 PyTorch CUDA runtime，和当前 `4090D` 环境适配风险最低。
- OpenFLAM、CASS/Demucs/BandIt 类模型都以 PyTorch 为主要运行时，避免在 `python:slim` 中重新拼 CUDA wheel。
- OpenFLAM `1.0.1` 要求 `torch>=2.6,<2.8`，因此不能使用 `torch 2.8` 基础镜像；否则 pip 会尝试卸载基础镜像里的 torch/CUDA 组件并下载 PyPI CUDA wheel。
- 初版只做推理调试，不需要 `devel` 镜像的编译工具链。
- worker 比普通音频模块更重，但仍然按需启动，用完释放 GPU。

当前构建文件：

```text
Dockerfile.audio_sed_worker
requirements/audio_sed_worker.txt
scripts/download_audio_sed_models.sh
scripts/run_audio_sed_debug.sh
```

模型和外部研究代码不在镜像 build 阶段下载，由 `scripts/download_audio_sed_models.sh` 单独写入：

```text
/data/multimedia-ana/audio-sed/vendor/bandit/
/data/multimedia-ana/audio-sed/models/bandit/
/data/multimedia-ana/audio-sed/models/openflam/
```

默认 BandIt checkpoint：

```text
dnr-3s-mus64-l1snr
```

下载脚本会把 checkpoint 放到 `checkpoints/` 下，并把 repo 中匹配的 experiment yaml 复制为 `hparams.yaml`，以满足 BandIt inference 的目录约定。同时生成稳定推理配置目录：

```text
/data/multimedia-ana/audio-sed/models/bandit/dnr-3s-mus64-l1snr-bs8/
```

该目录复用同一份 checkpoint，但 `hparams.yaml` 指向 BandIt `configs/inference/default8.yaml`。平台默认 worker 使用 `-bs8` 目录；原始 batch 24 配置只保留作离线性能对照，不作为默认运行配置。

## Pipeline Stages

### 1. Source Separation

目标：从每条输入音轨中分离出 `dialogue / music / effects`，后续默认只在 `effects` stem 上找事件。

优先调研方向：

- CASS：电影音频源分离任务，标准三 stem 是 dialogue / music / effects。
- DnR / DnR v3：当前公开 CASS 数据集路线，v3 改善了多语言、stem 污染、响度和 mastering 分布。
- AV-CASS：利用视频线索做电影音频源分离，适合电影中声音与动作强绑定的场景。

#### BandIt 选择逻辑

BandIt 被选为当前平台基线，不代表它是最终效果最优模型。选择原因是工程基线优先：

- 任务匹配：BandIt 面向 Cinematic Audio Source Separation，标准目标正是 `dialogue / music / effects` 三 stem。
- 工程可用：有公开代码、官方 inference 入口、Zenodo checkpoint，已在本机 Docker 内跑通。
- 模块边界清晰：BandIt 是 audio-only，不引入视频编码器或跨模态模型，符合 `audio-sed` 只产出音频侧候选的初版边界。
- 资源可控：默认 batch 8 后，`4090D 24GB` 上峰值约 `8.7GB`，可以稳定作为 worker 的 GPU 阶段。
- 可替换：pipeline 通过 `--bandit-model-name` 和 `--bandit-ckpt-path` 切换 checkpoint，便于横向测试。

没有选择 AV-CASS 作为当前默认的原因：

- AV-CASS 理论上更适合电影场景，因为它使用视频线索，可能减少 stem 错放。
- 但它会引入视频输入和视觉模型，破坏当前 `audio-sed` 音频侧模块边界。
- 它的工程部署、权重可用性、许可证、资源消耗都需要单独验证。
- 因此 AV-CASS 进入后续优化方向，不进入当前平台基线。

短期可行优化是横向测试多个 BandIt checkpoint。平台提供下载和网格测试脚本，但 checkpoint 选择属于效果验证问题，不改变当前 baseline 结构。

初版策略：

- 每条原始音轨单独分离，输出 `stream_<index>/effects.wav`。
- 默认分离后端接入 BandIt，使用 DnR 三 stem checkpoint，输出 `dialogue / music / effects`。
- 标准输出 `effects.wav` 必须精确对应 BandIt 纯 `effects.wav`，不能使用 `effects+residual.wav`、`music+effects.wav` 等组合 stem。
- 默认使用 BandIt batch 8 稳定配置。实测 12s/14s 两个样本峰值约 `8.7GB`，明显低于 batch 24 的接近 `24GB`。
- 如果显式传 `--allow-separation-fallback`，分离失败时才允许 fallback 到原始音轨作为 `effects` 输入，并在 metadata 中标记 `separation_status=fallback_original_audio`。
- 分离阶段只负责 stem，不做事件判断。
- BandIt 是当前工程友好的 DnR/CASS 路线：代码 Apache-2.0，官方 README 提供 inference 入口，权重在 Zenodo。
- BandIt 权重许可为 CC-BY-NC-4.0，当前按本地研究验证后端使用。
- `passthrough` 只保留为显式调试/容灾后端，不作为默认方案。

输出 artifact：

```text
streams/<stream_index>/mix.wav
streams/<stream_index>/effects.wav
streams/<stream_index>/dialogue.wav
streams/<stream_index>/music.wav
streams/<stream_index>/separation_command.json
```

### 2. Open-Vocabulary Audio Localization

目标：在 `effects.wav` 上用开放词汇 prompt 找事件候选，不再依赖 PANNs 这类封闭标签集合。

优先调研方向：

- FLAM / OpenFLAM：Frame-Wise Language-Audio Modeling，支持 zero-shot open-vocabulary sound event localization。
- OpenFLAM 当前公开模型要求音频 `48kHz`，可直接匹配测试样本的音轨采样率。
- FLAM 的本质输出应被视为“text prompt 对时间帧的相似度曲线”，后处理再把曲线变成事件候选。
- OpenFLAM 的公开包可通过 `pip install openflam` 安装；当前 requirements 固定为 `openflam==1.0.1`。
- OpenFLAM 代码和模型是 Adobe Research 非商业许可证，当前只作为本地研究验证后端，后续若要分发或商用需要重新确认授权。
- OpenFLAM/HTSAT 对单次音频输入长度有限制，不能把 12s/14s clip 整段直接送入模型。当前实现默认按 `9.5s` 窗口、`0.5s` 重叠分块推理，再把每个块的候选时间加回全局时间轴。
- OpenFLAM 默认运行在 CPU 上。实测 14s effects、13 prompts、2 chunks 下 CPU 推理约 `1.4s`，相对 BandIt 不是主瓶颈，同时避免与 BandIt 争抢 GPU 显存。
- OpenFLAM 输入固定为每条音轨分离出的 `effects.wav`。
- OpenFLAM 输出必须经过平台侧基础伪影过滤：边界过滤和局部能量门控。

#### OpenFLAM 选择逻辑

OpenFLAM 被选为当前开放词汇定位基线，不代表最终只能使用 OpenFLAM。选择原因：

- 任务匹配：本模块需要的是 `body punch impact`、`weapon hit`、`bullet impact` 这类开放词汇事件定位，而不是封闭标签分类。
- 输出形态合适：OpenFLAM 提供 frame-wise / local audio-text similarity，可以转成 `start_ms / peak_ms / end_ms` 事件候选。
- 替代 PANNs 路线：PANNs / AudioSet 标签空间与电影动作声不贴合，前期测试已证明效果不足。
- 工程可接入：`openflam==1.0.1` 可安装，模型可本地缓存，已在 Docker 内跑通。
- 资源轻：CPU 推理成本相对 BandIt 很小，可避免 GPU 常驻争抢。
- 下游友好：保留原始 prompt、score、局部能量，调用方可自行调阈值和融合视频结果。

没有选择 CLAP/AudioCLIP 作为当前默认的原因：

- CLAP 更常见于 clip-level audio-text 检索，若用于时间定位，需要平台自己实现滑窗、平滑、合并和阈值策略。
- OpenFLAM 的 frame-wise 设计更贴近当前“开放词汇时间定位”需求。

没有选择音频大模型/Audio LLM 的原因：

- 多数音频大模型更偏理解、问答或描述，不一定稳定输出结构化时间边界。
- 资源更重，解析自然语言输出会增加平台不确定性。

后续可替换方向包括：更强 frame-level audio-text localization 模型、CLAP 滑窗对照、用 OpenFLAM 候选训练轻量二级重排模型、结合音频 onset 做时间精修。

平台默认后处理：

```text
threshold = 0.2
min_event_ms = 120
merge_gap_ms = 160
openflam_chunk_seconds = 9.5
openflam_chunk_overlap_seconds = 0.5
prompt_batch_size = 8
boundary_ignore_ms = 300
min_event_local_rms_dbfs = -45.0
event_local_rms_window_ms = 240
```

其中 `boundary_ignore_ms` 过滤片段首尾边界候选，避免 `0ms` 等 chunk/clip 边界误报；`min_event_local_rms_dbfs` 要求事件峰值附近 effects 音频有足够局部能量，避免 OpenFLAM 在近似静音或分离伪影上给出高分候选。

这些参数是下游业务方可调项。平台默认值只提供稳定基线，不代表最终业务阈值。

初版 profile：

```text
action_beats_v1:
  fight:
    - body punch impact
    - kick impact
    - slap or smack
    - body fall impact
    - weapon hit
    - metal hit
    - glass shatter
  gunfire:
    - single gunshot
    - rapid gunfire
    - bullet impact
  explosion:
    - explosion
    - fire burst
    - debris impact after explosion
```

输出候选必须保留原始 prompt，不只返回 domain：

```json
{
  "event_id": "clip:s2:fight:body_punch_impact:1840",
  "audio_stream_index": 2,
  "is_default_stream": false,
  "stem": "effects",
  "domain": "fight",
  "prompt": "body punch impact",
  "start_ms": 1760,
  "peak_ms": 1840,
  "end_ms": 2030,
  "score": 0.71,
  "event_local_rms_dbfs": -23.4,
  "audio_peak_dbfs": -4.1,
  "audio_rms_dbfs": -23.9,
  "source": "openflam"
}
```

## Out of Scope

以下能力不属于 `audio-sed` 初版模块范围：

- 视频复核：由调用方结合 `video-vl` 或其它视觉模型完成。
- 音画融合：由调用方把视频识别结果、`audio-sed` 事件候选和 scene 时间轴做 join。
- 最终场面判断：由调用方判断是否存在目标打斗、开枪、爆破场面。
- 最终精确定位：由调用方决定是否用 onset、视频动作峰值、镜头剪辑点或其它信号做最终吸附。

这样做的理由：

- 本机 `4090D 24GB` 无法可靠同时承载音频分离、开放词汇音频模型和视频模型。
- 现有 `Qwen3-VL-8B` 本地记录峰值显存约 `20GB`，不适合塞入同一个 `audio-sed-worker`。
- 本模块保持音频侧职责清晰，输出可融合候选，避免过早做跨模态编排。

## Debug Output Contract

初版即使不做 API，也必须输出一个稳定 JSON，方便后续接入 `/v1/tasks`。

建议文件：

```text
result.json
pipeline_trace.json
streams/<stream_index>/stream_result.json
streams/<stream_index>/events.jsonl
```

`result.json` 顶层只做汇总，不输出合并后的顶层 `events`。事件必须在每条音轨内独立输出：

```json
{
  "service": "audio-sed",
  "mode": "debug-pipeline",
  "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4",
  "profile": "action_beats_v1",
  "summary": {
    "duration_ms": 12012,
    "audio_stream_count": 2,
    "analyzed_stream_count": 2,
    "candidate_count": 12,
    "event_count": 12
  },
  "audio_streams": [
    {
      "stream_index": 1,
      "is_default_stream": true,
      "mix_path": ".../streams/stream_1/mix.wav",
      "effects_path": ".../streams/stream_1/effects.wav",
      "events_jsonl": ".../streams/stream_1/events.jsonl",
      "event_count": 8,
      "events": []
    },
    {
      "stream_index": 2,
      "is_default_stream": false,
      "mix_path": ".../streams/stream_2/mix.wav",
      "effects_path": ".../streams/stream_2/effects.wav",
      "events_jsonl": ".../streams/stream_2/events.jsonl",
      "event_count": 4,
      "events": []
    }
  ],
  "metadata": {
    "pipeline_version": "audio_sed_pipeline_v0",
    "event_layout": "per_audio_stream",
    "result_json": ".../result.json"
  }
}
```

最终事件对象：

```json
{
  "event_id": "clip:s2:fight:body_punch_impact:1848",
  "file_uri": "...",
  "clip_id": "proxy_v1.local.00h19m34s-00h19m46s.clip",
  "audio_stream_index": 2,
  "is_default_stream": false,
  "stem": "effects",
  "domain": "fight",
  "prompt": "body punch impact",
  "start_ms": 1760,
  "peak_ms": 1840,
  "end_ms": 2030,
  "score": 0.71,
  "event_local_rms_dbfs": -23.4,
  "audio_peak_dbfs": -8.4,
  "audio_rms_dbfs": -19.2
}
```

`streams/<stream_index>/events.jsonl` 每行一个最终事件，便于后续导入 SQLite、DuckDB 或人工审核。顶层不再提供合并 `events.jsonl`，避免平台层暗含多音轨融合策略。

`pipeline_trace.json` 记录每阶段耗时、模型名、设备、输入输出文件、错误和 fallback，不作为业务主结果。

## Worker Resource Strategy

这个 worker 会比普通单模型音频模块更重，但不再加载视频模型。平台侧固定资源策略：

- 阶段串行执行，不并发加载多个大模型。
- BandIt 使用 GPU，batch size 固定为 8。
- OpenFLAM 使用 CPU，避免与 BandIt 争抢 GPU 显存。
- worker 内同一时间只跑一个任务。
- 若后续做常驻 worker，OpenFLAM 可以 CPU 常驻；BandIt 是否常驻需要以显存稳定为优先。
- 每阶段结束后释放不用的模型对象，并在 CUDA 后端执行 cache 清理。
- 每个阶段必须有 timeout 和清晰错误。
- 任务失败时保留 `pipeline_trace.json` 和 stderr 摘要，便于判断是哪一阶段失败。

实测记录：

```text
BandIt batch 24: 14s 样本峰值约 24076MB，接近 4090D 24GB 上限。
BandIt batch 8:  12s/14s 样本峰值约 8716MB。
OpenFLAM GPU:    14s 样本 reserved 约 870MB，推理约 0.24s。
OpenFLAM CPU:    14s 样本推理约 1.40s，不占 GPU。
```

因此平台默认选择 `BandIt GPU batch 8 + OpenFLAM CPU`。OpenFLAM GPU 只作为性能实验，不作为稳定默认。

## Initial Validation Plan

第一轮只验证两条样本：

```text
/data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4
/data/multimedia-ana/example-video/proxy_v1.local.00h19m46s-00h20m00s.clip.mp4
```

已知期望：

- 前者包含打斗候选，应能产生若干 `fight` 音频事件候选。
- 后者不应产生大量高分 `fight` 音频候选，可用于观察误报。

验收标准：

- worker 能在 Docker 内完成端到端调试运行。
- 每条音轨都有独立 stage 结果。
- `result.json` 顶层不合并多音轨事件。
- 每条音轨都有独立 `stream_result.json` 和 `events.jsonl`。
- 即使 CASS 或 FLAM 模型暂不可用，也能用 fallback/stub 明确产出 trace，而不是静默跳过。
- 输出 JSON 字段稳定，后续 API 只需要包装任务状态，不需要重设计业务结构。
- 人工审核能从每条音轨的 `events.jsonl` 快速比较两个 clip 的候选差异。
- 调用方可以直接按 `file_uri + clip_id + audio_stream_index + prompt/domain + start_ms/peak_ms/end_ms` 与视频识别结果做融合。

当前两个样本的稳定链路输出：

```text
/data/multimedia-ana/audio-sed/runtime/debug/separate_streams_boundary_00h19m34s/result.json
/data/multimedia-ana/audio-sed/runtime/debug/separate_streams_boundary_00h19m46s/result.json
```

统计：

```text
打斗切片:
  stream_1 default=true   events=17
  stream_2 default=false  events=27
  total=44

对话切片:
  stream_1 default=true   events=8
  stream_2 default=false  events=4
  total=12
```

这个结果只作为平台链路 sanity check，不作为最终业务阈值。阈值、打分解释、多音轨融合由下游调用方在流程确定后调参。

## Open Questions

- CASS/AV-CASS 是否有可直接部署的公开 checkpoint；若没有，初版可能要先用 DnR/CASS audio-only baseline 或普通 stem separation 近似。
- OpenFLAM 的非商业许可证是否满足当前使用场景；如果不满足，只能做本地研究验证，不能作为可分发默认后端。
- 调用方侧融合模块需要定义统一 join 规则，例如按 `clip_id` 和时间窗重叠，把音频候选与视频动作结果组合。
- 最终 onset / 动作峰值吸附应放在调用方侧，还是后续单独做一个轻量 refinement 工具，需要在融合模块设计时决定。

## References

- FLAM / OpenFLAM: https://flam-model.github.io/ and https://huggingface.co/kechenadobe/OpenFLAM
- FLAM ICML 2025 paper: https://proceedings.mlr.press/v267/wu25ab.html
- AV-CASS paper page: https://papers.cool/arxiv/2603.26113
- DnR v3 dataset record: https://zenodo.org/doi/10.5281/zenodo.12659887
- PANNs experiment retrospective: `docs/audio-sed-panns-test-retrospective.md`
