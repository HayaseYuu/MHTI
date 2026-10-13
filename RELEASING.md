# 增强版发布

- `VERSION`、Python/Vue/API/Docker 标签保持同一版本。
- 推送 main 的 `VERSION` 变更，触发 **Enhanced Source Release**。
- 后端测试、前端类型检查及构建全部成功后，按 `VERSION` 创建相应标签与 GitHub Release。
- 发布源码 ZIP、前端 ZIP 后，自动调用 Docker Release Assets 工作流。
- 两个原生 runner 从正式版本标签分别构建 AMD64 / ARM64，启动验收后补发镜像包。
- SHA256SUMS 同时覆盖源码、前端及镜像；不需要 Docker Hub secrets。
- 发行说明采用 `RELEASE_NOTES_<VERSION>.md`，不只列提交标题。
- 工作流支持手动运行；同名版本已有 Release 时不覆盖已有资产。
- 已发布的版本可手动运行 Docker Release Assets，输入原版本标签进行镜像补发。
- 原 Build and Release 工作流仍可选用，它依赖 Docker Hub secrets；
  增强版自动源码发布不触发它，也不覆盖原作者 Docker 镜像。

---

## 原项目发布指南（保留参考）

# 版本发布指南

本项目使用 [语义化版本](https://semver.org/lang/zh-CN/) 进行版本控制。

## 版本格式

```
主版本号.次版本号.修订号[-预发布标识]

示例：
- 1.0.0      - 正式版本
- 1.1.0      - 新功能版本
- 1.1.1      - 修复版本
- 2.0.0-beta - 预发布版本
```

## 发布流程

### 1. 创建版本标签

```bash
# 确保在 main 分支
git checkout main
git pull origin main

# 创建标签
git tag -a v1.0.0 -m "Release v1.0.0: 初始发布"

# 推送标签
git push origin v1.0.0
```

### 2. 自动触发 Actions

推送标签后，GitHub Actions 会自动：

1. ✅ 构建前端 (Vue.js)
2. ✅ 构建 Docker 多架构镜像 (amd64, arm64)
3. ✅ 推送到 Docker Hub (`xiyan520/mhti:latest` 和版本标签)
4. ✅ 创建 GitHub Release

### 3. 手动触发发布

也可以在 GitHub Actions 页面手动触发：

1. 进入 Actions → Build and Release
2. 点击 "Run workflow"
3. 输入版本号（不带 v 前缀）
4. 选择是否为预发布版本

## 版本号规则

| 变更类型 | 版本变化 | 示例 |
|---------|---------|------|
| 重大不兼容变更 | 主版本号 +1 | 1.0.0 → 2.0.0 |
| 新功能（向后兼容） | 次版本号 +1 | 1.0.0 → 1.1.0 |
| Bug 修复 | 修订号 +1 | 1.0.0 → 1.0.1 |
| 预发布版本 | 添加后缀 | 1.1.0-alpha, 1.1.0-beta, 1.1.0-rc.1 |

## Docker 标签策略

发布 `v1.2.3` 时，会自动创建以下标签：

| 标签 | 说明 |
|------|------|
| `xiyan520/mhti:1.2.3` | 完整版本号 |
| `xiyan520/mhti:1.2` | 主次版本号 |
| `xiyan520/mhti:1` | 主版本号 |
| `xiyan520/mhti:latest` | 最新稳定版（非预发布） |

## 必需的 Secrets 配置

在 GitHub 仓库设置中配置以下 Secrets：

| Secret 名称 | 说明 |
|------------|------|
| `DOCKERHUB_USERNAME` | Docker Hub 用户名 |
| `DOCKERHUB_TOKEN` | Docker Hub 访问令牌 |

### 获取 Docker Hub Token

1. 登录 [Docker Hub](https://hub.docker.com/)
2. 进入 Account Settings → Security
3. 创建 Access Token（选择 Read & Write 权限）
4. 复制 Token 到 GitHub Secrets

## 发布检查清单

发布前请确认：

- [ ] 所有测试通过
- [ ] 文档已更新
- [ ] CHANGELOG 已更新（如有）
- [ ] 版本号符合语义化规范
- [ ] Secrets 已正确配置
