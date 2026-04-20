# 视频理解总体架构

## 1. 当前约束与结论

本机资源：
- GPU：`NVIDIA GeForce RTX 4090 D`
- 显存：`24 GB`
- 已有镜像：`qwenllm/qwenvl:qwen3vl-cu128`

部署目标：
- 当前目录不是生产目录，只提供工具接口。
- 所有能力必须 API 化。
- 所有服务都运行在 Docker 中。
- 接口风格参考 `index-tts`。
- 不同服务容器之间可以独立运行，也可以被上层并行调用。
- 同一个服务容器内部任务串行执行。
- 不常驻长期占用 GPU。
- 当前仓库只负责分析，不负责结果融合或视频构建。

基于以上约束，视频标注模型建议如下。

## 2. Qwen3-VL 选型建议

推荐主模型：
- `Qwen/Qwen3-VL-8B-Instruct`

推荐降级模型：
- `Qwen/Qwen3-VL-4B-Instruct`

暂不建议当前机器直接作为主力部署的模型：
- `Qwen/Qwen3-VL-30B-A3B-Instruct`
- `Qwen/Qwen3-VL-32B-Instruct`
- `Qwen/Qwen3-VL-235B-A22B-*`
- `Thinking` 版本

原因：
- `8B-Instruct` 是单卡 24GB 上最有现实意义的主力档位。
- `4B-Instruct` 更适合做高频粗标、预筛选和低成本回填。
- `30B/32B` 在单张 24GB 4090 D 上不适合作为常规视频 API worker。
- `Thinking` 版本更偏长推理和研究型问答，不适合当前“服务化视频标注”目标。

建议采用双层策略：
- 标准标注：默认走 `8B-Instruct`
- 批量粗标：走 `4B-Instruct`
- 重点片段复核：仍走 `8B-Instruct`

## 3. 处理原则

Qwen3-VL 很强，但电影理解不应该直接把整部电影一次性交给一个 VL 模型。

更合理的方式是：
1. 先做切片和结构化预处理。
2. 再把镜头级或片段级内容送入 VL 模型做语义标注。
3. 各服务分别输出自己的分析结果。

这里要明确：
- 本仓库只负责分析服务。
- 本仓库不负责跨服务结果融合。
- 本仓库不负责视频生成、剪辑或构建。

## 4. 总体架构

当前建议不要做一个统一大调度器，而是做多个独立分析服务。

每个服务都遵循同一规则：
- 自己提供 HTTP API
- 自己管理自己的 job 目录
- 自己的容器内部串行执行任务
- 不同服务之间互相独立
- 是否并行由上层调用方决定

建议拆成 3 类分析服务。

### A. `video-vl-api`

职责：
- 视频标注
- 镜头语义理解
- 角色、动作、情绪、场景描述
- 二创可用摘要

资源类型：
- GPU

模型：
- `Qwen/Qwen3-VL-8B-Instruct`
- 降级模型 `Qwen/Qwen3-VL-4B-Instruct`

镜像基础：
- `qwenllm/qwenvl:qwen3vl-cu128`

### B. `video-scene-api`

职责：
- 视频切片
- 镜头边界检测
- 关键帧抽取
- 场景段分析

资源类型：
- CPU

组件：
- `ffmpeg`
- `PySceneDetect`

### C. `video-audio-api`

职责：
- ASR
- VAD
- forced alignment

资源类型：
- CPU 或轻 GPU

### D. 存储与共享目录

职责：
- 保存输入视频
- 保存中间产物
- 保存每个服务的 JSON 输出

建议：
- 当前阶段直接使用宿主目录挂载
- 每个服务拥有自己独立的 `jobs/`、`output/`、`cache/`
- 不做跨服务统一结果汇总

明确排除项：
- 当前不做 `video-fusion`
- 当前不负责结果对齐汇总
- 当前不负责视频生成、剪辑或构建

## 5. 推荐的数据流

当前不做统一编排，只做独立分析服务。

推荐用法是由上层脚本、调用方或人工步骤决定调用顺序。

例如：
1. 先调用 `video-scene-api`
2. 再调用 `video-audio-api`
3. 再调用 `video-vl-api`

也可以：
1. `video-scene-api` 和 `video-audio-api` 并行运行
2. 完成后再把片段或关键帧送到 `video-vl-api`

这里的重点是：
- 不同服务之间允许并行
- 同一个服务内部保持串行
- 本仓库输出的是“分服务分析结果”
- 不是“融合后的最终电影知识层”

因此当前输出应保持“分服务结果”：
- `scene` 输出自己的切片和关键帧 JSON
- `audio` 输出自己的 ASR/VAD/alignment JSON
- `vl` 输出自己的标注 JSON

## 6. Docker 形态建议

当前建议每个分析服务都采用类似 `index-tts` 的模式：
- 常驻一个 API 容器
- API 容器对外暴露接口
- 通过共享目录处理输入输出
- 服务内部任务串行执行

对 CPU 服务：
- 可以直接在服务容器内串行处理 job

对 GPU 服务：
- 可以采用两种实现

方案一：
- `video-vl-api` 容器内直接处理任务
- 容器常驻，但服务内部任务串行

方案二：
- `video-vl-api` 作为常驻 API 容器
- API 容器通过 Docker socket 拉起临时 `worker-vl-qwen3`
- worker 完成后退出

当前更推荐：
- `scene` 和 `audio` 先用容器内串行处理
- `vl` 使用 `api + 临时 worker`，因为 GPU 更值得按需释放

## 7. 服务边界建议

不要把以下能力塞进同一个容器：
- 视频切片
- 音频识别
- Qwen3-VL 推理

原因：
- 资源模式不同
- 依赖冲突概率高
- 不利于按需释放 GPU
- 日后替换模型会很麻烦

正确边界应该是：
- `video-scene-api` 独立
- `video-audio-api` 独立
- `video-vl-api` 独立

## 8. API 设计建议

每个服务都尽量统一成 `index-tts` 风格。

建议统一接口：
- `GET /health`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/result`

可选管理接口：
- `POST /admin/worker/wakeup`
- `POST /admin/worker/shutdown`

### `video-vl-api`

提交任务：
- `POST /jobs`

请求体建议：
- `video_uri`
- `profile`
- `model`
- `language`
- `max_segment_duration`
- `sample_fps`
- `return_formats`

说明：
- `profile` 可选 `draft` / `standard` / `deep`
- `model` 可选 `qwen3-vl-4b` / `qwen3-vl-8b`

结果建议：
- 标注 JSON

### `video-scene-api`

提交任务：
- `POST /jobs`

请求体建议：
- `video_uri`
- `profile`
- `min_scene_len`
- `threshold`
- `extract_keyframes`

结果建议：
- 镜头边界
- 场景段列表
- 关键帧清单

### `video-audio-api`

提交任务：
- `POST /jobs`

请求体建议：
- `video_uri`
- `language`
- `enable_vad`
- `enable_alignment`

结果建议：
- ASR 文本
- 语音片段时间戳
- forced alignment JSON

## 9. 视频标注输出建议

Qwen3-VL 不应只输出一段自然语言描述，应输出结构化结果。

建议让模型输出：
- `scene_summary`
- `shot_type`
- `characters`
- `actions`
- `emotion`
- `location`
- `objects`
- `cinematic_tags`
- `clip_value`
- `reason`

这样后续更容易做：
- 检索召回
- 标签聚合
- 剧情摘要
- 爆点片段筛选

## 10. 当前阶段的最优落地顺序

第一阶段：
- 先部署 `video-vl-api`
- 先打通视频片段输入到结构化标注输出
- 模型先用 `Qwen3-VL-8B-Instruct`
- 同时保留 `4B-Instruct` 作为降级路径

第二阶段：
- 增加 `video-scene-api`
- 把整视频先切成镜头段，再逐段送 Qwen3-VL

第三阶段：
- 增加 `video-audio-api`
- 引入 ASR / VAD / forced alignment

第四阶段：
- 根据外部项目需要再决定是否做融合
- 当前仓库不包含融合服务

## 11. 我对当前机器的最终建议

如果你现在就要开始做：
- 主模型选 `Qwen3-VL-8B-Instruct`
- 降级模型选 `Qwen3-VL-4B-Instruct`
- 不建议在这张 24GB 4090 D 上把 `30B/32B` 当作常规 API worker
- 先以“片段级标注服务”切入，不要直接上“整片级单次理解”

一句话结论：
- 这台机器适合把 `Qwen3-VL-8B-Instruct` 做成独立 GPU 分析服务，而不是做大模型常驻多并发推理节点。

## 12. 参考依据

官方信息核对要点：
- Qwen3-VL 官方仓库说明其支持长视频理解、视频时间对齐，并建议使用 `vLLM >= 0.11.0` 进行部署。
- 官方仓库明确提供 Docker 镜像 `qwenllm/qwenvl`。
- 官方模型集合包含 `2B / 4B / 8B / 30B-A3B / 32B / 235B-A22B` 多个档位。

参考链接：
- GitHub: https://github.com/QwenLM/Qwen3-VL
- README: https://github.com/QwenLM/Qwen3-VL/blob/main/README.md
- Hugging Face Collection: https://huggingface.co/collections/Qwen/qwen3-vl
