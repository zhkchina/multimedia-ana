# 协议回归测试

日期：
- `2026-04-22`

目标：
- 验证 `qwen3-vl` 和 `audio` 已切到统一请求协议
- 确认两者都接受 `input.file_uri + input.messages + input.params`

统一请求骨架：

```json
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "messages": [],
    "params": {}
  },
  "options": {
    "wait_seconds": 0
  }
}
```

测试输入：
- `/data/multimedia-ana/example-video/proxy_v1.local.mp4`

测试方式：
- 通过 Docker 网络内 QA 客户端调用 `/v1/tasks`
- `wait_seconds=0`
- `runs=1`

结果：

## qwen3-vl

- `task_id`: `task_20260422_111802_72a57709`
- `status`: `succeeded`
- `elapsed_seconds`: `37.581`
- 返回字段已切到：
  - `file_uri`
  - `messages`
  - `generation`
  - `output_text`
  - `output_json`

说明：
- 这次是冷启动任务，worker 先从空闲态拉起
- 已补充 Markdown code fence 解析，`output_json` 本次为对象

## audio

- `task_id`: `task_20260422_095826_c4196344`
- `status`: `succeeded`
- `elapsed_seconds`: `34.516`
- 返回字段已切到：
  - `file_uri`
  - `text`
  - `aed`
  - `segments`
  - `metadata`

结论：
- `qwen3-vl` 已接受统一协议并成功返回 JSON 结果
- `audio` 已接受统一协议并成功返回 JSON 结果
- 三个模块目前都遵循同一请求思想：
  - 一次一个文件
  - 容器内串行执行
  - `messages` 由调用方传入
  - 参数统一进入 `input.params`
