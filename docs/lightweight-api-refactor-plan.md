# Lightweight API Refactor Plan

本文档记录当前仓库三类多媒体解析服务的统一重构方案，当前仅为评审稿，不执行代码修改。

## 背景

经过当前讨论，三个服务的本质已经统一：

- 输入：音频或视频
- 输出：JSON 格式的文本化解析结果

因此，这个目录提供的能力不应再按“文件产物服务”设计，而应统一按“轻量多媒体解析 API”设计。

适用模块：

- `qwen3-vl`
- `scene`
- `audio`

## 重构目标

统一满足以下要求：

- 全部使用 Docker 部署
- 不污染宿主环境
- 不同服务容器之间独立运行、独立调用
- 同一个服务容器内串行执行
- 服务端只做短期任务状态和结果保存
- 对外主结果统一为 JSON
- 不再把本地文件作为主结果接口

## 统一设计结论

三个模块统一改成：

- 轻量常驻 API
- 服务内串行执行
- 使用 SQLite 保存短期任务状态与结果
- 对外提供统一的轻量异步 API

说明：

- 任务可能达到十分钟级，不适合依赖单个 HTTP 连接一直保持。
- 但当前只有单用户、单服务串行执行，不需要 Redis、Celery、Kafka 等更重方案。
- SQLite 足够满足当前需求，并且逻辑最简单。

## 为什么不继续使用当前文件型任务系统

当前旧模式的问题：

- `prompt` 写死，不利于模型服务灵活调用
- 结果文件落盘，不符合“服务端不长期保存结果”的目标
- `scene` 的 CSV、`audio` 的文本、`qwen3-vl` 的分析 JSON 都被当成主产物，不利于统一接口
- 长任务虽然能跑，但接口形态更像离线任务系统，而不是轻量解析服务

新的统一方向是：

- 文件只作为内部中间产物
- API 主接口只处理 JSON 请求和 JSON 响应
- 调用方负责消费和保存最终结果

## 统一接口方案

每个服务统一提供：

- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`
- `GET /healthz`
- `GET /readyz`

可选：

- `POST /v1/tasks/{task_id}/cancel`

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

字段约定：

- `input.file_uri`：单文件路径
- `input.messages`：调用方提示词数组
- `input.params`：服务私有参数
- `options.wait_seconds`：等待秒数；超时后调用方自行轮询

## 统一任务行为

创建任务时支持：

- `wait_seconds`

行为定义：

- 如果任务在 `wait_seconds` 内完成，直接返回最终结果
- 如果未完成，返回 `202 Accepted` 和 `task_id`
- 调用方之后通过 `GET /v1/tasks/{task_id}` 和 `GET /v1/tasks/{task_id}/result` 轮询

这样可以同时兼容：

- 短任务的近同步体验
- 长任务的稳态异步执行

## 为什么不用纯同步接口

因为三个模块都可能出现分钟级任务：

- 网络连接可能断开
- 客户端可能超时
- 反向代理可能超时

因此必须把：

- 任务执行状态
- HTTP 连接

在逻辑上解耦。

最轻量的方式不是长连接等待，而是：

- 创建任务
- 返回 `task_id`
- 轮询状态和结果

## SQLite 方案

每个服务维护自己的 SQLite 数据库。

建议每个服务独立文件：

- `/data/multimedia-ana/video-vl/runtime/tasks.db`
- `/data/multimedia-ana/video-scene/runtime/tasks.db`
- `/data/multimedia-ana/audio/runtime/tasks.db`

建议表结构包含：

- `task_id`
- `service`
- `status`
- `request_json`
- `result_json`
- `error_json`
- `created_at`
- `started_at`
- `finished_at`
- `expires_at`

状态建议统一为：

- `queued`
- `running`
- `succeeded`
- `failed`
- `canceled`

## 结果保存策略

原则：

- 结果短期保存在 SQLite
- 不做长期归档
- 不再以文件作为主结果来源

结果 TTL 可配置，例如：

- 默认保留 `24h`

到期后允许自动清理。

## 三个模块的统一结果形态

### A. `qwen3-vl`

输入：

- 视频路径
- 调用方传入的 `messages`
- 调用方传入的 JSON schema 或文本输出约束

输出：

- 视频语义理解 JSON

说明：

- 不再把 `prompt` 写死
- `prompt` 由调用方传入
- 服务端只做推理、状态管理和短期结果保存

### B. `scene`

输入：

- 视频路径
- 切分参数

输出：

- 场景切分 JSON

说明：

- CSV 不再作为主结果
- `scenedetect` 生成 CSV 仍可作为内部中间过程
- API 主返回统一为解析后的 `scenes` JSON

典型返回：

```json
{
  "scene_count": 120,
  "scenes": []
}
```

如果后续调用方确实需要 CSV：

- 可作为导出格式单独支持
- 但不再作为默认主结果

### C. `audio`

输入：

- 音频或视频路径

输出：

- `text`
- `segments`
- `aed`
- `metadata`

说明：

- 音频服务本质也是“输入媒体，输出 JSON 文本”
- `ffmpeg` 预处理仍作为 `audio-worker` 内部步骤
- `AED` 必须在第一版结果中显式保留

## 请求与响应统一原则

### 创建任务请求

每个服务都允许不同的业务参数，但统一放在 `input.params`：

```json
{
  "input": {
    "file_uri": "/data/multimedia-ana/example-video/proxy_v1.local.mp4",
    "messages": [],
    "params": {}
  },
  "options": {
    "wait_seconds": 30
  },
  "metadata": {
    "request_id": "client-001"
  }
}
```

### 创建任务响应

未完成：

```json
{
  "id": "task_xxx",
  "status": "queued"
}
```

若在等待时间内完成，也可以直接返回：

```json
{
  "id": "task_xxx",
  "status": "succeeded",
  "result": {}
}
```

### 状态查询响应

```json
{
  "id": "task_xxx",
  "service": "audio",
  "status": "running",
  "created_at": "...",
  "started_at": "...",
  "finished_at": null,
  "error": null
}
```

### 结果查询响应

```json
{
  "id": "task_xxx",
  "service": "scene",
  "status": "succeeded",
  "result": {}
}
```

## 执行模型

接口统一，但内部执行方式允许不同。

### `qwen3-vl`

建议：

- 轻量 API 常驻
- GPU worker 按需拉起
- worker 空闲超时退出
- 同服务内串行执行

### `audio`

建议：

- 轻量 API 常驻
- GPU worker 按需拉起
- worker 空闲超时退出
- 同服务内串行执行

### `scene`

建议：

- 暂时可保持单容器 API
- 在容器内串行执行任务
- 不强制立即拆成独立 worker

说明：

- 三个服务的接口和状态模型统一
- 内部执行模型不要求完全相同
- 这比强行把所有服务实现成同一种容器结构更简单

## 日志策略

服务端只记录最小状态日志。

建议记录：

- `task_id`
- `request_id`
- 输入媒体路径
- 状态变更
- 延迟
- 错误信息

默认不记录：

- 大段 prompt 正文
- 最终结果全文
- 大量中间产物

## 文件的角色

统一原则：

- 文件允许作为内部中间过程存在
- 文件不再作为主结果接口

例如：

- `scene` 的 CSV
- `audio` 的预处理 WAV
- `qwen3-vl` 的临时视频抽帧数据

这些都可以保留，但只服务于内部运行，不再作为调用方主消费对象。

## 对当前工程的直接影响

### 需要去掉的旧设计

- `POST /jobs`
- `GET /jobs/{id}`
- `GET /jobs/{id}/result` 依赖本地文件
- `jobs/*.json`
- `output/*.json` 作为主流程依赖

### 需要统一的新设计

- `/v1/tasks`
- SQLite 状态表
- JSON 结果直接存数据库
- 结果短期缓存
- 统一状态机

## 当前审核结论

当前最适合本仓库的统一重构方案是：

- 三个服务统一改成“输入媒体，输出 JSON”的轻量异步 API
- 使用 SQLite 作为最轻量的任务状态和短期结果存储
- `qwen3-vl`、`audio` 继续使用轻量 API + 按需 worker
- `scene` 暂时保留单容器串行执行，但接口和状态模型统一
- `scene` 的 CSV 不再作为主结果，统一对外返回 JSON
- 服务端不做长期结果归档
- 调用方负责消费和保存最终结果

## 当前文档状态

本文件仅定义重构方向与统一原则：

- 不修改现有代码
- 不执行迁移
- 仅用于后续审核与实施基线
