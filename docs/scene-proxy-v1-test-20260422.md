# Scene 模块测试报告

日期：
- `2026-04-22`

测试目标：
- 使用与视频理解模块相同的视频输入，验证 `scene` 模块的 JSON-only 输出
- 确认服务端不再保留 `csv/图片` 等业务产物
- 为下一步设计视频理解接口提供场景索引参考

输入文件：
- `/data/multimedia-ana/example-video/proxy_v1.local.mp4`

调用方式：
- `scene` API
- `POST /v1/tasks`
- `wait_seconds=0`
- 轮询 `GET /v1/tasks/{id}`
- 最终取 `GET /v1/tasks/{id}/result`

请求协议：

```json
{
  "input": {
    "file_uri": "/workspace/.tmp_proxy_scene_input/proxy_v1.local.mp4",
    "params": {
      "profile": "standard",
      "threshold": 27.0,
      "min_scene_len": "0.6s",
      "save_image_count": 0,
      "include_artifacts": false
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
```

测试命令：

```bash
docker run --rm \
  --network multimedia-ana_default \
  --user 1001:1003 \
  -v /data/multimedia-ana:/data/multimedia-ana \
  -v /home/kun/tools/multimedia-ana:/workspace \
  -w /workspace \
  multimedia-ana-video-scene-qa:local \
  python3 qa/run_scene_suite.py \
    --video-dir /workspace/.tmp_proxy_scene_input \
    --output-dir /tmp/scene-json-only-20260422b \
    --api-base-url http://video-scene:7860 \
    --profile standard \
    --threshold 27.0 \
    --min-scene-len 0.6s \
    --save-image-count 0 \
    --poll-interval-seconds 2 \
    --timeout-seconds 3600
```

任务结果概览：
- `task_id`: `task_20260422_095948_574c20f7`
- `elapsed_seconds`: `67`
- `scene_count`: `2410`
- `image_count`: `0`

返回 JSON 关键结构：
- `service`
- `file_uri`
- `profile`
- `threshold`
- `min_scene_len`
- `save_image_count`
- `scene_count`
- `image_count`
- `scenes`

本次参数：
- `profile`: `standard`
- `threshold`: `27.0`
- `min_scene_len`: `0.6s`
- `save_image_count`: `0`
- `include_artifacts`: `false`

前 3 个场景：

```json
[
  {
    "scene_number": 2,
    "start_frame": 49,
    "start_timecode": "00:00:02.002",
    "start_seconds": 2.002,
    "end_frame": 521,
    "end_timecode": "00:00:21.730",
    "end_seconds": 21.73,
    "length_frames": 473,
    "length_timecode": "00:00:19.728",
    "length_seconds": 19.728
  },
  {
    "scene_number": 3,
    "start_frame": 522,
    "start_timecode": "00:00:21.730",
    "start_seconds": 21.73,
    "end_frame": 659,
    "end_timecode": "00:00:27.486",
    "end_seconds": 27.486,
    "length_frames": 138,
    "length_timecode": "00:00:05.756",
    "length_seconds": 5.756
  },
  {
    "scene_number": 4,
    "start_frame": 660,
    "start_timecode": "00:00:27.486",
    "start_seconds": 27.486,
    "end_frame": 766,
    "end_timecode": "00:00:31.949",
    "end_seconds": 31.949,
    "length_frames": 107,
    "length_timecode": "00:00:04.463",
    "length_seconds": 4.463
  }
]
```

后 1 个场景：

```json
{
  "scene_number": 2411,
  "start_frame": 153274,
  "start_timecode": "01:46:32.761",
  "start_seconds": 6392.761,
  "end_frame": 153441,
  "end_timecode": "01:46:39.768",
  "end_seconds": 6399.768,
  "length_frames": 168,
  "length_timecode": "00:00:07.007",
  "length_seconds": 7.007
}
```

产物清理检查：
- `/data/multimedia-ana/video-scene/output/task_20260422_095948_574c20f7`: 不存在
- `/data/multimedia-ana/video-scene/runtime/tasks/task_20260422_095948_574c20f7`: 不存在

结论：
- `scene` 模块已成功处理 `proxy_v1.local.mp4`
- 当前默认参数下切出了 `2410` 个场景，切分非常细
- 返回 JSON 已经足够作为后续视频理解接口设计的场景索引来源
- 当前协议下服务端不再为该任务保留 `csv/图片` 输出目录
- 如果下一步要直接分析 `260-360` 场景，可以直接基于本次返回的 `scenes[]` 取对应 `scene_number / start_seconds / end_seconds`
- 当前默认参数更像“高召回切分”，后续如果要降低片段数，优先调 `threshold` 和 `min_scene_len`
