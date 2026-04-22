# QA Testlab

这套测试子系统与主服务目录隔离，默认只使用：

- 仓库内 `qa/` 目录存放脚本与镜像定义
- `/data/multimedia-ana/testlab/video-scene` 存放测试输入清单、运行结果和关键帧产物

它不会修改宿主机 Python 环境，也不会要求在本机直接安装依赖。
`qa/*.sh` 会优先读取仓库根目录的 `.env`，复用其中的 `HOST_UID` 和 `HOST_GID`，避免测试资源变成 `root` 或 `nobody` 属主。

说明：
- `video-scene-api` 容器负责真正处理任务
- `qa` 镜像是一个纯 Python 测试客户端，只负责调用 API 和归档结果

## 目录

```text
qa/
  Dockerfile
  requirements.txt
  build_image.sh
  run_suite.sh
  run_scene_suite.py
```

对应的数据目录：

```text
/data/multimedia-ana/testlab/video-scene/
  runs/
```

## 目标

1. 批量遍历 `/data/multimedia-ana/example-video/` 下所有视频
2. 在 Docker 内通过 `video-scene-api` 提交任务、轮询状态并下载结果
3. 归档每个视频的结果 JSON 和汇总 JSON

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

## 结果位置

每次运行会生成：

- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/summary.json`
- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/manifest.json`
- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/<video_stem>/scene_report.json`
- `/data/multimedia-ana/testlab/video-scene/runs/<run_id>/<video_stem>/analysis.json`

## 当前限制

- 当前 QA 依赖本机已经启动 `video-scene-api`
- 当前默认通过 Docker 网络 `multimedia-ana_default` 直接访问 `http://video-scene:7860`
- 当前只覆盖 `detect-content` 路线
- 关键帧图片仍由服务写入 `/data/multimedia-ana/video-scene/output/<job_id>/`
