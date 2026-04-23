本目录提供 Docker 化的多媒体解析服务。

统一原则：
- 输入音频或视频
- 输出 JSON
- 一次一个文件
- 调用方决定批量调用策略
- 服务之间独立运行、独立调用
- 同一服务容器内串行执行
- 宿主机不安装 Python 运行依赖

当前服务：
- `qwen3-vl`：视频语义理解，宿主机端口 `18086`
- `scene`：场景切分，宿主机端口 `18087`
- `audio`：ASR / AED / 段级时间轴，宿主机端口 `18088`

统一 API：
- `GET /healthz`
- `GET /readyz`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`

统一请求骨架：

```json
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "messages": [
      {
        "role": "user",
        "content": "请输出结构化结果。"
      }
    ],
    "params": {}
  },
  "options": {
    "wait_seconds": 0
  }
}
```

说明：
- `input.file_uri`：单文件路径
- `input.messages`：由调用方提供，允许特殊符号和长提示词，推荐用标准 JSON 编码发送
- `input.params`：服务私有参数
- `options.wait_seconds`：等待秒数；长任务由调用方轮询

当前实现形态：
- `qwen3-vl`：轻量常驻 API + 按需 GPU worker
- `audio`：轻量常驻 API + 按需 GPU worker
- `scene`：单容器 API，容器内串行执行
- 三个服务都用 SQLite 保存短期任务状态和结果

启动：
```bash
bash scripts/build.sh
bash scripts/up.sh
docker compose up -d audio-api video-scene
```

常用运维：
```bash
bash scripts/down.sh
bash scripts/logs.sh api
bash scripts/logs.sh audio-api
bash scripts/logs.sh worker
```

服务文档：
- [Qwen3-VL Guide](./readme.qwen.md)
- [Scene Guide](./readme.scene.md)
- [Audio Guide](./readme.audio.md)

架构与设计：
- [轻量多媒体 API 统一重构方案](./docs/lightweight-api-refactor-plan.md)
- [视频理解总体架构](./docs/video-understanding-architecture.md)
- [Qwen3-VL Transformers 后端说明](./docs/qwen3-vl-transformers-backend.md)
- [FunASR 音频服务接入方案](./docs/funasr-audio-service-plan.md)
- [工程完备性差距分析](./docs/engineering-gap-analysis.md)

测试与报告：
- [QA Guide](./qa/README.md)
- [重构前后对比](./docs/refactor-comparison-20260422.md)
- [统一协议回归测试](./docs/protocol-regression-20260422.md)
- [proxy_v1 模型模块热态测试](./docs/proxy-v1-model-benchmark-20260422.md)

重要约束：
- 输入文件必须是 Docker 容器可见的真实文件路径，推荐放在 `/data/multimedia-ana/` 下。
- 指向宿主机其他目录的软链接可能在容器内不可见。像 `proxy_v1.mp4 -> /home/kun/assets/...` 这种情况，需要先物化到 `/data/multimedia-ana` 下再提交。
- 服务器端默认不保留业务结果文件；任务状态和结果只短期保存在 SQLite 中。
- 当前服务额外只读挂载了 `/data/assets:/data/assets:ro`，可直接把 `input.file_uri` 指向 `/data/assets/` 下的媒体资产。
