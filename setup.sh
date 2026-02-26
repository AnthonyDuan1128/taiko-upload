#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  太鼓自制谱面投稿网站 — Ubuntu 部署脚本
#  用法: sudo bash setup.sh
# ═══════════════════════════════════════════════════════════════════════════

set -e

# ── 颜色 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════╗"
echo "║   🥁  太鼓自制谱面投稿网站 — 部署工具          ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 检查 root ────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ 请使用 sudo 运行此脚本${NC}"
    exit 1
fi

# ── 配置项 ────────────────────────────────────────────────────────────────
APP_DIR="/opt/taiko-submission"
APP_USER="taiko"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="taiko-submission"
DOMAIN=""

# ── 1. 获取管理员信息 ────────────────────────────────────────────────────
echo -e "${YELLOW}── 管理员账户设置 ──${NC}"
read -p "请输入管理员用户名: " ADMIN_USERNAME
while [ -z "$ADMIN_USERNAME" ]; do
    echo -e "${RED}用户名不能为空${NC}"
    read -p "请输入管理员用户名: " ADMIN_USERNAME
done

while true; do
    read -s -p "请输入管理员密码 (至少6位): " ADMIN_PASSWORD
    echo
    if [ ${#ADMIN_PASSWORD} -lt 6 ]; then
        echo -e "${RED}密码至少6位${NC}"
        continue
    fi
    read -s -p "再次确认密码: " ADMIN_PASSWORD2
    echo
    if [ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD2" ]; then
        echo -e "${RED}两次密码不一致，请重新输入${NC}"
        continue
    fi
    break
done

echo ""
read -p "请输入服务器端口 [默认 5000]: " APP_PORT
APP_PORT=${APP_PORT:-5000}

read -p "请输入域名（可留空，用于 Nginx 配置）: " DOMAIN

echo ""
echo -e "${GREEN}✓ 管理员: ${ADMIN_USERNAME}${NC}"
echo -e "${GREEN}✓ 端口: ${APP_PORT}${NC}"
echo -e "${GREEN}✓ 管理面板路径: /1128admin1128${NC}"
echo ""

# ── 2. 安装系统依赖 ──────────────────────────────────────────────────────
echo -e "${CYAN}[1/6] 安装系统依赖...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx git > /dev/null 2>&1
echo -e "${GREEN}✓ 系统依赖安装完成${NC}"

# ── 3. 创建应用用户与目录 ────────────────────────────────────────────────
echo -e "${CYAN}[2/6] 创建应用目录...${NC}"
id -u $APP_USER > /dev/null 2>&1 || useradd -r -s /bin/false $APP_USER
mkdir -p $APP_DIR
cp -r "$(dirname "$(readlink -f "$0")")"/* $APP_DIR/ 2>/dev/null || true
cp -r "$(dirname "$(readlink -f "$0")")"/.* $APP_DIR/ 2>/dev/null || true
chown -R $APP_USER:$APP_USER $APP_DIR
echo -e "${GREEN}✓ 应用目录: $APP_DIR${NC}"

# ── 4. Python 虚拟环境 ──────────────────────────────────────────────────
echo -e "${CYAN}[3/6] 配置 Python 虚拟环境...${NC}"
python3 -m venv $VENV_DIR
$VENV_DIR/bin/pip install --quiet --upgrade pip
$VENV_DIR/bin/pip install --quiet flask flask-sqlalchemy flask-login flask-wtf werkzeug requests wtforms email-validator gunicorn
echo -e "${GREEN}✓ Python 依赖安装完成${NC}"

# ── 5. 生成环境变量配置文件 ──────────────────────────────────────────────
echo -e "${CYAN}[4/6] 生成配置文件...${NC}"
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

cat > $APP_DIR/.env << EOF
# 太鼓投稿网站 — 环境变量配置
SECRET_KEY=${SECRET_KEY}
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
FLASK_ENV=production
APP_PORT=${APP_PORT}
EOF

chmod 600 $APP_DIR/.env
chown $APP_USER:$APP_USER $APP_DIR/.env
echo -e "${GREEN}✓ 配置文件已生成: $APP_DIR/.env${NC}"

# ── 6. 创建 systemd 服务 ─────────────────────────────────────────────────
echo -e "${CYAN}[5/6] 配置 systemd 服务...${NC}"

cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=太鼓自制谱面投稿网站
After=network.target

[Service]
Type=notify
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/gunicorn --workers 4 --bind 127.0.0.1:${APP_PORT} --timeout 120 app:app
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 确保 uploads 目录存在
mkdir -p $APP_DIR/uploads
chown -R $APP_USER:$APP_USER $APP_DIR

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl start ${SERVICE_NAME}
echo -e "${GREEN}✓ 服务已启动${NC}"

# ── 7. Nginx 反向代理 (可选) ─────────────────────────────────────────────
echo -e "${CYAN}[6/6] 配置 Nginx 反向代理...${NC}"

if [ -n "$DOMAIN" ]; then
    NGINX_SERVER_NAME="server_name ${DOMAIN};"
else
    NGINX_SERVER_NAME="server_name _;"
fi

cat > /etc/nginx/sites-available/${SERVICE_NAME} << EOF
server {
    listen 80;
    ${NGINX_SERVER_NAME}

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    location /static/ {
        alias ${APP_DIR}/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

ln -sf /etc/nginx/sites-available/${SERVICE_NAME} /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t && systemctl reload nginx
echo -e "${GREEN}✓ Nginx 已配置${NC}"

# ── 完成 ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   🎉  部署完成！                                ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  管理员用户名: ${GREEN}${ADMIN_USERNAME}${NC}"
echo -e "${CYAN}║${NC}  管理面板地址: ${GREEN}http://${DOMAIN:-localhost}/1128admin1128${NC}"
echo -e "${CYAN}║${NC}  网站地址:     ${GREEN}http://${DOMAIN:-localhost}${NC}"
echo -e "${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  ${YELLOW}管理命令:${NC}"
echo -e "${CYAN}║${NC}    查看状态: systemctl status ${SERVICE_NAME}"
echo -e "${CYAN}║${NC}    查看日志: journalctl -u ${SERVICE_NAME} -f"
echo -e "${CYAN}║${NC}    重启服务: systemctl restart ${SERVICE_NAME}"
echo -e "${CYAN}║${NC}    停止服务: systemctl stop ${SERVICE_NAME}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
