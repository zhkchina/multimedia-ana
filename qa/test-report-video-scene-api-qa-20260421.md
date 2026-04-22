# Video-Scene API QA 测试报告（2026-04-21）

## 结论

本轮 `video-scene-api` QA 已完成并通过。

验证依据：

- 新 run 目录已生成：`/data/multimedia-ana/testlab/video-scene/runs/20260421_104129`
- QA 汇总文件存在：`manifest.json`、`summary.json`
- 每个视频目录均生成：`analysis.json`、`scene_report.json`
- 服务侧目录存在对应 job 产物：`/data/multimedia-ana/video-scene/output/job_*`

这说明：

- QA 已经实际通过 API 提交任务，而不是旧版直接跑 `scenedetect`
- `video-scene` 单容器 API 的提交、轮询、结果下载链路是通的
- 当前镜像在这批样例视频上可以稳定完成处理

## 测试范围

测试输入目录：

- `/data/multimedia-ana/example-video`

测试运行目录：

- `/data/multimedia-ana/testlab/video-scene/runs/20260421_104129`

API 访问地址：

- `http://video-scene:7860`

本轮参数：

- `profile = standard`
- `threshold = 27.0`
- `min_scene_len = 0.6s`
- `save_image_count = 3`

## 汇总结果

来自 `/data/multimedia-ana/testlab/video-scene/runs/20260421_104129/summary.json`：

- `status = succeeded`
- `video_count = 6`
- `succeeded_count = 6`
- `failed_count = 0`
- `total_scene_count = 777`
- `total_image_count = 2349`
- `total_elapsed_seconds = 128.213`

服务健康状态：

- `ok = true`
- `worker_online = true`
- `queued_jobs = 0`
- `worker.status = running`

## 单视频结果

### `BV1CidqBUE2R.mp4`

- `scene_count = 27`
- `image_count = 84`
- `elapsed_seconds = 10.022`
- 结果密度正常

### `BV1EfQEBjE27.mp4`

- `scene_count = 380`
- `image_count = 1143`
- `elapsed_seconds = 46.059`
- 场景切分明显过碎

### `BV1Vnd8B2E1D.mp4`

- `scene_count = 95`
- `image_count = 288`
- `elapsed_seconds = 16.030`
- 中等偏高切分密度

### `BV1brX4B9EJQ.mp4`

- `scene_count = 12`
- `image_count = 39`
- `elapsed_seconds = 6.019`
- 结果密度正常

### `BV1ecoABBEMm.mp4`

- `scene_count = 230`
- `image_count = 693`
- `elapsed_seconds = 42.061`
- 场景切分明显过碎

### `BV1feDCB1Eby.mp4`

- `scene_count = 33`
- `image_count = 102`
- `elapsed_seconds = 8.023`
- 结果密度正常

## 结果判断

### 1. API 链路验证通过

这次结果与旧版 QA 的最大区别是：

- run 目录下存在每个视频的 `analysis.json`
- 服务侧 `video-scene/output/job_*` 下存在对应结果文件
- `summary.json` 中记录的 `api_base_url` 为 `http://video-scene:7860`

因此可以确认：

- 任务是通过 API 提交的
- 状态轮询和结果下载成功
- `video-scene-api` 已具备可用的端到端处理能力

### 2. 默认参数仍有碎片化问题

当前默认参数：

- `threshold = 27.0`
- `min_scene_len = 0.6s`

在部分视频上仍明显偏敏感：

- `BV1EfQEBjE27.mp4`：`380` 个 scene
- `BV1ecoABBEMm.mp4`：`230` 个 scene

这会带来：

- 关键帧数量过大
- 结果粒度过碎
- 后续下游处理成本升高

因此，这轮测试可以证明“链路可用”，但还不能证明“默认参数已收敛到适合作为生产默认值”。

## 最终判断

当前阶段可以下两个结论：

1. `video-scene-api` 已经完成端到端 QA 验证，可进入下一步集成或联调。
2. 默认参数需要继续调优，尤其要压制高切分密度视频的碎片化问题。

## 建议

建议下一轮参数回归至少覆盖：

- `SCENE_THRESHOLD=30.0`
- `SCENE_THRESHOLD=32.0`
- `MIN_SCENE_LEN=1.0s`
- `MIN_SCENE_LEN=1.5s`

目标是找到一个更平衡的默认组合：

- 不明显漏切
- 不产生过量碎片
- 控制关键帧与 scene 数量
