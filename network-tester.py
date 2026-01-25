#!/usr/bin/env python3
import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from deepdiff import DeepDiff

# -----------------------------
# CONFIG
# -----------------------------
SNAPSHOT_ROOT = Path("./snapshots")
SERVICES = ["dnsmasq", "docker", "tailscale"]
CHUNK_LINES = 500  # lines per clipboard chunk
SCENARIOS = [
    {"name": "pom", "services": []},
    {"name": "pom+dnsmasq", "services": ["dnsmasq"]},
    {"name": "pom+docker", "services": ["docker"]},
    {"name": "pom+docker+dnsmasq", "services": ["docker", "dnsmasq"]},
    {"name": "pom+docker+tailscale", "services": ["docker", "tailscale"]},
]

# -----------------------------
# UTILITIES
# -----------------------------
def run_cmd(cmd: List[str], check=True, capture=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)

def prompt_user(message: str) -> bool:
    resp = input(f"{message} (y/n): ").lower()
    return resp.startswith("y")

def log(level: str, msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{level}[{ts}] {msg}")

def info(msg: str):
    log("🟢[INFO] ", msg)

def warn(msg: str):
    log("🟡[WARN] ", msg)

def ok(msg: str):
    log("✅[OK]  ", msg)

def error(msg: str):
    log("🔴[ERROR] ", msg)

# -----------------------------
# PRE-FLIGHT
# -----------------------------
def docker_preflight() -> bool:
    """Ensure Docker daemon is running. Launch Docker Desktop if not."""
    try:
        run_cmd(["docker", "info"])
        info("Docker daemon running")
        return True
    except subprocess.CalledProcessError:
        warn("Docker daemon not running. Attempting to open Docker Desktop...")
        run_cmd(["open", "/Applications/Docker.app"])
        time.sleep(45)
        try:
            run_cmd(["docker", "info"])
            info("Docker daemon running after launch")
            return True
        except subprocess.CalledProcessError:
            error("Docker still not running. Skipping Docker scenario.")
            return False

def check_dnsmasq_port():
    """Check if port 53 is free, kill dnsmasq if necessary."""
    result = run_cmd(["lsof", "-i", ":53"], check=False)
    if result.stdout.strip():
        warn("Port 53 in use, killing existing dnsmasq processes")
        run_cmd(["sudo", "pkill", "dnsmasq"], check=False)
        time.sleep(1)
    else:
        info("Port 53 free")

# -----------------------------
# SNAPSHOT SYSTEM
# -----------------------------
def snapshot_dir(scenario: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SNAPSHOT_ROOT / f"run-{ts}" / scenario
    path.mkdir(parents=True, exist_ok=True)
    return path

def capture_snapshot(label: str, scenario: str) -> Path:
    path = snapshot_dir(scenario)
    snap_file = path / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{label}.json"
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "label": label,
        "scenario": scenario,
        "network": {},
        "services": {},
    }
    # Capture DNS
    try:
        resolv = run_cmd(["cat", "/etc/resolv.conf"]).stdout.strip()
        snapshot["network"]["resolv_conf"] = resolv.splitlines()
    except Exception as e:
        warn(f"Could not capture /etc/resolv.conf: {e}")

    try:
        scutil = run_cmd(["scutil", "--dns"]).stdout.strip()
        snapshot["network"]["scutil_dns"] = scutil.splitlines()
    except Exception as e:
        warn(f"Could not capture scutil --dns: {e}")

    # Capture services status
    for svc in SERVICES:
        snapshot["services"][svc] = service_status(svc)

    with open(snap_file, "w") as f:
        json.dump(snapshot, f, indent=2)

    info(f"Snapshot saved: {snap_file}")
    copy_to_clipboard(snap_file)
    return snap_file

def diff_snapshots(before: Path, after: Path) -> Path:
    with open(before) as f:
        bdata = json.load(f)
    with open(after) as f:
        adata = json.load(f)
    diff = DeepDiff(bdata, adata, ignore_order=True).to_dict()
    diff_file = before.parent / "diff.json"
    with open(diff_file, "w") as f:
        json.dump(diff, f, indent=2)
    info(f"Diff saved: {diff_file}")
    copy_to_clipboard(diff_file)
    return diff_file

def copy_to_clipboard(file_path: Path):
    """Split large files into chunks and copy first to pbcopy, prompt for next."""
    with open(file_path) as f:
        lines = f.readlines()
    total_chunks = (len(lines) + CHUNK_LINES - 1) // CHUNK_LINES
    for i in range(total_chunks):
        chunk = lines[i*CHUNK_LINES:(i+1)*CHUNK_LINES]
        subprocess.run("pbcopy", input="".join(chunk), text=True)
        info(f"[INFO] Chunk {i+1}/{total_chunks} copied to clipboard")
        if i < total_chunks - 1:
            input("Press Enter to send the next chunk...")

# -----------------------------
# SERVICE MODULES
# -----------------------------
def service_status(service: str) -> str:
    if service == "dnsmasq":
        result = run_cmd(["pgrep", "dnsmasq"], check=False)
        return "running" if result.stdout.strip() else "stopped"
    elif service == "docker":
        try:
            run_cmd(["docker", "info"])
            return "running"
        except:
            return "stopped"
    elif service == "tailscale":
        result = run_cmd(["pgrep", "-f", "tailscaled"], check=False)
        return "running" if result.stdout.strip() else "stopped"
    return "unknown"

def start_dnsmasq():
    cfg = "/tmp/dnsmasq-test.conf"
    with open(cfg, "w") as f:
        f.write("listen-address=127.0.0.1\nno-resolv\nserver=1.1.1.1\n")
    run_cmd(["sudo", "dnsmasq", "-C", cfg])
    ok("dnsmasq started")

def stop_dnsmasq():
    run_cmd(["sudo", "pkill", "dnsmasq"], check=False)
    ok("dnsmasq stopped")

def run_ps_module():
    try:
        ps_out = run_cmd(["ps", "-e", "-o", "pid,comm"]).stdout.strip().splitlines()
        info(f"Captured {len(ps_out)} processes")
    except Exception as e:
        warn(f"Failed to capture ps: {e}")

def run_dnsmasq_module(scenario: str):
    check_dnsmasq_port()
    before = capture_snapshot("before-dnsmasq", scenario)
    stop_dnsmasq()
    capture_snapshot("after-stop", scenario)
    start_dnsmasq()
    after = capture_snapshot("after-start", scenario)
    diff_snapshots(before, after)
    stop_dnsmasq()

def run_docker_module(scenario: str):
    if not docker_preflight():
        return
    before = capture_snapshot("before-docker", scenario)
    try:
        test_image = "alpine:3.18"
        timestamp = datetime.now().strftime("%s")
        container_name = f"nettest_{timestamp}"
        run_cmd(["docker", "pull", test_image])
        run_cmd(["docker", "run", "--rm", "--name", container_name, test_image,
                 "sh", "-c", "echo Hello; nslookup google.com"])
        ok("Docker container test complete")
    except Exception as e:
        warn(f"Docker test failed: {e}")
    after = capture_snapshot("after-docker", scenario)
    diff_snapshots(before, after)

def run_tailscale_module(scenario: str):
    info("Tailscale module placeholder — manual start required")

# -----------------------------
# SCENARIO RUNNER
# -----------------------------
def run_scenario(scenario: Dict):
    info(f"=== Running scenario: {scenario['name']} ===")
    run_ps_module()  # baseline snapshot after preflight
    for svc in scenario["services"]:
        if svc == "dnsmasq":
            run_dnsmasq_module(scenario["name"])
        elif svc == "docker":
            run_docker_module(scenario["name"])
        elif svc == "tailscale":
            run_tailscale_module(scenario["name"])
    info(f"=== Scenario '{scenario['name']}' complete ===\n")

# -----------------------------
# MAIN
# -----------------------------
def main():
    info("You are going to receive multiple posts of logs. Do not take action until all chunks are sent.")
    for scenario in SCENARIOS:
        run_scenario(scenario)
    ok("All scenarios complete")

if __name__ == "__main__":
    main()
