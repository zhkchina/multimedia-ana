# FunASR Audio Service Plan

本文档用于记录 `audio` 服务的当前实现方案与已知限制。

## 目标

在当前仓库内新增一组与 `video-vl` 平行的音频分析服务，用于：

- 中文电影音频离线转写
- 长音频自动切段
- 为后续时间戳、对话分析、情绪线索分析预留扩展位

约束保持与现有项目一致：

- 所有能力通过 Docker 提供
- 宿主机不安装 Python 运行依赖
- 使用 `/data/multimedia-ana` 作为统一数据根目录
- API 常驻，worker 按需拉起
- 容器内任务串行，容器之间可独立运行
- 避免 root 污染宿主目录

## 模型结论

当前阶段优先处理中文电影音频，因此首选：

- `iic/SenseVoiceSmall`
- `fsmn-vad`

选择原因：

- `SenseVoiceSmall` 官方定位不只是 ASR，还支持 `LID / SER / AED`，更适合电影理解而不仅是纯转写。
- `fsmn-vad` 先做语音切段，可以稳定处理长音频。
- 官方 README 直接给出了 `SenseVoiceSmall + fsmn-vad` 的调用示例。
- `AED` 对当前项目不是附属能力，而是下一步工作流中的重要参考标记。

不作为第一版主方案的模型：

- `paraformer-zh`
  - 更适合中文 ASR 与时间戳专项，不作为当前通用电影音频主模型
- `Whisper-large-v3` / `turbo`
  - 更重，当前不是首选路线

参考：

- FunASR README: https://github.com/modelscope/FunASR/blob/main/README.md
- FunASR Tutorial: https://github.com/modelscope/FunASR/blob/main/docs/tutorial/README.md

## 服务形态

建议新增一组独立服务：

- `audio-api`
- `audio-worker`

设计意图：

- `audio-api` 常驻，负责 job 接口、状态查询、调度 Docker worker
- `audio-worker` 按需启动，执行 FunASR 推理，空闲退出

不建议第一版把音频逻辑直接并进当前 `docker-api`，原因：

- 音频与视频 VL 的依赖和结果结构差异很大
- 资源使用模式不同
- 独立服务边界更清晰，便于后续扩展与排障

## Docker 镜像方案

推荐镜像：

- `audio-api`: `python:3.11-slim`
- `audio-worker`: `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`

说明：

- 本机已经验证 `pytorch:2.8.0-cuda12.8-cudnn9-devel` 可适配当前硬件。
- 如果允许重新拉取同系列 `runtime` 镜像，则 `runtime` 更适合作为 `audio-worker` 的基础镜像：
  - 语义更准确
  - 镜像更轻
  - 不额外携带编译工具链
- 若后续发现 `runtime` 与 FunASR 依赖有兼容问题，再回退到本机已验证的 `devel` 版本。

当前优先建议：

- 首先尝试 `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`
- 保留回退方案：`pytorch/pytorch:2.8.0-cuda12.8-cudnn9-devel`

## 目录规划

建议在当前仓库内新增：

- `app/audio_api/`
- `app/audio_worker/`
- `requirements/audio_api.txt`
- `requirements/audio_worker.txt`
- `Dockerfile.audio_api`
- `Dockerfile.audio_worker`

数据目录：

- `/data/multimedia-ana/audio/jobs`
- `/data/multimedia-ana/audio/output`
- `/data/multimedia-ana/audio/cache`
- `/data/multimedia-ana/audio/logs`

## API 方案

第一版建议只暴露最小接口。

### `POST /jobs/asr`

提交音频分析任务。

请求体：

```json
{
  "audio_uri": "/data/multimedia-ana/example-audio/movie.wav",
  "profile": "movie_zh",
  "language": "auto"
}
```

字段说明：

- `audio_uri`: 必填，宿主机可访问路径
- `profile`: 第一版先固定支持 `movie_zh`
- `language`: 默认 `auto`

响应：

```json
{
  "job_id": "job_20260422_120000_abcd1234",
  "status": "queued"
}
```

### `GET /jobs/{job_id}`

查询任务状态。

响应示例：

```json
{
  "job_id": "job_20260422_120000_abcd1234",
  "status": "running",
  "service": "audio",
  "created_at": "2026-04-22T12:00:00+08:00",
  "updated_at": "2026-04-22T12:00:08+08:00",
  "result_path": null,
  "error": null
}
```

状态统一为：

- `queued`
- `running`
- `succeeded`
- `failed`

### `GET /jobs/{job_id}/result`

返回结果 JSON。

当前实现返回结构：

```json
{
  "backend": "funasr",
  "model_id": "iic/SenseVoiceSmall",
  "vad_model_id": "fsmn-vad",
  "audio_uri": "/data/multimedia-ana/example-audio/movie.wav",
  "profile": "movie_zh",
  "language": "auto",
  "text": "完整转写文本",
  "aed": {
    "available": true,
    "raw": {}
  },
  "segments": [],
  "metadata": {
    "duration_seconds": 7123.4
  },
  "raw_result": {}
}
```

说明：

- `SenseVoiceSmall` 官方能力包含 `AED`，因此第一版结果中应显式保留 `aed` 字段。
- 由于官方 README 主要展示识别流程，没有将 `AED` 的稳定输出 schema 完整定义为固定结构，因此第一版建议：
  - 保留 `aed.raw`
  - 首次真实样本验证后，再决定是否固化额外事件字段结构
- `AED` 在当前项目中用于后续工作流参考，不应只埋在 `raw_result` 中。
- `segments` 字段在当前实现中始终保留，但是否有内容取决于模型原始返回里是否包含可提取的时间轴字段。
- 按当前 `SenseVoiceSmall + fsmn-vad` 路线，实际样本已验证可能只返回 `text`，此时 `segments` 会是空数组。

### `GET /health`

健康检查：

```json
{
  "status": "ok",
  "service": "audio-api"
}
```

## Profile 方案

第一版建议不要把底层 FunASR 参数直接暴露给调用方。

仅定义一个 profile：

- `movie_zh`

内部参数建议：

- `model="iic/SenseVoiceSmall"`
- `vad_model="fsmn-vad"`
- `vad_kwargs.max_single_segment_time=30000`
- `language="auto"`
- `use_itn=True`
- `batch_size_s=60`
- `merge_vad=True`
- `merge_length_s=15`

## Worker 推理方案

按官方推荐方式，使用 Python `AutoModel(...)` 调用：

```python
from funasr import AutoModel

model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    vad_kwargs={"max_single_segment_time": 30000},
    device="cuda:0",
)
```

推理参数：

```python
res = model.generate(
    input=audio_path,
    cache={},
    language="auto",
    use_itn=True,
    batch_size_s=60,
    merge_vad=True,
    merge_length_s=15,
)
```

参考：

- https://github.com/modelscope/FunASR/blob/main/README.md

## 音频预处理方案

第一版建议在 `audio-worker` 内部固定加入一层 `ffmpeg` 预处理，不单独拆为独立服务。

原因：

- 电影音频来源复杂，输入格式不能假设总是标准音频
- 后续可能直接处理视频抽出的音轨
- FunASR 在统一格式输入下更稳定
- 标准化后的音频也便于后续 `VAD / ASR / 时间轴 / 对齐` 复用

建议支持的输入类型：

- `wav`
- `mp3`
- `m4a`
- `flac`
- 常见视频文件中的音轨

建议统一转为：

- `wav`
- `mono`
- `16kHz`
- `pcm_s16le`

参考转换命令：

```bash
ffmpeg -y -i input.xxx -vn -ac 1 -ar 16000 -sample_fmt s16 output.wav
```

结论：

- 需要在 Docker 内做 `ffmpeg` 预处理
- 但第一版不需要拆成独立 `preprocess-api / preprocess-worker`
- 预处理作为 `audio-worker` 内部固定步骤更合适

## 部署方案

建议在 `docker-compose.yml` 中新增两个服务：

- `audio-api`
- `audio-worker`

端口建议：

- `audio-api`: `0.0.0.0:18088:7860`

环境变量建议：

- `DATA_ROOT=/data/multimedia-ana`
- `AUDIO_MODEL_ID=iic/SenseVoiceSmall`
- `AUDIO_VAD_MODEL_ID=fsmn-vad`
- `AUDIO_WORKER_IDLE_TIMEOUT_SECONDS=1800`
- `AUDIO_WORKER_POLL_INTERVAL_SECONDS=5`
- `MODELSCOPE_CACHE=/data/multimedia-ana/audio/cache/modelscope`
- `HF_HOME=/data/multimedia-ana/audio/cache/huggingface`
- `HOST_UID=1001`
- `HOST_GID=1003`

权限策略：

- API 与 worker 都使用宿主 UID/GID 运行
- 继续避免 `root:root` 污染 `/data/multimedia-ana`

## 当前实现状态

当前仓库已经落地：

- `audio-api + audio-worker`
- 复用现有 `job/store/scheduler` 机制
- 输入仅接受宿主机可访问的本地文件路径
- `audio-worker` 内固定执行 `ffmpeg` 预处理
- `audio-worker` 强制要求 GPU 可用，否则直接失败
- 模型首次启动时在容器内联网下载到 `/data/multimedia-ana/audio/cache`

模型调用保持为：

- `model="iic/SenseVoiceSmall"`
- `vad_model="fsmn-vad"`
- `device="cuda:0"`
- `disable_update=True`

其中 `disable_update=True` 是当前实现的必要设置，用于关闭 `FunASR` 初始化时的 PyPI 更新检查，避免首次启动被无关的版本检查阻塞；它不影响后续在容器内联网下载模型文件。

## 当前限制

保留这一版时，需要明确接受以下限制：

- 当前链路已经验证可以稳定完成 GPU 转写，但还不能保证返回逐段时间戳。
- 已验证样本中，`SenseVoiceSmall` 的原始返回只有 `text`，没有 `sentence_info`、`segments`、`timestamp` 等字段，因此结果里的 `segments` 为空数组。
- 当前结果中的 `text` 仍可能包含 `SenseVoice` 控制标签，如 `<|zh|><|HAPPY|><|BGM|><|withitn|>`；这是因为这一版保留原始文本，没有额外接入 `rich_transcription_postprocess(...)` 清洗。
- `aed` 字段在结构上已保留，但是否有值取决于模型该次返回；当前已验证样本中 `aed.raw` 可能为 `null`。
- 当前方案的重点是“本地离线音频转写服务跑通并稳定调度”，不是“时间戳专项方案”；如果后续目标是稳定输出逐段 `start_ms/end_ms`，需要补充时间戳模型或单独时间轴能力。

## 第一版不做的内容

当前不建议在第一版一起做：

- `cam++`
- 说话人分离
- `fa-zh`
- 强制对齐
- 实时流式 ASR
- 对 `SenseVoice` 文本标签做额外后处理清洗

原因：

- 第一版目标是先把中文电影音频离线分析跑稳
- 先保证结果结构、任务调度和资源回收稳定
- `AED` 不在延后项中，因为它已经属于 `SenseVoiceSmall` 的能力范围，第一版应保留其输出

## 后续扩展方向

在第一版稳定后，再按能力扩展：

- `POST /jobs/vad`
- `POST /jobs/timestamp`
- `POST /jobs/diarization`

届时可考虑补充：

- `paraformer-zh`
- `fa-zh`
- `cam++`

## 当前结论

对于当前项目和当前硬件，最合适的审核结论是：

- 采用独立的 `audio-api + audio-worker`
- 模型组合为 `SenseVoiceSmall + fsmn-vad`
- 第一版结果中显式保留 `AED` 输出，作为后续工作流的重要参考标记
- 在 `audio-worker` 内固定加入 `ffmpeg` 预处理，将输入统一为标准音频格式
- 延续当前仓库已有的 `api 常驻 + worker 按需拉起` 风格
- `audio-worker` 优先尝试 `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`
- 当前实现版本保留，作为本地 GPU 音频转写基线
- 当前版本不承诺稳定输出逐段时间戳，`segments` 为空时视为当前模型路线下的已知限制
