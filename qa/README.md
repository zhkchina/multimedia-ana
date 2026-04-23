# QA Testlab

这套测试子系统与主服务目录隔离，默认只使用：

- 仓库内 `qa/` 目录存放脚本与镜像定义
- `/data/multimedia-ana/testlab/` 存放测试运行结果

它不会修改宿主机 Python 环境，也不会要求在本机直接安装依赖。
`qa/*.sh` 会优先读取仓库根目录的 `.env`，复用其中的 `HOST_UID` 和 `HOST_GID`，避免测试资源变成 `root` 或 `nobody` 属主。

说明：
- 各服务容器负责真正处理任务
- `qa` 镜像是纯 Python 测试客户端，只负责调用统一 `/v1/tasks` API 和归档结果

## 目录

```text
qa/
  Dockerfile
  requirements.txt
  build_image.sh
  run_multimedia_suite.sh
  run_multimedia_suite.py
  compare_multimedia_runs.py
  run_suite.sh
  run_scene_suite.py
```

对应的数据目录：

```text
/data/multimedia-ana/testlab/video-scene/
  runs/
```

## 目标

1. 在 Docker 网络内调用统一 `/v1/tasks` 接口
2. 提交单文件任务、轮询状态并获取结果 JSON
3. 归档测试结果和汇总 JSON

## 使用顺序

先构建测试镜像：

```bash
cd /home/kun/tools/multimedia-ana
bash qa/build_image.sh
```

执行整套测试：

```bash
cd /home/kun/tools/multimedia-ana
bash qa/run_suite.sh
```

如果你想覆盖输入目录或输出目录：

```bash
cd /home/kun/tools/multimedia-ana
VIDEO_DIR=/data/multimedia-ana/example-video \
TESTLAB_DIR=/data/multimedia-ana/testlab/video-scene \
QA_NETWORK=multimedia-ana_default \
API_BASE_URL=http://video-scene:7860 \
bash qa/run_suite.sh
```

如果你想调整场景检测参数：

```bash
cd /home/kun/tools/multimedia-ana
PROFILE=standard \
SCENE_THRESHOLD=30.0 \
MIN_SCENE_LEN=1.0s \
SAVE_IMAGE_COUNT=1 \
bash qa/run_suite.sh
```

执行统一多媒体基线：

```bash
cd /home/kun/tools/multimedia-ana
bash qa/build_image.sh
bash qa/run_multimedia_suite.sh
```

默认行为：

- `api_mode=tasks_v1`
- 依次测试 `video-vl / scene / audio`
- 每个服务跑 `2` 次，便于记录冷/热态耗时
- 结果输出到 `/data/multimedia-ana/testlab/multimedia/runs/<run_id>/summary.json`

前后对比：

```bash
cd /home/kun/tools/multimedia-ana
python3 qa/compare_multimedia_runs.py \
  --before /data/multimedia-ana/testlab/multimedia/runs/<before_run>/summary.json \
  --after /data/multimedia-ana/testlab/multimedia/runs/<after_run>/summary.json \
  --output-md /data/multimedia-ana/testlab/multimedia/comparison.md
```

## 结果位置

每次运行会生成：

- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/summary.json`
- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/manifest.json`
- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/<video_stem>/scene_report.json`
- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/<video_stem>/analysis.json`

## 当前限制

- 当前 QA 依赖本机已经启动 `video-scene-api`
- 当前默认通过 Docker 网络 `multimedia-ana_default` 访问各服务
- 当前只覆盖当前单文件 JSON 输出路线
- `scene` 基准默认使用 `save_image_count=0`、`include_artifacts=false`
