"""远程安装配置 Nginx"""
import paramiko
import time

HOST = "82.156.105.169"
USER = "root"
KEY_FILE = r"D:\api对接\hpc.pem"


def ssh_exec(ssh, cmd, timeout=120):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip():
        for line in out.strip().split('\n')[-5:]:
            print(f"    {line}")
    if err.strip() and "WARNING" not in err and "DEPRECATION" not in err:
        for line in err.strip().split('\n')[-3:]:
            print(f"    [!] {line}")
    return out, err


def main():
    print(f"连接 {HOST} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.RSAKey.from_private_key_file(KEY_FILE)
    ssh.connect(HOST, username=USER, pkey=pkey, timeout=15)
    print("连接成功\n")

    print("1. 安装 Nginx")
    out, _ = ssh_exec(ssh, "which nginx 2>/dev/null && echo 'ALREADY_INSTALLED'")
    if "ALREADY_INSTALLED" not in out:
        print("  添加 Nginx 仓库...")
        ssh_exec(ssh, """cat > /etc/yum.repos.d/nginx.repo << 'REPO'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/centos/9/$basearch/
gpgcheck=0
enabled=1
REPO""")
        ssh_exec(ssh, "yum install -y nginx 2>&1 | tail -5", timeout=180)

    print("\n2. 配置 Nginx 反向代理")
    ssh_exec(ssh, "mkdir -p /etc/nginx/conf.d")
    nginx_conf = r"""server {
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
        proxy_connect_timeout 10;
    }
}
"""
    sftp = ssh.open_sftp()
    with sftp.open("/etc/nginx/conf.d/scrm.conf", "w") as f:
        f.write(nginx_conf)

    ssh_exec(ssh, "rm -f /etc/nginx/conf.d/default.conf 2>/dev/null; echo done")

    print("\n3. 测试 Nginx 配置")
    ssh_exec(ssh, "nginx -t 2>&1")

    print("\n4. 启动 Nginx")
    ssh_exec(ssh, "systemctl enable nginx && systemctl restart nginx")

    print("\n5. 检查 Nginx 状态")
    time.sleep(2)
    ssh_exec(ssh, "systemctl status nginx --no-pager | head -10")

    print("\n6. 配置防火墙（OS层面）")
    ssh_exec(ssh, "systemctl start firewalld 2>/dev/null; firewall-cmd --permanent --add-service=http 2>/dev/null; firewall-cmd --permanent --add-port=8000/tcp 2>/dev/null; firewall-cmd --reload 2>/dev/null; echo 'firewall done'")
    ssh_exec(ssh, "iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null; iptables -I INPUT -p tcp --dport 8000 -j ACCEPT 2>/dev/null; echo 'iptables done'")

    print("\n7. 验证服务")
    ssh_exec(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/login && echo ' - 8000端口OK'")
    ssh_exec(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/login && echo ' - 80端口Nginx代理OK'")

    print("\n" + "=" * 50)
    print("全部完成！")
    print(f"  http://82.156.105.169      (Nginx 80端口)")
    print(f"  http://82.156.105.169:8000 (直连)")
    print()
    print("重要：还需在腾讯云控制台放行端口：")
    print("  轻量应用服务器 → 防火墙 → 添加规则")
    print("  - TCP 80  (HTTP)")
    print("  - TCP 8000 (备用)")
    print("=" * 50)

    sftp.close()
    ssh.close()


if __name__ == "__main__":
    main()
