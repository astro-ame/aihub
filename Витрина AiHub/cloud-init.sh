#!/bin/sh
# Cloud-init для деплоя Telegram-бота Ai Hub Market на Ubuntu/Debian.
# После первой загрузки загрузите файлы бота в /opt/aihub-bot и запустите сервис (см. ДЕПЛО.md).

# Обновление и установка Python
apt-get -y update
apt-get -y install python3 python3-pip python3-venv

# Директория для бота
mkdir -p /opt/aihub-bot
chmod 755 /opt/aihub-bot

# Systemd-сервис (включите и запустите после загрузки кода: systemctl enable aihub-bot && systemctl start aihub-bot)
cat > /etc/systemd/system/aihub-bot.service << 'EOF'
[Unit]
Description=Ai Hub Market Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/aihub-bot
ExecStart=/opt/aihub-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
