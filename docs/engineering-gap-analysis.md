# 工程完备性差距分析

## 1. 目的

本文用于评估当前 `multimedia-ana` 与已稳定对外提供服务的 `~/tools/index-tts` 相比，在工程完备性方面还缺哪些关键部分。

说明：
- 本文只记录差距与建议
- 当前阶段先不实施
- 后续按优先级逐项补齐

## 2. 当前状态判断

当前 `multimedia-ana` 已具备：
- 可运行的 `docker-api + worker` 双容器结构
- 局域网可访问的 HTTP API
- `/data/multimedia-ana` 数据目录
- `Qwen3-VL-8B-Instruct + transformers` 已实测跑通
- 单任务、双任务、N 任务 benchmark 脚本
- worker 热复用能力

当前成熟度判断：
- 功能链路：已跑通
- 服务骨架：基本齐
- 工程完备度：中等
- 距离“稳定对外提供服务”：仍缺 QA、运维文档、配置治理、结果契约等关键部分

## 3. 与 index-tts 的主要差距

### 3.1 缺正式 QA 体系

当前问题：
- 只有运维脚本和 benchmark
- 没有独立的 `qa/` 目录
- 没有测试镜像
- 没有固定测试资产组织方式
- 没有正式测试报告

`index-tts` 对照：
- `qa/README.md`
- `qa/run_suite.sh`
- `qa/Dockerfile`
- `docs/test-report-*.md`

建议后续补齐：
- `qa/`
- `qa/README.md`
- `qa/run_suite.sh`
- benchmark 结果沉淀为正式报告

### 3.2 缺稳定服务级 README

当前 README 已能指导使用，但还不足以支撑长期稳定外部接入。

缺少内容：
- API 字段完整契约
- 错误码与状态码说明
- 响应体结构说明
- 输入路径规范
- 结果保留策略
- 已知性能区间
- 已知限制的系统化说明

建议后续补齐：
- 将 README 升级为“外部 agent 直接接手即可使用”的服务说明文档

### 3.3 缺部署/运维方案文档

当前已有：
- 架构文档
- transformers 后端说明

仍缺：
- 正式部署/运维文档

应包含：
- 为什么采用双容器
- worker 生命周期策略
- 队列与串行消费策略
- `/data` 目录约定
- benchmark 与日志保留策略
- 清理策略
- 后续扩展 `scene/audio` 的服务边界

### 3.4 缺统一配置入口

当前问题：
- 配置主要写在 `docker-compose.yml`

风险：
- 改端口、UID/GID、数据根目录时不够集中
- 跨机器迁移时容易漏改

建议后续补齐：
- `.env`
- 对 compose 做变量收敛

### 3.5 缺 `.dockerignore`

当前问题：
- 还没有 `.dockerignore`

风险：
- 构建上下文膨胀
- benchmark 结果、临时文件或其他无关文件被带进 build context
- 构建效率和可控性下降

建议后续补齐：
- `.dockerignore`

### 3.6 缺更正式的运维脚本

当前已有：
- `build.sh`
- `up.sh`
- `down.sh`
- `logs.sh`
- `submit_job.sh`
- `smoke_test_video_vl.sh`
- `benchmark_two_jobs.sh`
- `benchmark_n_jobs.sh`

仍缺：
- `status.sh`
- `clean.sh` 或 `prune_jobs.sh`

建议后续补齐：
- `status.sh`
  - 汇总 `/health`
  - 容器状态
  - worker 运行状态
  - 最近任务状态
- `clean.sh`
  - 清理旧 job
  - 清理旧 output
  - 清理旧 benchmark
  - 清理异常 lock

### 3.7 缺结果契约与输出 schema 文档

当前问题：
- 已有结果 JSON
- 但没有正式 schema 文档

风险：
- 外部系统接入时会依赖当前实现细节
- 后续字段调整容易破坏兼容性

建议后续补齐：
- 结果 JSON schema 文档
- 结果字段版本约定
- 错误结果结构说明

### 3.8 缺版本与兼容性记录

当前问题：
- 已经依赖固定镜像与模型组合
- 但没有专门文档记录“已验证组合”

建议后续补齐：
- 已验证镜像 tag
- 已验证模型版本
- 当前已知限制
- `flash_attn` 状态

### 3.9 缺局域网服务边界说明

当前问题：
- 现在对局域网开放
- 但没有写清楚安全边界

应补充：
- 当前无鉴权
- 仅适合受控内网
- 不适合直接暴露公网

## 4. 优先级建议

### 第一优先级

应最先补齐：
- `qa/` 目录与正式回归测试入口
- 部署/运维文档
- `.env`
- `.dockerignore`

原因：
- 这些是从“可用”走向“稳定可维护”的基础设施

### 第二优先级

应随后补齐：
- `status.sh`
- `clean.sh` / `prune_jobs.sh`
- 输出 schema 文档

原因：
- 直接影响长期运维与外部接入质量

### 第三优先级

后续补齐：
- 正式测试报告
- 性能基线文档
- 版本/兼容性记录
- 局域网安全边界说明

## 5. 建议的下一阶段补齐顺序

后续实施建议顺序：

1. `.env`
2. `.dockerignore`
3. `docs/deployment-plan.md`
4. `status.sh`
5. `clean.sh`
6. `qa/README.md`
7. `qa/run_suite.sh`
8. 正式测试报告
9. 输出 schema 文档

## 6. 一句话结论

当前 `multimedia-ana` 已经达到“功能跑通、服务可用”的阶段，但距离 `index-tts` 那种“稳定对外提供服务”的工程完备度，还差：
- QA 体系
- 部署/运维文档
- 配置治理
- 运维状态与清理工具
- 结果契约与正式测试沉淀
