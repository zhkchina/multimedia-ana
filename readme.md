本文件夹提供一套面向电影理解与视频二创的视频理解工具。

目标：
- 提供视频标注、视频切片与场景分析、语义识别、语义活动检测、ASR、VAD、forced alignment 等基础能力。
- 所有能力均通过 API 暴露，不直接耦合业务系统。
- 采用 Docker 化部署，避免污染宿主环境。
- 采用类似 `~/tools/index-tts` 的访问接口风格。
- 不同服务容器之间可以独立运行、独立调用；同一个服务容器内部任务串行执行。

当前重点：
- 视频标注模型优先采用 Qwen3-VL 系列。
- 已确认本机存在镜像：`qwenllm/qwenvl:qwen3vl-cu128`。
- 当前仓库只负责分析，不负责结果融合或视频构建。

设计文档：
- [视频理解总体架构](./docs/video-understanding-architecture.md)
- [Qwen3-VL Transformers 后端说明](./docs/qwen3-vl-transformers-backend.md)
  - 含当前性能测试结论、队列复用结论、GPU 占用统计和 `flash_attention_2` 评估
- [工程完备性差距分析](./docs/engineering-gap-analysis.md)

当前已实现：
- 常驻 `docker-api` FastAPI 控制面
- 按需拉起 `video-vl` worker 容器
- worker 空闲默认保活 `1800s`，减少队列场景下的重复冷启动
- 统一数据根目录：`/data/multimedia-ana`
- 宿主机高位端口对外暴露：`18086`
- `POST /jobs`、`GET /jobs/{job_id}`、`GET /jobs/{job_id}/result`、`GET /health`
- `video-vl` 默认按官方 README 推荐方式接入 `transformers`
- 默认模型：`Qwen/Qwen3-VL-8B-Instruct`
- 已去掉 `vLLM` 路线与相关配置，避免误导

启动方式：
- `docker compose build`
- `docker compose up -d docker-api`
- 如果只想单独补构建 worker：`docker compose build video-vl-worker`

常规运维脚本：
- `bash scripts/build.sh`
- `bash scripts/build.sh api`
- `bash scripts/build.sh worker`
- `bash scripts/up.sh`
- `bash scripts/down.sh`
- `bash scripts/logs.sh api`
- `bash scripts/logs.sh worker`
- `bash scripts/submit_job.sh /data/multimedia-ana/your_video.mp4`
- `bash scripts/benchmark_two_jobs.sh /data/multimedia-ana/your_video.mp4`
- `bash scripts/benchmark_n_jobs.sh 5`
  默认循环输入 `/data/multimedia-ana/example-video/` 下的视频，也可用 `VIDEO_DIR=/your/path` 覆盖目录。

联调脚本：
- `bash scripts/smoke_test_video_vl.sh /path/to/video.mp4`
- 默认调用 `http://127.0.0.1:18086`
- 默认把测试视频复制到 `/data/multimedia-ana/smoke_test_input.mp4`

当前限制：
- 首次运行 `video-vl` worker 时，如本地没有模型权重，会下载 `Qwen/Qwen3-VL-8B-Instruct` 到 `/data/multimedia-ana/video-vl/cache/huggingface`。
- 目前只实现了 `video-vl` 服务，`scene/audio` 还未接入。
