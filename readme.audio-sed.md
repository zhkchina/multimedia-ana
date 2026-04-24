这个模块的目的是做一个电影音频的事件检测工具，把打斗、开枪、撞击、爆炸效果的精确时间点识别提取出来，为后续电影片段二创剪辑、卡点视频制作提供数据。

我测试了PANNs 方案，发现效果并不好，详细报告在 docs 目录下。

最新的方案如下：
先做电影音频拆分
1.优先研究 CASS / AV-CASS / DnR 这条线。
只在 effects 轨上找事件
2.用 FLAM 这种开放词汇模型，不要只靠封闭标签。

本模块范围只做以上两步，输出音频侧事件候选。视频识别、音画融合、是否存在目标打斗/开枪/爆破场面，以及最终精确定位，放在本接口的调用方完成。

工程上还是按照这个目录的统一规范来，api 负责监听和拉起重任务 docker。worker docker 在任务完成后释放 GPU 资源

关于其它要求同时参考~/tools/agent.md

当前初版流水线设计见：
- [Audio SED Pipeline Design](./docs/audio-sed-pipeline-design.md)

## 平台侧固定策略

平台侧只负责提供稳定的音频候选生产链路，不在本模块内做业务判定和阈值调优。当前固定策略：

- 每条音轨独立处理，独立输出，不在 `audio-sed` 内合并多音轨事件。
- BandIt 使用 GPU 做电影音频三 stem 分离，稳定配置为 `batch_size=8`。
- OpenFLAM 使用 CPU 做开放词汇声音定位，输入固定为每条音轨的 `effects.wav`。
- 默认过滤片段首尾边界事件，当前 `boundary_ignore_ms=300`。
- 默认对 OpenFLAM 候选做局部能量门控，当前 `min_event_local_rms_dbfs=-45`、`event_local_rms_window_ms=240`。
- 输出是音频侧事件候选，不判断是否最终存在打斗、开枪、爆破场面。
- 下游调用方负责结合视频识别结果、业务阈值和时间融合规则做最终判断。

当前已提供 worker 调试构建入口：

```bash
bash scripts/build.sh audio-sed
bash scripts/download_audio_sed_models.sh
bash scripts/run_audio_sed_debug.sh /data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4
```

`download_audio_sed_models.sh` 是首次准备或恢复模型缓存用的脚本；模型已存在时不需要每次运行。当前本机模型目录在：

```text
/data/multimedia-ana/audio-sed/vendor/bandit/
/data/multimedia-ana/audio-sed/models/bandit/
/data/multimedia-ana/audio-sed/models/openflam/
```

默认调试链路会使用：

- BandIt `dnr-3s-mus64-l1snr-bs8` 做电影三 stem 分离
- OpenFLAM `v1-base` 在 CPU 上做开放词汇音频定位
- 每条音轨输出独立的 `stream_result.json` 和 `events.jsonl`

典型输出目录：

```text
/data/multimedia-ana/audio-sed/runtime/debug/<run_id>/
  result.json
  pipeline_trace.json
  streams/
    stream_1/
      mix.wav
      effects.wav
      dialogue.wav
      music.wav
      events.jsonl
      stream_result.json
    stream_2/
      mix.wav
      effects.wav
      dialogue.wav
      music.wav
      events.jsonl
      stream_result.json
```

`result.json` 顶层只汇总 `summary` 和 `audio_streams`，不再提供合并后的顶层 `events`。每条音轨的候选事件在对应 `audio_streams[n].events` 与 `streams/stream_<index>/events.jsonl` 中。

如果只验证容器和 JSON 输出结构、不下载模型，可显式使用 passthrough 分离和 stub 定位：

```bash
AUDIO_SED_SEPARATION_BACKEND=passthrough \
AUDIO_SED_LOCALIZATION_BACKEND=stub_energy \
  bash scripts/run_audio_sed_debug.sh /data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4
```

下游可按业务需要覆盖定位参数，例如：

```bash
bash scripts/run_audio_sed_debug.sh <input.mp4> \
  --threshold 0.5 \
  --min-event-local-rms-dbfs -42 \
  --boundary-ignore-ms 300
```

这些参数属于业务使用方调参范围，平台默认值只保证稳定可运行和保守过滤明显伪影。

## BandIt checkpoint 横向测试

平台默认使用 BandIt 作为工程基线，不代表该 checkpoint 是最终效果最优。可横向测试多个 checkpoint：

```bash
bash scripts/download_audio_sed_bandit_grid.sh
bash scripts/run_audio_sed_bandit_grid.sh
```

默认测试：

```text
dnr-3s-bark64-l1snr
dnr-3s-erb64-l1snr
dnr-3s-mel64-l1snr
dnr-3s-mus64-l1snr
```

下载脚本会为每个 checkpoint 生成对应的 `-bs8` 稳定推理配置。网格测试脚本会跑两个示例切片，并输出：

```text
/data/multimedia-ana/audio-sed/runtime/grid/bandit_<GRID_ID>/summary.tsv
```

如需只测部分 checkpoint：

```bash
BANDIT_GRID_MODELS="dnr-3s-erb64-l1snr dnr-3s-mus64-l1snr" \
  bash scripts/download_audio_sed_bandit_grid.sh

BANDIT_GRID_MODELS="dnr-3s-erb64-l1snr dnr-3s-mus64-l1snr" \
  bash scripts/run_audio_sed_bandit_grid.sh
```
