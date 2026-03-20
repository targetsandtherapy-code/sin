"""通过宝塔面板 CLI 安装 Nginx"""
import paramiko
import time

HOST = "82.156.105.169"
USER = "root"
KEY_FILE = r"D:\api对接\hpc.pem"


def ssh_exec(ssh, cmd, timeout=300):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip():
        for line in out.strip().split('\n')[-8:]:
            print(f"    {line}")
    if err.strip() and "WARNING" not in err:
        for line in err.strip().split('\n')[-3:]:
            print(f"    [!] {line}")
    return out, err


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.RSAKey.from_private_key_file(KEY_FILE)
    ssh.connect(HOST, username=USER, pkey=pkey, timeout=15)
    print("连接成功\n")

    print("1. 查看宝塔面板信息")
    ssh_exec(ssh, "bt default 2>/dev/null || /etc/init.d/bt default 2>/dev/null")

    print("\n2. 用宝塔 CLI 安装 Nginx")
    ssh_exec(ssh, "bt 14 2>/dev/null; echo 'bt cmd done'", timeout=600)

    print("\n3. 尝试直接安装 Nginx (编译安装)")
    out, _ = ssh_exec(ssh, "which nginx 2>/dev/null && echo HAS_NGINX")
    if "HAS_NGINX" not in out:
        print("  宝塔未安装成功，尝试 dnf 安装...")
        ssh_exec(ssh, "dnf module reset nginx -y 2>&1 | tail -3", timeout=60)
        ssh_exec(ssh, "dnf module enable nginx:1.24 -y 2>&1 | tail -3", timeout=60)
        ssh_exec(ssh, "dnf install -y nginx 2>&1 | tail -5", timeout=180)

    print("\n4. 检查 Nginx")
    out, _ = ssh_exec(ssh, "which nginx 2>/dev/null && nginx -v 2>&1")

    if "nginx" in out.lower():
        print("\n  Nginx 已安装！配置反向代理...")
        sftp = ssh.open_sftp()
        ssh_exec(ssh, "mkdir -p /etc/nginx/conf.d")

        nginx_conf = """server {
    listen 80;
    server_name _;
    client_max_body_size 20M;

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
        with sftp.open("/etc/nginx/conf.d/scrm.conf", "w") as f:
            f.write(nginx_conf)
        ssh_exec(ssh, "rm -f /etc/nginx/conf.d/default.conf 2>/dev/null; nginx -t 2>&1")
        ssh_exec(ssh, "systemctl enable nginx && systemctl restart nginx")
        time.sleep(2)
        ssh_exec(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/login && echo ' - 80端口OK'")
        sftp.close()
    else:
        print("\n  Nginx 安装失败，直接用 8000 端口访问即可")

    print("\n5. 确认 CRM 服务")
    ssh_exec(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/login && echo ' - CRM OK'")

    print("\n" + "=" * 50)
    print("  http://82.156.105.169:8000  (CRM直连)")
    print("  管理员: admin / admin123")
    print("  腾讯云控制台防火墙需放行: TCP 80, TCP 8000")
    print("=" * 50)

    ssh.close()


if __name__ == "__main__":
    main()
