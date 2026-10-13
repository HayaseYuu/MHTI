# MHTI 增强版 1.0.0

基线：HayaseYuu/MHTI `ec04e3c`，原版本标识 2.0.0。
本发布采用增强版独立 1.0.0 序列，不修改上游版本历史。

## 新增功能

- 表番刮削：TMDB + AniList 并行搜索，动画分类与非成人过滤。
- 双源补全：严格同标题、同年且无歧义时关联，补充缺失简介、评分、图片与类型。
- 单源回退：TMDB 无匹配、无凭据或不可用时可使用 AniList 独立条目。
- 创建刮削任务 → 配置选项：R18 开关，默认关闭，符合现有选项行、Naive UI 与主题设计。
- 模式持久化：单文件任务、历史、冲突处理、手动 ID 重刮、批量请求沿用同一设置。
- 来源展示：TMDB / AniList 徽章、正确外链与海报，双源真实 NFO uniqueid。
- AniList 图片下载、来源感知的历史图片与离线重新整理。
- API 流程不再强制要求 TMDB Cookie；R18 模式仍验证 TMDB Token。
- 发布门禁：后端测试和前端类型检查成功后才发布源码/前端 ZIP 及 SHA256SUMS。

## 保留原有能力

修复原有 115 依赖兼容与目录浏览失效符号链接异常；修复 NFO 简介 XML 转义。
Python 最低版本统一为 3.12，依赖约束在 pip/Poetry 中保持一致。

本地和 115 网盘、复制/移动/硬链接/软链接、字幕关联、目录监控、任务队列、
冲突处理、Emby 检查、NFO/图片、历史操作与亮暗主题。

## 使用与限制

新任务 R18 关闭使用双源表番；开启使用原 TMDB 成人模式。
TMDB Token 在设置中配置；AniList 无需 Token，代理与超时沿用系统配置。
AniList 不提供逐集标题/剧情/日期，使用 Episode N 占位，只接受已知集数。
未知集数或季度不一致停在待处理，不猜测、不自动移动文件。
TMDB 多季数据不会被 AniList 的单季度结构覆盖。
旧版无模式快照的任务及历史记录按原成人模式恢复；新任务默认表番。

## 下载和部署

- `mhti-source-1.0.0.zip`：完整源码，包含双源服务、测试、文档及 Dockerfile。
- `mhti-frontend-1.0.0.zip`：前端构建产物，需搭配本版本后端。
- `SHA256SUMS.txt`：发行包完整性校验。

从源码解压后构建：

```bash
docker build -t mhti:1.0.0 .
docker run -d --name mhti -p 8000:8000 \
  -v "$PWD/data:/app/data" -v /path/to/media:/media \
  -e TZ=Asia/Shanghai mhti:1.0.0
```

本增强版源码发布不依赖 Docker Hub secrets，不覆盖上游作者镜像。
测试结果与提交 ID 见工作流和发布关联提交。升级前备份数据目录。
