# Qwen3-VL Service Guide

`qwen3-vl` 提供单文件视频理解服务。

## 设计约束

- 一次只处理一个文件
- 调用方传 `messages`
- 调用方传服务参数到 `input.params`
- 服务端容器内串行执行
- 服务端只短期保留任务状态和结果
- 不保留业务结果文件

服务信息：
- 宿主机端口：`18086`
- API 容器：`docker-api`
- Worker：按需拉起 `multimedia-ana-video-vl-worker`
- 模型：`Qwen/Qwen3-VL-8B-Instruct`

## 请求接口

- `GET /healthz`
- `GET /readyz`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`

## 输入要求

- `input.file_uri` 必须是容器可见的真实文件路径
- 推荐放在 `/data/multimedia-ana/` 下
- 也支持直接使用 `/data/assets/` 下的只读资产路径
- 不要依赖指向容器外目录的软链接

## 最小请求

```bash
curl -X POST http://127.0.0.1:18086/v1/tasks \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @- <<'JSON'
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "messages": [
      {
        "role": "user",
        "content": "请对这个视频片段进行电影镜头级语义标注，并严格输出 JSON 对象。字段包含 scene_summary、shot_type、characters、actions、emotion、location、objects、cinematic_tags、clip_value、reason。"
      }
    ],
    "params": {
      "profile": "standard",
      "sample_fps": 1.0,
      "max_frames": 64
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
- `input.messages`: 必填，提示词数组
- `input.params.profile`: 可选，默认 `standard`
- `input.params.sample_fps`: 可选，默认 `1.0`
- `input.params.max_frames`: 可选，默认 `128`
- `input.params.language`: 可选
- `input.params.response_format`: 可选
- `input.params.generation`: 可选，如 `max_output_tokens`、`temperature`、`top_p`
- `options.wait_seconds`: 可选，超时后返回任务状态，由调用方轮询

## 返回结果

核心字段：
- `backend`
- `model_id`
- `file_uri`
- `messages`
- `generation`
- `output_text`
- `output_json`

调用方应优先消费 `output_json`。

## 轮询示例

```bash
TASK_ID="$(curl -sS -X POST http://127.0.0.1:18086/v1/tasks \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @- <<'JSON' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "messages": [
      {
        "role": "user",
        "content": "请输出结构化视频语义理解结果。"
      }
    ],
    "params": {
      "profile": "standard",
      "sample_fps": 1.0,
      "max_frames": 64
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
JSON
)"

while true; do
  STATUS="$(curl -sS "http://127.0.0.1:18086/v1/tasks/${TASK_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "task=${TASK_ID} status=${STATUS}"
  if [ "${STATUS}" = "succeeded" ] || [ "${STATUS}" = "failed" ] || [ "${STATUS}" = "canceled" ]; then
    break
  fi
  sleep 1
done

curl -sS "http://127.0.0.1:18086/v1/tasks/${TASK_ID}/result"
```

## 当前验证结果

参考：
- [proxy_v1 模型模块热态测试](./docs/proxy-v1-model-benchmark-20260422.md)

在 `proxy_v1.local.mp4` 上，热态两次均值约：
- `12.564s`

## 常用命令

```bash
bash scripts/up.sh
bash scripts/logs.sh api
bash scripts/logs.sh worker
bash scripts/smoke_test_video_vl.sh /data/multimedia-ana/example-video/proxy_v1.local.mp4
```
