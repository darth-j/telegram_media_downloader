# Docker 部署指南

本项目以 `Dineshkarthik/telegram_media_downloader` 当前版本为代码主体，并保留 `tangyoha` 版本常用的本地配置、下载目录、会话目录和代理部署方式。

## 从 tangyoha 版本迁移

先停止旧容器并备份原目录，尤其是 `config.yaml`、`sessions/` 和下载目录。不要把包含 API key 的 `config.yaml` 提交到 Git。

将旧文件复制到本项目：

```sh
cp /旧项目/config.yaml .
cp -R /旧项目/sessions/. sessions/
cp -R /旧项目/downloads/. downloads/
```

旧配置将聊天与重试状态放在 `data.yaml` 的 `chat:` 中，新版则使用 `config.yaml` 的 `chats:`。启动脚本会自动合并并迁移这些字段，同时保留 `api_id`、`api_hash`、proxy、`chat_id` 和重试状态，原配置备份会写入 `sessions/config-backups/`。旧版的 `file_path_prefix`、Web Bot 和 rclone 配置不属于上游新版功能，不会被导入。

为确保下载落到挂载目录，请在 `config.yaml` 增加或修改：

```yaml
download_directory: /app/downloads
```

如需 Telegram SOCKS/HTTP 代理，建议使用新版原生配置：

```yaml
proxy:
  scheme: socks5
  hostname: 192.168.1.10
  port: 1080
```

## 启动

首次部署前创建挂载目标（Docker 不会把目录误建成 SQLite 文件）：

```sh
cp .env.example .env
cp config.yaml.example config.yaml
mkdir -p downloads sessions
touch downloads.sqlite3
docker compose up -d --build
```

浏览器访问 `http://服务器地址:5000`。可在 `.env` 中修改 `WEBUI_PORT`。当前上游 Web UI 没有登录认证，请仅在可信内网使用，不要把端口直接暴露到公网；公网访问应在前面增加带认证的反向代理。

查看日志与停止：

```sh
docker compose logs -f
docker compose down
```

## GitHub Actions 自动发布到 Docker Hub

仓库已包含 `.github/workflows/docker-publish.yml`，支持自动构建并推送 `linux/amd64` 和 `linux/arm64` 镜像。

先在 Docker Hub 的 **Account settings → Personal access tokens** 创建一个具有 Read & Write 权限的 Token。然后在 GitHub 仓库的 **Settings → Secrets and variables → Actions → Secrets** 中添加：

- `DOCKERHUB_TOKEN`：Docker Hub 用户 `sky97` 创建的 Token，不要使用登录密码。

当前发布目标固定为 `sky97/telegram_media_downloader_containe`。

以下操作会触发发布：

- 推送到 `master`：发布 `latest` 和 `sha-xxxxxxx`。
- 推送 `v1.2.3` 形式的标签：发布 `1.2.3`、`1.2` 和 SHA 标签。
- 在 GitHub Actions 页面手动执行工作流。

创建版本标签的最短命令：

```sh
git tag v1.0.0
git push origin v1.0.0
```

在 192.168.6.251 的 `.env` 中配置镜像名称：

```env
DOCKER_IMAGE=sky97/telegram_media_downloader_containe:latest
```

然后改为拉取已发布镜像：

```sh
docker compose pull
docker compose up -d
```

## CLI 模式

Web UI 是默认启动方式。只运行一次命令行下载任务：

```sh
docker compose run --rm telegram-media-downloader cli
```

## 升级

保留本地的配置和数据文件，用新的上游代码替换程序文件后重建：

```sh
docker compose build --pull
docker compose up -d
```

## 权限

镜像默认以 UID/GID `1000:1000` 运行。如果挂载目录不可写，在 Linux 宿主机执行：

```sh
sudo chown -R 1000:1000 downloads sessions config.yaml downloads.sqlite3
```
