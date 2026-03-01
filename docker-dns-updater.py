#!/usr/bin/env python3
import json
import subprocess
import sys
import platform
import os

# ------------------------------------------------------------------
# docker-dns-updater.py
# Updates dnsmasq with Docker container hostnames (IPv4 + IPv6)
# Supports: macOS (Silicon/Intel), Ubuntu, Debian
# ------------------------------------------------------------------

def log(msg):
    """Conditional logging based on quiet flag."""
    if "--quiet" not in sys.argv:
        print(msg)

def get_containers(docker_env):
    """Retrieve all running container IDs."""
    try:
        res = subprocess.check_output(["docker", "ps", "-q"], text=True, env=docker_env)
        return res.strip().split()
    except Exception as e:
        log("Docker access error: " + str(e))
        return []

def apply_quad9_profile():
    """Applies Quad9 Secured DNS over TLS profile (macOS only)."""
    if platform.system() == "Darwin":
        log("Applying Quad9 mobileconfig profile via Safari...")
        url = "https://docs.quad9.net/assets/mobileconfig/Quad9_Secured_DNS_over_TLS_20260119.mobileconfig"
        subprocess.run(["open", "-a", "Safari", url])
    else:
        log("Quad9 profile is only supported on macOS. Skipping.")

def main():
    os_type = platform.system()
    docker_env = os.environ.copy()
    
    # 1. Environment Detection & Docker Socket Fix
    if os_type == "Darwin":
        # Root often cannot find the Docker Desktop socket; check common user paths
        user = os.environ.get("SUDO_USER") or os.getlogin()
        socket_path = os.path.join("/Users", user, ".docker/run/docker.sock")
        if os.path.exists(socket_path):
            docker_env["DOCKER_HOST"] = "unix://" + socket_path
        
        # Determine dnsmasq path without calling brew (to avoid root errors)
        if os.path.exists("/opt/homebrew/etc/dnsmasq.d"):
            dns_file = "/opt/homebrew/etc/dnsmasq.d/docker-hosts.conf"
        else:
            dns_file = "/usr/local/etc/dnsmasq.d/docker-hosts.conf"
    else:
        dns_file = "/etc/dnsmasq.d/docker-hosts.conf"

    # 2. Handle Quad9 Profile Flag
    if "--update-profile" in sys.argv:
        apply_quad9_profile()

    # 3. Process Containers
    containers = get_containers(docker_env)
    if not containers:
        log("No running Docker containers detected.")
        # We don't exit so we can still write the TXT record if needed
    
    seen_names = {}
    output_lines = []

    for container_id in containers:
        try:
            inspect_json = subprocess.check_output(["docker", "inspect", container_id], text=True, env=docker_env)
            data = json.loads(inspect_json)[0]
            
            name = data["Name"].lstrip("/")
            networks = data.get("NetworkSettings", {}).get("Networks", {})

            for net_name, net_data in networks.items():
                ip4 = net_data.get("IPAddress")
                ip6 = net_data.get("GlobalIPv6Address")
                
                # Default hostname
                host = name + ".internal"
                
                # Collision handling: if name exists, append network as subdomain
                if name in seen_names:
                    host = name + "." + net_name + ".internal"
                
                seen_names[name] = True

                if ip4 and ip4 != "":
                    output_lines.append("address=/" + host + "/" + ip4)
                if ip6 and ip6 != "":
                    output_lines.append("address=/" + host + "/" + ip6)
        except Exception as e:
            log("Error inspecting container " + container_id + ": " + str(e))
            continue

    # 4. Handle System DNS Fallback Flag
    if "--use-system-dns" in sys.argv:
        log("Adding system/DHCP DNS servers as fallback...")
        try:
            if os_type == "Darwin":
                dns_out = subprocess.check_output(["scutil", "--dns"], text=True)
                for line in dns_out.splitlines():
                    if "nameserver" in line:
                        srv = line.split(":")[1].strip()
                        output_lines.append("server=" + srv)
            else:
                # Linux fallback: try resolvectl then resolv.conf
                if shutil.which("resolvectl"):
                    dns_out = subprocess.check_output(["resolvectl", "status"], text=True)
                    for line in dns_out.splitlines():
                        if "DNS Servers" in line:
                            for s in line.split()[2:]:
                                output_lines.append("server=" + s)
                else:
                    with open("/etc/resolv.conf", "r") as f:
                        for line in f:
                            if line.startswith("nameserver"):
                                output_lines.append("server=" + line.split()[1])
        except Exception:
            pass

    # 5. Self-documenting TXT record
    output_lines.append('txt-record=help.internal,"https://github.com/adamamyl/docker-dns-reso"')

    # 6. Write Configuration & Reload
    new_content = "\n".join(output_lines) + "\n"
    
    # Check if update is actually needed unless --force is passed
    if os.path.exists(dns_file) and "--force" not in sys.argv:
        with open(dns_file, "r") as f:
            if f.read() == new_content:
                log("No changes detected. Skipping reload.")
                return

    try:
        with open(dns_file, "w") as f:
            f.write(new_content)
        
        log("Reloading dnsmasq...")
        if os_type == "Darwin":
            # Kickstart avoids Homebrew root permission issues
            subprocess.run(["launchctl", "kickstart", "-k", "system/homebrew.mxcl.dnsmasq"], check=False)
        else:
            subprocess.run(["systemctl", "reload", "dnsmasq"], check=False)
        
        log("Docker DNS updated successfully.")
    except Exception as e:
        log("Error writing dnsmasq config: " + str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()