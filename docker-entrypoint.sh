#!/bin/sh
set -eu
cd /app
if [ ! -f config.yaml ]; then
    cp config.yaml.example config.yaml
    echo "已生成 config.yaml，请填写 Telegram API 配置后重新启动容器。" >&2
fi
python migrate_legacy_config.py config.yaml
if [ "${1:-}" = "webui" ]; then
    shift
    exec python webui.py "$@"
fi
if [ "${1:-}" = "cli" ]; then
    shift
    exec python media_downloader.py "$@"
fi
exec "$@"
