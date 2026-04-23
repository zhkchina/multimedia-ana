# Audio Service Guide

`audio` 提供单文件音频解析服务。

## 设计约束

- 一次只处理一个文件
- 调用方可传 `messages`
- 调用方传服务参数到 `input.params`
- 服务端容器内串行执行
- 服务端只短期保留任务状态和结果
- 不保留业务结果文件

服务信息：
- 宿主机端口：`18088`
- API 容器：`multimedia-ana-audio-api`
- Worker：按需拉起 `multimedia-ana-audio-worker`
- 模型：`SenseVoiceSmall + fsmn-vad`

## 请求接口

- `GET /healthz`
- `GET /readyz`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`

## 输入要求

- `input.file_uri` 可传音频，也可直接传视频
- worker 内部会用 `ffmpeg` 预处理为 `wav + mono + 16kHz + pcm_s16le`
- 路径必须是容器可见的真实文件
- 也支持直接使用 `/data/assets/` 下的只读资产路径

## 最小请求

```bash
curl -X POST http://127.0.0.1:18088/v1/tasks \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @- <<'JSON'
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "params": {
      "profile": "movie_zh",
      "language": "auto"
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
JSON
```

## 输入字段

- `input.file_uri`: 必填，单个音频或视频文件路径
- `input.messages`: 可选，保留给上层任务语义
- `input.params.profile`: 当前建议 `movie_zh`
- `input.params.language`: 默认 `auto`
- `options.wait_seconds`: 可选

## 返回结果

核心字段：
- `backend`
- `model_id`
- `vad_model_id`
- `file_uri`
- `text`
- `aed`
- `segments`
- `metadata`
- `raw_result`

说明：
- `segments` 是段级时间轴
- `aed` 是下一步工作流的重要参考标记
- `text` 是完整转写文本

## 轮询示例

```bash
TASK_ID="$(curl -sS -X POST http://127.0.0.1:18088/v1/tasks \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @- <<'JSON' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "params": {
      "profile": "movie_zh",
      "language": "auto"
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
JSON
)"

while true; do
  STATUS="$(curl -sS "http://127.0.0.1:18088/v1/tasks/${TASK_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "task=${TASK_ID} status=${STATUS}"
  if [ "${STATUS}" = "succeeded" ] || [ "${STATUS}" = "failed" ] || [ "${STATUS}" = "canceled" ]; then
    break
  fi
  sleep 1
done

curl -sS "http://127.0.0.1:18088/v1/tasks/${TASK_ID}/result"
```

## 当前验证结果

参考：
- [proxy_v1 模型模块热态测试](./docs/proxy-v1-model-benchmark-20260422.md)

在 `proxy_v1.local.mp4` 上，热态两次均值约：
- `24.098s`

## 常用命令

```bash
bash scripts/build.sh audio
docker compose up -d audio-api
bash scripts/logs.sh audio-api
bash scripts/logs.sh audio-worker
bash scripts/smoke_test_audio.sh /data/multimedia-ana/example-video/proxy_v1.local.mp4
```
