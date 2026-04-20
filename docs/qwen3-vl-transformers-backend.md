# Qwen3-VL Transformers Backend

## 1. 当前实现

当前 `video-vl` worker 已按 Qwen3-VL 官方 README 切换为 `transformers` 路线。

实现方式：
- `AutoModelForImageTextToText.from_pretrained(...)`
- `AutoProcessor.from_pretrained(...)`
- `qwen_vl_utils.process_vision_info(...)`
- `model.generate(...)`

目标：
- 保留 `Qwen/Qwen3-VL-8B-Instruct`
- 去掉 `vLLM` 路线与相关配置
- 让当前单卡 `24GB` 机器优先追求可运行性，而不是高并发吞吐

## 2. 官方参考

官方 README 明确提供了 `transformers` 的视频处理示例，包含：
- 本地视频路径输入
- `process_vision_info(...)`
- `processor(...)`
- `model.generate(...)`

参考：
- GitHub README:
  https://github.com/QwenLM/Qwen3-VL/blob/main/README.md

官方还说明：
- Qwen3-VL 需要 `transformers >= 4.57.0`
- 推荐在多图像和视频场景中启用 `flash_attention_2` 以提升速度并节省显存

## 3. 当前代码约定

### 模型

- 模型固定为：`Qwen/Qwen3-VL-8B-Instruct`
- 不再保留 `vLLM` 后端开关

### 输入

外部 API 仍然保持最小业务输入：
- `video_uri`
- `language`
- `profile`
- `sample_fps`
- `max_frames`

### 内部推理策略

当前内部使用以下保守策略：
- `max_frames` 默认上限为 `64`
- 视频通过 `file://` URI 传给 `qwen_vl_utils`
- 生成参数采用官方 Instruct 推荐值：
  - `temperature=0.7`
  - `top_p=0.8`
  - `top_k=20`
  - `repetition_penalty=1.0`

### 注意事项

- 若镜像中存在 `flash_attn`，则启用 `flash_attention_2`
- 若不存在，则自动回退到默认 attention 实现
- 不要求额外安装 `vLLM`

## 4. 当前架构不变的部分

以下内容保持不变：
- `docker-api` 常驻控制面
- 按需拉起 `video-vl-worker`
- `/data/multimedia-ana` 数据目录
- job 文件存储
- 运维脚本

## 5. 预期收益

- 避免 `vLLM` 在当前 `24GB` 单卡上的 engine 初始化显存失败
- 保留现有 API 和调度结构
- 继续使用官方 `qwenllm/qwenvl:qwen3vl-cu128` 镜像

## 6. 预期代价

- 吞吐低于 `vLLM`
- 首次模型加载仍然较慢
- 长视频推理时间会更长

一句话结论：
- 当前项目以“单任务可运行”为优先，`transformers` 是比 `vLLM` 更符合这台机器约束的实现路线。

## 7. 已验证性能结论

### 单任务测试

测试视频：
- 时长约 `115.755s`
- 文件大小约 `11.38MB`
- 当前默认输入上限：`64` 帧

实测结果：
- 冷启动单任务总耗时约 `33s`
- 热态单任务实际处理时间约 `13s` 到 `14s`

结论：
- 当前 `Qwen3-VL-8B-Instruct + transformers` 在这台 `24GB 4090 D` 上已经达到可用状态
- 对单视频标注服务而言，这个速度是可接受的

### 连续双任务测试

已验证：
- worker 保活时间设置为 `1800s`
- 连续提交两个相同视频任务

结果：
- 第一个任务承担模型冷启动成本
- 第二个任务没有再次加载模型
- worker 日志中只出现一次模型加载

结论：
- 当前实现已经具备“队列场景下复用已加载模型”的能力
- 后续任务可以复用同一个常驻 worker，而不是每个任务都冷启动

### GPU 使用情况

连续双任务基准测试结果：
- 平均 GPU 利用率约 `51.93%`
- 峰值 GPU 利用率 `100%`
- 平均显存占用约 `20314MB`
- 峰值显存占用约 `20314MB`

结论：
- 当前不是“显存没吃满”的问题，而是“显存较高、计算利用率中等”
- 说明瓶颈不完全在纯 GPU 算力，还包括：
  - 视频解码与预处理
  - Python 调度
  - attention 实现
  - token 生成过程

## 8. 关于 flash_attention_2 的评估结论

当前状态：
- 官方 README 推荐在多图像和视频场景启用 `flash_attention_2`
- 当前镜像内未安装 `flash_attn`
- 当前 worker 已实现自动检测：如存在 `flash_attn` 则启用，否则回退默认 attention

收益判断：
- 这是一个值得尝试的优化点
- 预期收益主要体现在热态任务，而不是冷启动阶段
- 更现实的收益区间是“小幅到中幅提升”，而不是数量级提升

保守预估：
- 热态单任务有机会获得约 `10%` 到 `30%` 的提速
- 同时可能改善 attention 相关显存效率

风险判断：
- 代码改动很小
- 但环境改造复杂度中高
- 主要风险在 `Python 3.12 + torch 2.8.0+cu128 + qwenllm/qwenvl:qwen3vl-cu128` 组合下安装 `flash_attn` 的稳定性

当前决策：
- 暂不进行 `flash_attention_2` 优化
- 保持当前已跑通的 `transformers` 路线作为主线实现
