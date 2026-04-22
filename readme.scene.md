# Video-Scene Service Guide

本文件只描述 `video-scene` 服务，供后续 agent 或开发者快速接手。

目标：

- 明确 `video-scene` 当前提供什么能力
- 明确两种访问方式：`API` 和 `Docker + CLI`
- 给出可以直接执行的最小示例
- 说明输入输出约束，避免把任务提交到错误路径

## 1. 服务定位

`video-scene` 用于对视频做场景切分，并导出：

- 场景列表
- 场景统计 CSV
- 每个场景的关键帧图片
- 统一的 `analysis.json`

当前实现形态：

- 单容器服务
- 容器内串行处理任务
- 基于 `PySceneDetect + ffmpeg + OpenCV`

当前镜像：

- `multimedia-ana-video-scene:local`

当前容器：

- `multimedia-ana-video-scene`

## 2. 重要约束

### 输入视频路径

无论走 API 还是 CLI，输入视频都应该放在宿主机和容器都能访问的共享目录里。

当前项目默认共享：

- `/data/multimedia-ana`

推荐输入目录：

- `/data/multimedia-ana/example-video`

### 输出目录

服务默认输出到：

- `/data/multimedia-ana/video-scene/output/<job_id>/`

QA 结果默认输出到：

- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/`

### 当前默认参数

- `profile = standard`
- `threshold = 27.0`
- `min_scene_len = 0.6s`
- `save_image_count = 3`

注意：

- 当前默认参数在部分视频上会切得过碎
- `BV1EfQEBjE27.mp4` 和 `BV1ecoABBEMm.mp4` 已验证存在碎片化问题

## 3. 何时用哪种方式

### 用 API

适合：

- 需要统一服务入口
- 需要异步提交任务
- 需要轮询任务状态
- 需要被其他 agent、脚本、调度器复用

### 用 Docker + CLI

适合：

- 临时手工验证
- 快速单文件调试
- 不想走 job 管理，只想直接跑一次场景检测

## 4. 启动服务

构建镜像：

```bash
cd /home/kun/tools/multimedia-ana
bash scripts/build.sh scene
```

启动服务：

```bash
cd /home/kun/tools/multimedia-ana
docker compose up -d video-scene
```

健康检查：

```bash
curl http://127.0.0.1:18087/health
```

预期：

- 返回 `ok: true`
- 返回 `worker_online: true`

## 5. 方式一：通过 API 使用

### API 地址

宿主机访问：

- `http://127.0.0.1:18087`

同一 Docker 网络内访问：

- `http://video-scene:7860`

### 可用接口

- `GET /health`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

### 5.1 提交任务

```bash
curl -X POST http://127.0.0.1:18087/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "video_uri": "/data/multimedia-ana/example-video/BV1CidqBUE2R.mp4",
    "profile": "standard",
    "threshold": 27.0,
    "min_scene_len": "0.6s",
    "save_image_count": 3
  }'
```

成功时返回示例：

```json
{
  "job_id": "job_20260421_024129_03a51725",
  "status": "queued"
}
```

### 5.2 查询任务状态

```bash
curl http://127.0.0.1:18087/jobs/job_20260421_024129_03a51725
```

状态通常会经历：

- `queued`
- `running`
- `succeeded` 或 `failed`

### 5.3 获取结果

返回任务状态包装：

```bash
curl http://127.0.0.1:18087/jobs/job_20260421_024129_03a51725/result
```

直接下载 `analysis.json`：

```bash
curl -L http://127.0.0.1:18087/jobs/job_20260421_024129_03a51725/result?download=true \
  -o /tmp/video-scene-analysis.json
```

### 5.4 一段最小轮询示例

```bash
JOB_ID="$(curl -sS -X POST http://127.0.0.1:18087/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "video_uri": "/data/multimedia-ana/example-video/BV1CidqBUE2R.mp4",
    "profile": "standard",
    "threshold": 27.0,
    "min_scene_len": "0.6s",
    "save_image_count": 3
  }' | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"

while true; do
  STATUS="$(curl -sS "http://127.0.0.1:18087/jobs/${JOB_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "job=${JOB_ID} status=${STATUS}"
  if [ "${STATUS}" = "succeeded" ] || [ "${STATUS}" = "failed" ]; then
    break
  fi
  sleep 2
done

curl -L "http://127.0.0.1:18087/jobs/${JOB_ID}/result?download=true" \
  -o "/tmp/${JOB_ID}.json"
```

## 6. 方式二：通过 Docker + CLI 使用

这里不经过 API，而是直接在镜像里运行 `scenedetect`。

适合快速验证单个视频。

### 6.1 直接用 `docker run`

```bash
docker run --rm \
  --user 1001:1003 \
  -v /data/multimedia-ana:/data/multimedia-ana \
  multimedia-ana-video-scene:local \
  python3 -m scenedetect \
    -i /data/multimedia-ana/example-video/BV1CidqBUE2R.mp4 \
    -o /data/multimedia-ana/video-scene/manual/BV1CidqBUE2R \
    -s /data/multimedia-ana/video-scene/manual/BV1CidqBUE2R/stats.csv \
    -m 0.6s \
    detect-content --threshold 27.0 \
    list-scenes --skip-cuts \
    save-images --num-images 3
```

执行后可在这里查看结果：

- `/data/multimedia-ana/video-scene/manual/BV1CidqBUE2R/`

典型产物：

- `stats.csv`
- `BV1CidqBUE2R-Scenes.csv`
- `Scene-*.jpg`

### 6.2 用 `docker compose run`

如果你想复用 compose 定义，也可以这样跑：

```bash
docker compose run --rm \
  --entrypoint python3 \
  video-scene \
  -m scenedetect \
  -i /data/multimedia-ana/example-video/BV1CidqBUE2R.mp4 \
  -o /data/multimedia-ana/video-scene/manual/BV1CidqBUE2R \
  -s /data/multimedia-ana/video-scene/manual/BV1CidqBUE2R/stats.csv \
  -m 0.6s \
  detect-content --threshold 27.0 \
  list-scenes --skip-cuts \
  save-images --num-images 3
```

## 7. 输出结果说明

API 模式下载到的 `analysis.json` 主要包含：

- `job_id`
- `service`
- `video_uri`
- `threshold`
- `min_scene_len`
- `scene_count`
- `image_count`
- `stats_csv`
- `scenes_csv`
- `image_files`
- `scenes`

其中 `scenes` 的每个条目包含：

- `scene_number`
- `start_frame`
- `start_timecode`
- `start_seconds`
- `end_frame`
- `end_timecode`
- `end_seconds`
- `length_frames`
- `length_timecode`
- `length_seconds`

## 8. 常见问题

### 没有生成新测试产物

先检查：

- QA 是否真的跑的是当前仓库下的 `qa/run_suite.sh`
- `API_BASE_URL` 是否指向 `http://video-scene:7860`
- `/data/multimedia-ana/testlab/video-scene/runs/` 下是否生成了新的 `run_id`

### API 健康检查失败

检查：

```bash
docker compose ps video-scene
docker logs --tail 200 multimedia-ana-video-scene
```

### 场景切分过碎

优先尝试提高阈值或增大最小场景长度，例如：

- `threshold = 30.0`
- `threshold = 32.0`
- `min_scene_len = 1.0s`
- `min_scene_len = 1.5s`

## 9. 建议给后续 agent 的工作方式

如果是系统集成、脚本联调、批量处理：

- 优先用 API

如果是单文件排障、算法调参、快速肉眼检查：

- 优先用 Docker + CLI

如果要做回归测试：

- 使用 `qa/` 目录下的 Docker 化测试入口
- 不要把测试逻辑重新写回宿主机
