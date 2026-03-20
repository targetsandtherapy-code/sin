"""远程部署 CRM 到腾讯云服务器"""
import paramiko
import os
import sys

HOST = "82.156.105.169"
USER = "root"
PASSWORD = "hpcls1268A@"
REMOTE_DIR = "/opt/scrm"
LOCAL_DIR = os.path.dirname(__file__)

DEPLOY_FILES = [
    "main.py", "database.py", "requirements.txt",
    "init_data.json", "dealer_models.json",
]
TEMPLATE_FILES = [
    "templates/base.html", "templates/dashboard.html", "templates/leads.html",
    "templates/lead_form.html", "templates/push_log.html", "templates/settings.html",
    "templates/login.html", "templates/admin_logs.html", "templates/admin_users.html",
    "templates/dealers.html", "templates/dealer_form.html",
    "templates/car_models.html", "templates/car_model_form.html",
]
STATIC_FILES = ["static/style.css"]


def ssh_exec(ssh, cmd, show=True):
    if show:
        print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if show and out.strip():
        print(f"    {out.strip()}")
    if err.strip() and "WARNING" not in err:
        print(f"    [stderr] {err.strip()}")
    return out, err


def main():
    print(f"连接 {HOST} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key_file = r"D:\api对接\hpc.pem"
    pkey = paramiko.RSAKey.from_private_key_file(key_file)
    ssh.connect(HOST, username=USER, pkey=pkey, timeout=15)
    print("连接成功\n")

    sftp = ssh.open_sftp()

    print("1. 创建目录")
    ssh_exec(ssh, f"mkdir -p {REMOTE_DIR}/templates {REMOTE_DIR}/static")

    print("\n2. 检查 Python")
    out, _ = ssh_exec(ssh, "python3 --version 2>&1")
    if "Python 3" not in out:
        print("  安装 Python3...")
        ssh_exec(ssh, "apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv 2>&1 | tail -3")

    print("\n3. 上传文件")
    for f in DEPLOY_FILES:
        local = os.path.join(LOCAL_DIR, f)
        remote = f"{REMOTE_DIR}/{f}"
        print(f"  {f}")
        sftp.put(local, remote)

    for f in TEMPLATE_FILES + STATIC_FILES:
        local = os.path.join(LOCAL_DIR, f)
        remote = f"{REMOTE_DIR}/{f}"
        if os.path.exists(local):
            print(f"  {f}")
            sftp.put(local, remote)

    print("\n4. 创建虚拟环境 & 安装依赖")
    ssh_exec(ssh, f"cd {REMOTE_DIR} && python3 -m venv venv 2>&1 | tail -3")
    ssh_exec(ssh, f"cd {REMOTE_DIR} && venv/bin/pip install -r requirements.txt 2>&1 | tail -5")

    print("\n5. 创建 systemd 服务")
    service = f"""[Unit]
Description=SCRM Leads CRM
After=network.target

[Service]
Type=simple
WorkingDirectory={REMOTE_DIR}
ExecStart={REMOTE_DIR}/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    with sftp.open("/etc/systemd/system/scrm.service", "w") as f:
        f.write(service)

    ssh_exec(ssh, "systemctl daemon-reload")
    ssh_exec(ssh, "systemctl enable scrm")
    ssh_exec(ssh, "systemctl restart scrm")

    print("\n6. 检查服务状态")
    import time
    time.sleep(3)
    ssh_exec(ssh, "systemctl status scrm --no-pager -l | head -15")

    print("\n7. 配置 Nginx 反向代理")
    nginx_conf = """server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
"""
    with sftp.open("/www/server/panel/vhost/nginx/scrm.conf", "w") as f:
        f.write(nginx_conf)
    ssh_exec(ssh, "nginx -t 2>&1")
    ssh_exec(ssh, "nginx -s reload 2>&1 || systemctl restart nginx 2>&1")

    print("\n8. 开放防火墙端口")
    ssh_exec(ssh, "firewall-cmd --zone=public --add-port=8000/tcp --permanent 2>&1 || true")
    ssh_exec(ssh, "firewall-cmd --reload 2>&1 || true")

    print("\n" + "=" * 50)
    print("部署完成！")
    print(f"  访问地址: http://{HOST}")
    print(f"  备用地址: http://{HOST}:8000")
    print(f"  Webhook:  http://{HOST}/api/webhook/kuaishou")
    print(f"  管理员:   admin / admin123")
    print("=" * 50)

    sftp.close()
    ssh.close()


if __name__ == "__main__":
    main()
