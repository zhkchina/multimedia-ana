# PANNs Audio SED Service Design

本文档设计一个基于 PANNs 的音频事件检测服务，用于从已切好的 scene 视频片段中产出枪声、击打声等动作卡点时间轴。本文只定义设计，不包含实现变更。

## 背景

当前仓库已有三个服务：

- `qwen3-vl`：视频语义理解，`18086`，API + 按需 GPU worker。
- `scene`：场景切分，`18087`，单容器内串行执行。
- `audio`：ASR / AED / 段级时间轴，`18088`，API + 按需 GPU worker。

统一约束来自本仓库 README 和 `/home/kun/tools/agent.md`：

- 所有服务必须 Docker 化，不污染宿主机 Python 环境。
- 输入必须是容器可见真实文件路径，推荐 `/data/multimedia-ana/` 或 `/data/assets/`。
- 服务输出 JSON，一次只处理一个文件，调用方负责批量调度。
- GPU 或重模型服务采用双容器：轻量 API 常驻，worker 按需拉起和释放。
- 容器以宿主机 UID/GID 运行，模型、大文件、运行时文件放 `/data`。
- 端口监听 `0.0.0.0`，使用高位端口。
- 测试放 `qa/`，通过 Docker 执行。
- 每个服务需要 agent 友好的 readme。

## 目标

新增 `audio-sed` 服务，用 PANNs 做 sound event detection，第一版聚焦卡点动作时间轴：

- 输入：音频或 scene 视频片段。
- 输出：事件列表，包含 `label`、`start_ms`、`peak_ms`、`end_ms`、`score`。
- 时间默认相对输入片段起点；若调用方传入 `timeline_offset_ms`，额外返回源视频绝对时间。
- 第一版不做训练，不做人工标注平台，不做长期业务结果文件保存。

## 模型选择

第一版采用 PANNs，优先路线：

- 推理库：`panns-inference==0.1.1`
- 模型：`Cnn14` / PANNs AudioSet 527 类
- 输入采样率：`32000 Hz`
- 任务：`SoundEventDetection`

如果 `panns-inference` 对 framewise 时间轴、模型 checkpoint 或标签映射的控制不够，第二步再 vendor 官方 `qiuqiangkong/audioset_tagging_cnn` 的最小推理代码，使用 `Cnn14_DecisionLevelMax_mAP=0.385.pth`。

不建议第一版直接上 HTS-AT，因为官方代码维护和依赖稳定性更差；PANNs 更适合先打通 `scene -> sed -> card beat timeline` 的工程闭环。

## 镜像选择

### API 镜像

推荐：

```dockerfile
FROM python:3.11-slim
```

理由：

- 与现有 `audio-api` 形态一致。
- 只需要 FastAPI、Docker SDK、SQLite 状态读写，不需要 PyTorch。
- 常驻容器轻量，启动快。

### Worker 镜像

推荐 MVP：

```dockerfile
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
```

理由：

- 已被当前 `audio-worker` 采用，符合现有 CUDA 运行时选择。
- 预装 PyTorch/CUDA，避免在 slim 镜像里手工拼 CUDA、torch wheel。
- PANNs 是 CNN 推理，runtime 镜像足够，不需要 devel 工具链。
- 给后续 HTS-AT 或自训练 SED worker 保留升级空间。

不推荐：

- `python:3.11-slim + pip install torch`：镜像构建慢，CUDA wheel 和驱动匹配风险更高。
- `pytorch/*-devel`：MVP 不需要编译工具链，镜像更重。
- 把 checkpoint 烘进镜像：模型文件应放 `/data/multimedia-ana/audio-sed/models/`，避免污染 git 管理目录并便于替换。

Worker 系统依赖建议：

- `ffmpeg`：从视频抽音频、统一转码。
- 可选 `libsndfile1`：若 `soundfile` wheel 在目标环境缺底层库时启用。

Worker Python 依赖建议：

```text
panns-inference==0.1.1
librosa>=0.10,<0.11
soundfile>=0.12,<0.13
scipy>=1.11,<1.15
numpy>=1.26,<2.0
```

说明：`panns-inference` 本身较老，需在镜像验证阶段确认与 Python 3.11、当前 PyTorch 2.8 的兼容性。若不兼容，优先 vendor 最小推理代码，而不是降级整个工程基础镜像。

## 服务形态

新增两个容器：

- `audio-sed-api`
- `audio-sed-worker`

端口：

- 宿主机：`18089`
- 容器内：`7860`

服务名和镜像：

- API image：`multimedia-ana-audio-sed-api:local`
- Worker image：`multimedia-ana-audio-sed-worker:local`
- API container：`multimedia-ana-audio-sed-api`
- Worker container：`multimedia-ana-audio-sed-worker`

数据目录：

```text
/data/multimedia-ana/audio-sed/
  cache/
  logs/
  models/
  output/
  runtime/
    tasks.db
    worker_state.json
    tasks/{task_id}/
```

checkpoint 推荐路径：

```text
/data/multimedia-ana/audio-sed/models/Cnn14_DecisionLevelMax_mAP=0.385.pth
```

第一版建议 worker 在 checkpoint 缺失时直接失败并返回清晰错误，不默认联网下载。后续可提供独立脚本下载模型到 `/data`。

## API 设计

沿用统一接口：

- `GET /healthz`
- `GET /readyz`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`
- `POST /admin/worker/wakeup`
- `POST /admin/worker/shutdown`

最小请求：

```json
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/scene_001.mp4",
    "params": {
      "profile": "movie_beat_v1"
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
```

推荐请求：

```json
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/scene_001.mp4",
    "params": {
      "profile": "movie_beat_v1",
      "timeline_offset_ms": 123450,
      "target_labels": ["gunshot", "impact", "glass_break"],
      "threshold": 0.25,
      "min_event_ms": 60,
      "merge_gap_ms": 120,
      "nms_window_ms": 180,
      "peak_refine": true,
      "include_framewise": false
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
```

参数说明：

- `profile`：默认 `movie_beat_v1`。
- `timeline_offset_ms`：可选，输入 scene 在源视频中的起点毫秒。
- `target_labels`：可选，业务标签集合；默认 `["gunshot", "impact", "glass_break", "explosion"]`。
- `threshold`：全局检测阈值，默认 `0.25`。后续可支持 per-label 阈值。
- `min_event_ms`：过滤过短事件，默认 `60`。
- `merge_gap_ms`：同标签近邻事件合并间隔，默认 `120`。
- `nms_window_ms`：峰值去重窗口，默认 `180`。
- `peak_refine`：是否用 waveform onset / RMS peak 精修 `peak_ms`，默认 `true`。
- `include_framewise`：是否返回 framewise 分数，默认 `false`，只用于调试。

返回结果：

```json
{
  "service": "audio-sed",
  "backend": "panns",
  "model_id": "Cnn14_DecisionLevelMax",
  "file_uri": "/data/multimedia-ana/example-video/scene_001.mp4",
  "params": {
    "profile": "movie_beat_v1",
    "sample_rate_hz": 32000,
    "timeline_offset_ms": 123450,
    "target_labels": ["gunshot", "impact", "glass_break"],
    "threshold": 0.25,
    "peak_refine": true
  },
  "summary": {
    "duration_ms": 8420,
    "event_count": 2,
    "labels": {
      "gunshot": 1,
      "impact": 1
    }
  },
  "events": [
    {
      "index": 0,
      "label": "gunshot",
      "source_labels": ["Gunshot, gunfire"],
      "start_ms": 1320,
      "peak_ms": 1388,
      "end_ms": 1510,
      "absolute_start_ms": 124770,
      "absolute_peak_ms": 124838,
      "absolute_end_ms": 124960,
      "score": 0.83
    }
  ],
  "metadata": {
    "audio": {
      "sample_rate_hz": 32000,
      "channels": 1,
      "duration_seconds": 8.42
    },
    "preprocess": {
      "codec": "pcm_f32le",
      "source": "ffmpeg"
    },
    "device": "cuda:0"
  }
}
```

## 标签映射

PANNs 输出 AudioSet 527 类，业务层不直接暴露全部原始标签。第一版定义业务标签映射：

```text
gunshot:
  - Gunshot, gunfire

explosion:
  - Explosion
  - Fireworks

impact:
  - Slap, smack
  - Thump, thud
  - Knock
  - Whip
  - Generic impact sounds

glass_break:
  - Glass
  - Breaking
  - Shatter

metal_hit:
  - Clang
  - Clatter
  - Tools
```

实现时需要以实际 `panns_inference.labels` 或官方 `class_labels_indices.csv` 为准校验名称。不存在的标签不得静默忽略，应在启动日志中记录，并在 `metadata.label_mapping` 中返回有效映射。

## 推理与后处理流程

1. 校验 `file_uri` 是否存在。
2. 用 `ffmpeg` 抽音频到任务工作目录：

```text
mono / 32000 Hz / float32 wav
```

3. 对短 scene 直接整段推理；对长 scene 走滑窗。
4. 获取 framewise scores。
5. 根据标签映射聚合业务标签分数，聚合方式默认 `max`。
6. 对每个业务标签做平滑、阈值、连通区间提取。
7. 应用 `min_event_ms`、`merge_gap_ms`、`nms_window_ms`。
8. 若 `peak_refine=true`，在候选区间附近用 onset envelope / RMS peak 精修 `peak_ms`。
9. 若传入 `timeline_offset_ms`，补充绝对时间字段。
10. 写入 SQLite result JSON，删除任务工作目录。

卡点消费建议优先使用 `peak_ms`，不要使用 `start_ms`。`start_ms/end_ms` 用于解释事件范围，`peak_ms` 用于剪辑对齐。

## 实现文件规划

建议新增：

```text
app/audio_sed_api/
  __init__.py
  main.py
  models.py
  scheduler.py

app/audio_sed_worker/
  __init__.py
  inference.py
  worker_entry.py

requirements/audio_sed_api.txt
requirements/audio_sed_worker.txt
Dockerfile.audio_sed_api
Dockerfile.audio_sed_worker
readme.audio-sed.md
scripts/smoke_test_audio_sed.sh
```

建议修改：

```text
docker-compose.yml
scripts/build.sh
scripts/up.sh
scripts/logs.sh
readme.md
qa/README.md
```

实现方式复用现有模式：

- API 逻辑参考 `app/audio_api/main.py`。
- Docker SDK worker 调度参考 `app/audio_api/scheduler.py`。
- worker 轮询和 idle timeout 参考 `app/audio_worker/worker_entry.py`。
- SQLite task store 继续复用 `app/core/task_store.py`。
- Settings 继续复用 `app/core/settings.py`，新增 PANNs 相关 env 字段。

## docker-compose 设计

新增公共 env：

```yaml
x-audio-sed-common-env: &audio_sed_common_env
  DATA_ROOT: /data/multimedia-ana
  HOME: /data/multimedia-ana/audio-sed/cache/home
  USER: kun
  LOGNAME: kun
  SERVICE_NAME: audio-sed
  HOST_PROJECT_DIR: /home/kun/tools/multimedia-ana
  HOST_UID: 1001
  HOST_GID: 1003
  AUDIO_SED_DEVICE: cuda:0
  AUDIO_SED_MODEL_ID: Cnn14_DecisionLevelMax
  AUDIO_SED_CHECKPOINT_PATH: /data/multimedia-ana/audio-sed/models/Cnn14_DecisionLevelMax_mAP=0.385.pth
  AUDIO_SED_SAMPLE_RATE: 32000
```

API service：

- `container_name`: `multimedia-ana-audio-sed-api`
- `ports`: `0.0.0.0:18089:7860`
- mount `/var/run/docker.sock`
- `group_add: ["1002"]`

Worker service：

- `image`: `multimedia-ana-audio-sed-worker:local`
- `gpus: all`
- `shm_size: 8g`
- `command`: `python3 -m app.audio_sed_worker.worker_entry`
- volumes 与现有 worker 一致：
  - `.:/workspace:ro`
  - `/data/multimedia-ana:/data/multimedia-ana`
  - `/data/assets:/data/assets:ro`

动态 worker kwargs 必须与 compose worker 配置同步，保持现有注释风格。

## 验证计划

第一阶段 smoke test：

- 构建：`bash scripts/build.sh audio-sed`
- 启动：`docker compose up -d audio-sed-api`
- 提交：`bash scripts/smoke_test_audio_sed.sh /data/multimedia-ana/example-video/scene_001.mp4`
- 验证：返回 `events` 数组，且所有事件有 `label/start_ms/peak_ms/end_ms/score`。

第二阶段业务样本验证：

- 选 10 个含枪声/击打/玻璃破碎的 scene。
- 人工记录预期 peak 时间。
- 对比 `peak_ms` 误差分布。
- 初版可接受目标：明显瞬态事件 P50 误差小于 120ms，P90 小于 250ms。

第三阶段回归：

- 在 `qa/` 下新增 Docker 化测试脚本。
- 只校验协议、字段、时间范围、非空结果，不把模型分数作为强断言。

## 风险

- PANNs 的 AudioSet 标签粒度不完全等于电影动作语义，`impact` 类可能需要大量阈值和映射调参。
- 电影 BGM、foley、混响会造成误检，必须依赖后处理和人工样本校准。
- `panns-inference` 维护频率一般，若与 PyTorch 2.8 / Python 3.11 不兼容，应 vendor 最小推理代码。
- 默认 checkpoint 缺失会导致 worker 失败；需要提前准备模型文件到 `/data`。
- PANNs 适合 MVP 和 baseline，不代表最终精度上限。

## 决策建议

先按 `audio-sed-api + audio-sed-worker` 独立服务实现，不复用现有 `audio` 服务。原因：

- 当前 `audio` 面向 ASR / AED，预处理固定 `16kHz`，而 PANNs 需要 `32kHz`。
- 两类任务返回结构不同，混在一起会让接口语义变脏。
- PANNs 是 GPU 推理，符合 `agent.md` 中可唤起/释放的双容器模式。

第一版目标是稳定产出可消费的 `peak_ms`，不是追求最高 SED 指标。若业务链路验证通过，再考虑 HTS-AT、自训练小模型或 FLAM 辅助标签扩展。
