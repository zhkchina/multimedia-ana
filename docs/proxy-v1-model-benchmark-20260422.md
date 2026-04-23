# proxy_v1 模型模块热态测试

日期：
- `2026-04-22`

测试对象：
- `qwen3-vl`
- `audio`

输入文件：
- 原始路径：`/data/multimedia-ana/example-video/proxy_v1.mp4`
- 实际测试路径：`/data/multimedia-ana/example-video/proxy_v1.local.mp4`

说明：
- `proxy_v1.mp4` 原本是一个指向 `/home/kun/assets/...` 的软链接
- Docker 容器无法访问该宿主机路径
- 为了保证服务可读，先将其物化为 `/data` 下的真实文件 `proxy_v1.local.mp4`

测试方法：
- API：`/v1/tasks`
- 请求骨架：`input.file_uri + input.messages + input.params`
- `wait_seconds=0`
- `poll_interval=1s`
- `warmup_runs=1`
- 正式计入结果：`2` 次
- 测试期间确认 worker 已在线且模型已加载

命令：

```bash
docker run --rm \
  --network multimedia-ana_default \
  --user 1001:1003 \
  -v /data/multimedia-ana:/data/multimedia-ana \
  -v /home/kun/tools/multimedia-ana:/workspace \
  -w /workspace \
  multimedia-ana-video-scene-qa:local \
  python3 qa/run_multimedia_suite.py \
    --output-dir /data/multimedia-ana/testlab/multimedia/runs/proxy_v1_hot_20260422 \
    --api-mode tasks_v1 \
    --services video-vl audio \
    --warmup-runs 1 \
    --runs 2 \
    --wait-seconds 0 \
    --poll-interval-seconds 1 \
    --timeout-seconds 3600 \
    --video-input /data/multimedia-ana/example-video/proxy_v1.local.mp4 \
    --audio-input /data/multimedia-ana/example-video/proxy_v1.local.mp4
```

结果文件：
- `/data/multimedia-ana/testlab/multimedia/runs/proxy_v1_hot_20260422/summary.json`

## 结果汇总

### qwen3-vl

- worker 在线：是
- 模型重载：否
- 热态两次均值：`12.564s`
- 第 1 次：`12.062s`
- 第 2 次：`13.066s`

任务：
- `task_20260422_082926_ef9abaee`
- `task_20260422_082938_2840f253`

补充：
- 这两次测量期间 `multimedia-ana-video-vl-worker` 没有再次出现 `Loading Qwen3-VL transformers runtime`
- 说明模型确实处于热启动复用状态

### audio

- worker 在线：是
- 模型重载：否
- 热态两次均值：`24.098s`
- 第 1 次：`24.096s`
- 第 2 次：`24.100s`

任务：
- `task_20260422_083014_a2e4d976`
- `task_20260422_083038_3612759a`

补充：
- 输入是视频文件，worker 内部通过 `ffmpeg` 提取并标准化音频
- 输出为 `text + aed + segments + metadata` JSON

## 结论

- `proxy_v1` 在当前统一轻量任务 API 下可稳定处理
- `qwen3-vl` 热态延迟约 `12-13s`
- `audio` 热态延迟约 `24s`
- 对 Docker 服务而言，提交给 API 的输入路径必须是容器可见的真实文件，不能依赖容器外软链接
