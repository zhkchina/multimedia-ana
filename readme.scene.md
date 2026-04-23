# Scene Service Guide

`scene` 提供单文件场景切分服务。

## 设计约束

- 一次只处理一个文件
- 参数统一放在 `input.params`
- 容器内串行执行
- 服务端只短期保留任务状态和结果
- 默认只返回 JSON，不保留 `csv/图片` 等业务产物

服务信息：
- 宿主机端口：`18087`
- API 容器：`multimedia-ana-video-scene`
- 算法：`PySceneDetect + ffmpeg + OpenCV`

## 请求接口

- `GET /healthz`
- `GET /readyz`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`

## 输入要求

- `input.file_uri` 必须是容器可见的真实文件路径
- 推荐放在 `/data/multimedia-ana/example-video/`
- 也支持直接使用 `/data/assets/` 下的只读资产路径

## 最小请求

```bash
curl -X POST http://127.0.0.1:18087/v1/tasks \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @- <<'JSON'
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "params": {
      "profile": "standard",
      "detector": "content",
      "threshold": 27.0,
      "min_scene_len": "0.6s",
      "downscale": 0,
      "frame_skip": 0,
      "save_image_count": 0,
      "include_artifacts": false
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
JSON
```

## 输入字段

- `input.file_uri`: 必填，单个视频文件路径
- `input.messages`: 预留字段，当前 `scene` 不使用
- `input.params.profile`: 可选，默认 `standard`
- `input.params.detector`: 可选，默认 `content`，当前仅支持该值
- `input.params.threshold`: 可选，默认 `27.0`
- `input.params.min_scene_len`: 可选，默认 `0.6s`
- `input.params.downscale`: 可选，默认 `0`
- `input.params.frame_skip`: 可选，默认 `0`
- `input.params.save_image_count`: 默认 `0`
- `input.params.include_artifacts`: 默认 `false`
- `options.wait_seconds`: 可选

说明：
- `threshold` 越高，切分越保守
- `min_scene_len` 越大，越不容易出现碎片化短镜头
- `downscale` 和 `frame_skip` 用于提速，但可能影响精度
- `include_artifacts=true` 时，会返回 `stats_csv`、`scenes_csv`、`image_files`

## 返回结果

核心字段：
- `service`
- `file_uri`
- `params`
- `summary`
- `scenes`

调用方应优先消费：
- `summary.scene_count`
- `scenes`

默认不返回：
- `artifacts`

## 轮询示例

```bash
TASK_ID="$(curl -sS -X POST http://127.0.0.1:18087/v1/tasks \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @- <<'JSON' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "params": {
      "profile": "standard",
      "detector": "content",
      "threshold": 27.0,
      "min_scene_len": "0.6s",
      "downscale": 0,
      "frame_skip": 0,
      "save_image_count": 0,
      "include_artifacts": false
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
JSON
)"

while true; do
  STATUS="$(curl -sS "http://127.0.0.1:18087/v1/tasks/${TASK_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "task=${TASK_ID} status=${STATUS}"
  if [ "${STATUS}" = "succeeded" ] || [ "${STATUS}" = "failed" ] || [ "${STATUS}" = "canceled" ]; then
    break
  fi
  sleep 1
done

curl -sS "http://127.0.0.1:18087/v1/tasks/${TASK_ID}/result"
```

## 当前验证结果

参考：
- [scene proxy_v1 测试报告](./docs/scene-proxy-v1-test-20260422.md)

## 常用命令

```bash
bash scripts/build.sh scene
docker compose up -d video-scene
curl http://127.0.0.1:18087/healthz
```
