#!/usr/bin/env python3
import os
import sys
import platform
import subprocess
import shutil
import argparse

# ------------------------------------------------------------------
# Universal Installer for docker-dns
# ------------------------------------------------------------------


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

    updater_src = os.path.join(repo_root, "docker-dns-updater.py")
    updater_dst = "/usr/local/bin/docker-dns-updater.py"
    shutil.copy(updater_src, updater_dst)
    os.chmod(updater_dst, 0o755)

    if os_type == "Darwin":
        os.makedirs("/etc/resolver", exist_ok=True)

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

    flags = ["python3", updater_dst]
    if args.update_profile:
        flags.append("--update-profile")
    if args.use_system_dns:
        flags.append("--use-system-dns")
    if args.force:
        flags.append("--force")

    subprocess.run(flags)
    print("Installation complete.")


if __name__ == "__main__":
    main()
