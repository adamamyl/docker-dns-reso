#!/usr/bin/env python3
import os
import sys
import platform
import subprocess
import shutil
import argparse
import random

# ------------------------------------------------------------------
# Universal Installer for docker-dns (Python Edition)
# RESTORED: Quad9, Collision Logic, CLI Flags, System DNS Fallback
# ------------------------------------------------------------------

UPDATER_SCRIPT_CONTENT = r'''#!/usr/bin/env python3
import json
import subprocess
import sys
import platform
import os

def get_containers(docker_env):
    try:
        res = subprocess.check_output(["docker", "ps", "-q"], text=True, env=docker_env)
        return res.strip().split()
    except Exception:
        return []

def main():
    os_type = platform.system()
    docker_env = os.environ.copy()
    
    # 1. FIX: Access Docker Socket as root
    if os_type == "Darwin":
        user = os.environ.get("SUDO_USER") or os.getlogin()
        socket_path = os.path.join("/Users", user, ".docker/run/docker.sock")
        if os.path.exists(socket_path):
            docker_env["DOCKER_HOST"] = "unix://" + socket_path

    # 2. RESTORE: Path Detection
    dns_file = "/etc/dnsmasq.d/docker-hosts.conf"
    if os_type == "Darwin":
        if os.path.exists("/opt/homebrew/etc/dnsmasq.d"):
            dns_file = "/opt/homebrew/etc/dnsmasq.d/docker-hosts.conf"
        else:
            dns_file = "/usr/local/etc/dnsmasq.d/docker-hosts.conf"

    # 3. RESTORE: Quad9 Profile Logic
    if "--update-profile" in sys.argv and os_type == "Darwin":
        url = "https://docs.quad9.net/assets/mobileconfig/Quad9_Secured_DNS_over_TLS_20260119.mobileconfig"
        subprocess.run(["open", "-a", "Safari", url])

    # 4. RESTORE: Collision Safe Hostnames
    containers = get_containers(docker_env)
    seen_names = {}
    output_lines = []

    for container_id in containers:
        try:
            inspect_json = subprocess.check_output(["docker", "inspect", container_id], text=True, env=docker_env)
            data = json.loads(inspect_json)[0]
            name = data["Name"].lstrip("/")
            networks = data["NetworkSettings"]["Networks"]

            for net_name, net_data in networks.items():
                ip4 = net_data.get("IPAddress")
                ip6 = net_data.get("GlobalIPv6Address")
                
                host = name + ".internal"
                if name in seen_names:
                    host = name + "." + net_name + ".internal"
                
                seen_names[name] = True
                if ip4: output_lines.append("address=/" + host + "/" + ip4)
                if ip6: output_lines.append("address=/" + host + "/" + ip6)
        except: continue

    # 5. RESTORE: System DNS Fallback
    if "--use-system-dns" in sys.argv:
        try:
            if os_type == "Darwin":
                dns_out = subprocess.check_output(["scutil", "--dns"], text=True)
                for line in dns_out.splitlines():
                    if "nameserver" in line:
                        srv = line.split(":")[1].strip()
                        output_lines.append("server=" + srv)
            else:
                with open("/etc/resolv.conf", "r") as f:
                    for line in f:
                        if line.startswith("nameserver"):
                            output_lines.append("server=" + line.split()[1])
        except: pass

    output_lines.append('txt-record=help.internal,"https://github.com/adamamyl/docker-dns-reso"')
    new_content = "\n".join(output_lines) + "\n"
    
    with open(dns_file, "w") as f:
        f.write(new_content)

    # 6. RESTORE: Force Reload
    if os_type == "Darwin":
        subprocess.run(["launchctl", "kickstart", "-k", "system/homebrew.mxcl.dnsmasq"], check=False)
    else:
        subprocess.run(["systemctl", "reload", "dnsmasq"], check=False)

if __name__ == "__main__":
    main()
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-profile", action="store_true")
    parser.add_argument("--use-system-dns", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("Error: Must run as root")
        sys.exit(1)

    repo_root = os.path.dirname(os.path.abspath(__file__))
    os_type = platform.system()

    # 1. Deploy Files
    updater_dst = "/usr/local/bin/docker-dns-updater.py"
    with open(updater_dst, "w") as f:
        f.write(UPDATER_SCRIPT_CONTENT)
    os.chmod(updater_dst, 0o755)

    if os_type == "Darwin":
        # Ensure macOS Resolver directory exists
        if not os.path.exists("/etc/resolver"):
            os.makedirs("/etc/resolver")
        
        # Install the .internal resolver
        res_src = os.path.join(repo_root, "macos", "resolver", "docker.internal")
        if os.path.exists(res_src):
            shutil.copy(res_src, "/etc/resolver/internal")
            os.chmod("/etc/resolver/internal", 0o644)

        # Fix LaunchDaemon
        plist_src = os.path.join(repo_root, "macos", "docker-dns-updater.plist")
        plist_dst = "/Library/LaunchDaemons/com.docker.dnsupdater.plist"
        if os.path.exists(plist_src):
            shutil.copy(plist_src, plist_dst)
            # Re-load to fix "Error 5" session issues
            subprocess.run(["launchctl", "unload", "-w", plist_dst], capture_output=True)
            subprocess.run(["launchctl", "load", "-w", plist_dst])

    # 2. Run Initial Trigger
    flags = ["python3", updater_dst]
    if args.update_profile: flags.append("--update-profile")
    if args.use_system_dns: flags.append("--use-system-dns")
    if args.force: flags.append("--force")
    
    subprocess.run(flags)
    print("Installation complete.")

if __name__ == "__main__":
    main()