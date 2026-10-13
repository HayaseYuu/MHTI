# 1.1.0 Docker 镜像部署

正式发布页：<https://github.com/HayaseYuu/MHTI/releases/tag/v1.1.0>

## 下载

按部署主机的 CPU 架构选择：

- Intel / AMD（x86_64）：`mhti-1.1.0-amd64.tar.gz`
- Apple Silicon / ARM64：`mhti-1.1.0-arm64.tar.gz`
- 同时下载 `SHA256SUMS.txt`。

两个镜像均从已发布的 `v1.1.0` 标签构建，不移动版本标签。
内置 Caddy、前端、后端及所有运行依赖，无需 Docker Hub 登录。

## 校验、加载、启动

以下以 AMD64 为例，ARM64 主机替换对应文件名：

```bash
# Linux 校验当前已下载的发行文件。
sha256sum -c SHA256SUMS.txt --ignore-missing
# macOS 可以使用 shasum -a 256 文件名，与 SHA256SUMS 对比。

gzip -dc mhti-1.1.0-amd64.tar.gz | docker load

docker run -d --name mhti \
  --restart unless-stopped \
  -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  -v /path/to/media:/media \
  -e TZ=Asia/Shanghai \
  mhti:1.1.0
```

浏览器访问 `http://你的主机:8000`，首次启动创建管理员账号。
将 `/path/to/media` 替换为自己的媒体目录。
刮削整理需要可写目录；只读扫描时可将媒体挂载改成只读，并单独挂载可写输出目录。
数据卷必须挂到 `/app/data`，不要改用其他容器路径。

## 可选 Compose

原项目 Compose 指向 `xiyan520/mhti:latest`，那不是本增强版镜像。
加载本版本后，请使用下面的配置或将原 Compose 的 image 改为 `mhti:1.1.0`。

```yaml
services:
  mhti:
    image: mhti:1.1.0
    pull_policy: never
    container_name: mhti
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - /path/to/media:/media
    environment:
      TZ: Asia/Shanghai
```

无需挂载源码、Caddyfile，也无需单独部署前端。
升级已有实例前备份数据卷；停止旧容器后使用保留的数据卷启动新实例。

## 构建验证

Docker Release Assets 工作流执行：

1. 原生 AMD64 / ARM64 构建并校验镜像架构、版本标签及来源提交。
2. `pip check` 与 115 / 双源元数据模块导入验证。
3. 实际启动容器，检查前端首页、API 版本、数据库健康与 readiness。
4. 导出 Docker save 归档、校验 gzip、生成 SHA-256，附加到同一版本 Release。

发布包是离线镜像归档，不是容器注册表地址，需先 `docker load` 再运行。
