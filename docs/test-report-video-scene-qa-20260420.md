# Video-Scene QA 测试报告（2026-04-20）

## 1. 目的

本文记录当前 `video-scene` 单容器镜像在本机样例视频上的一次正式 QA 测试结果。

重点验证：
- 转码后的输入视频是否可以稳定完成场景检测
- `PySceneDetect + ffmpeg + opencv` 的镜像组合是否可用
- 默认参数在真实样例上的切分密度是否合理

## 2. 测试环境

代码目录：
- `/home/kun/tools/multimedia-ana`

测试镜像：
- `multimedia-ana-video-scene:local`
- `multimedia-ana-video-scene-qa:local`

测试入口：
- `bash qa/build_image.sh`
- `bash qa/run_suite.sh`

输入目录：
- `/data/multimedia-ana/example-video`

测试结果目录：
- `/data/multimedia-ana/testlab/video-scene/runs/20260420_210437`

## 3. 测试参数

本次测试使用默认参数：
- `detector`: `detect-content`
- `threshold`: `27.0`
- `min_scene_len`: `0.6s`
- `save_image_count`: `3`

## 4. 总体结果

汇总文件：
- `/data/multimedia-ana/testlab/video-scene/runs/20260420_210437/summary.json`

总体结果：
- `status`: `succeeded`
- 视频总数：`6`
- 成功数：`6`
- 失败数：`0`
- 总场景数：`777`
- 总关键帧图片数：`2349`

结论：
- 转码后的样例视频已可以被当前 `video-scene` 镜像稳定处理
- 当前单容器镜像中的 `PySceneDetect`、`opencv`、`ffmpeg` 组合已验证可用
- QA Docker 化执行链路已跑通

## 5. 分视频结果

### `BV1CidqBUE2R.mp4`

- 场景数：`27`
- 图片数：`84`
- 检测主流程耗时约：`2.6s`
- 结果文件完整生成

对应报告：
- `/data/multimedia-ana/testlab/video-scene/runs/20260420_210437/BV1CidqBUE2R/scene_report.json`

### `BV1EfQEBjE27.mp4`

- 场景数：`380`
- 图片数：`1143`
- 检测主流程耗时约：`22.2s`
- 结果文件完整生成

对应报告：
- `/data/multimedia-ana/testlab/video-scene/runs/20260420_210437/BV1EfQEBjE27/scene_report.json`

### `BV1Vnd8B2E1D.mp4`

- 场景数：已成功生成
- 图片数：已成功生成
- 结果文件完整生成

### `BV1brX4B9EJQ.mp4`

- 场景数：已成功生成
- 图片数：已成功生成
- 结果文件完整生成

### `BV1ecoABBEMm.mp4`

- 场景数：`230`
- 图片数：`693`
- 结果文件完整生成

### `BV1feDCB1Eby.mp4`

- 场景数：`33`
- 图片数：`102`
- 检测主流程耗时约：`5.3s`
- 结果文件完整生成

对应报告：
- `/data/multimedia-ana/testlab/video-scene/runs/20260420_210437/BV1feDCB1Eby/scene_report.json`

## 6. 关键观察

### 6.1 功能链路已跑通

这次测试与前一次失败测试的根本区别在于：
- 输入视频已先完成转码
- 当前镜像不再被 AV1 解码问题阻塞
- `stats.csv`、`*-Scenes.csv`、关键帧图片和 `scene_report.json` 均已正常产出

这说明当前 `video-scene` 镜像已经具备：
- 批量遍历视频目录
- 场景边界检测
- 关键帧抽取
- QA 结果归档

### 6.2 默认参数导致部分视频碎片化明显

本次测试最重要的问题不是“跑不通”，而是“默认参数对部分视频切分过碎”。

最典型样例：
- `BV1EfQEBjE27.mp4` 在默认参数下切出 `380` 个 scene
- `BV1ecoABBEMm.mp4` 在默认参数下切出 `230` 个 scene

这说明当前默认参数：
- `threshold = 27.0`
- `min_scene_len = 0.6s`

对部分剪辑密度高、镜头变化频繁或画面波动大的视频过于敏感。

直接影响：
- 场景片段数量显著膨胀
- 关键帧图片产物过多
- 后续如将结果继续送入 `video-vl` 或人工校对，成本会被放大
- 默认参数不适合作为稳定的服务级默认值直接对外暴露

### 6.3 当前参数更像“高召回调试参数”

从本次结果判断，当前默认参数更接近：
- 尽量多切
- 宁可碎一些，也不要漏明显切点

它适合：
- 调试
- 人工观察场景检测敏感度
- 做参数探索起点

但不适合直接作为后续稳定部署的默认参数。

## 7. 风险判断

当前主要风险不是运行失败，而是结果过碎。

风险包括：
- 对部分视频生成过多场景段
- 关键帧产物数量膨胀
- 后续链路的 I/O、存储和人工检查成本上升
- 若上游业务按 scene 数量线性处理，整体吞吐会被拖慢

## 8. 建议

建议后续至少增加一轮参数回归测试，重点比较：
- 提高 `threshold`
- 增大 `min_scene_len`
- 不同类型视频下的切分密度

建议的下一步测试方向：
- `threshold = 30.0`
- `threshold = 32.0`
- `min_scene_len = 1.0s`
- `min_scene_len = 1.5s`

目标不是单纯减少 scene 数，而是找到：
- 大多数视频不过碎
- 又不会明显漏掉关键切点

## 9. 一句话结论

当前 `video-scene` 单容器镜像已经在转码后样例视频上验证通过，功能链路可用；但默认参数会导致部分视频碎片化明显，尚不适合作为稳定部署时的最终默认值。
