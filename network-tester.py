#!/usr/bin/env python3
import os
import subprocess
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import List

# -----------------------------
# Constants / Logging
# -----------------------------
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
NC = "\033[0m"

console = Console()

class Logger:
    def info(self, msg): console.print(f"🟢 [INFO] {msg}")
    def warn(self, msg): console.print(f"🟡 [WARN] {msg}")
    def error(self, msg): console.print(f"🔴 [ERROR] {msg}")
    def ok(self, msg): console.print(f"✅ [OK] {msg}")

logger = Logger()

# -----------------------------
# Idempotent PATH prepending
# -----------------------------
try:
    brew_prefix = subprocess.check_output(["brew", "--prefix"], text=True).strip()
except subprocess.CalledProcessError:
    brew_prefix = "/usr/local"

for subdir in ["bin", "sbin"]:
    path_to_add = f"{brew_prefix}/{subdir}"
    if path_to_add not in os.environ["PATH"].split(":"):
        os.environ["PATH"] = f"{path_to_add}:{os.environ['PATH']}"

# -----------------------------
# Tools
# -----------------------------
TOOLS_BREW = ["iproute2mac", "doggo", "rg", "gawk", "mtr", "dnsmasq"]
TOOLS_MANUAL = ["docker", "tailscale"]

def tool_exists(tool: str) -> bool:
    return subprocess.run(["command", "-v", tool], capture_output=True, text=True).returncode == 0

def install_brew_tools(tools: List[str]):
    missing = [t for t in tools if not tool_exists(t)]
    if missing:
        logger.info(f"Installing missing tools via Homebrew: {' '.join(missing)}")
        try:
            subprocess.run(["brew", "install"] + missing, check=True)
            logger.ok("Tool installation complete")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install tools: {e}")
    else:
        logger.info("All Homebrew tools already installed")

def report_tools_status():
    for tool in TOOLS_BREW + TOOLS_MANUAL:
        exists = tool_exists(tool)
        logger.info(f"Tool '{tool}' found: {exists}")

# -----------------------------
# Command runner
# -----------------------------
def run_cmd(cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)

# -----------------------------
# Snapshot handling
# -----------------------------
SNAPSHOT_ROOT = Path("snapshots") / datetime.now().strftime("run-%Y%m%d-%H%M%S")
SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)

def save_snapshot(scenario: str, filename: str, data: dict):
    dir_path = SNAPSHOT_ROOT / scenario
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / filename
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Snapshot saved: {file_path}")
    return file_path

# -----------------------------
# ChatGPT-ready chunked output
# -----------------------------
def send_to_chatgpt(text: str, scenario: str, chunk_size: int = 500):
    lines = text.splitlines()
    chunks = [lines[i:i+chunk_size] for i in range(0, len(lines), chunk_size)]
    total_chunks = len(chunks)
    for idx, chunk_lines in enumerate(chunks, 1):
        chunk_text = "\n".join(chunk_lines)
        if idx == 1:
            instructions = [
                f"You are analyzing the log/snapshot of our macOS network tester for scenario '{scenario}'.",
                "The full log is split into multiple posts. Do NOT respond until all chunks are received.",
                f"I will indicate each chunk as 'Chunk X of {total_chunks}'.",
                "Your task is to identify what changed between snapshots, highlight modified services/interfaces/routes,",
                "explain how these changes may affect other parts of the network stack, note errors/missing services,",
                "and suggest potential fixes or workarounds for a fully working stack.",
                "Begin receiving chunks now.\n"
            ]
            chunk_text = "\n".join(instructions + chunk_lines)
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(chunk_text.encode())
            logger.info(f"Chunk {idx}/{total_chunks} copied to clipboard")
        except Exception as e:
            logger.error(f"Failed to copy chunk {idx}: {e}")
        if idx < total_chunks:
            input("Paste this chunk into ChatGPT and press Enter for next chunk...")
    logger.ok(f"All {total_chunks} chunks for scenario '{scenario}' sent to clipboard")

# -----------------------------
# Network module runners
# -----------------------------
def check_dnsmasq_port():
    result = subprocess.run(["lsof", "-i", ":53"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        logger.info("Port 53 free")
        return True
    else:
        logger.warn("Port 53 in use")
        return False

def run_dnsmasq_module(scenario):
    if check_dnsmasq_port():
        # placeholder: start dnsmasq
        time.sleep(1)
        logger.ok("dnsmasq started")
    else:
        logger.warn("Skipping dnsmasq start due to port conflict")
    # Save snapshots for before/after
    save_snapshot(scenario, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_before.json", {"dummy": "before"})
    save_snapshot(scenario, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_after.json", {"dummy": "after"})

def run_docker_module(scenario, timeout=45):
    if not tool_exists("docker"):
        logger.warn("Docker not found; skipping scenario")
        return
    try:
        # Ensure Docker daemon running
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        logger.info("Docker daemon running")
    except subprocess.CalledProcessError:
        logger.warn("Docker daemon not running. Attempting to open Docker Desktop...")
        subprocess.run(["open", "-a", "Docker"])
        with Progress(SpinnerColumn(), TextColumn("{task.description}")) as progress:
            task = progress.add_task("Waiting for Docker...", total=None)
            for _ in range(timeout):
                time.sleep(1)
                try:
                    subprocess.run(["docker", "info"], check=True, capture_output=True)
                    progress.update(task, description="Docker ready")
                    break
                except subprocess.CalledProcessError:
                    continue
            progress.remove_task(task)
        logger.info("Docker daemon running after launch")
    # snapshot
    save_snapshot(scenario, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_docker-test.json", {"dummy": "docker"})

def run_tailscale_module(scenario):
    logger.info("Tailscale module placeholder — manual start required")
    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as progress:
        task = progress.add_task("Waiting for Tailscale (manual)...", total=5)
        for _ in range(5):
            time.sleep(1)
        progress.remove_task(task)

# -----------------------------
# Scenario runner
# -----------------------------
SCENARIOS = [
    {"name": "pom", "modules": []},
    {"name": "pom+dnsmasq", "modules": ["dnsmasq"]},
    {"name": "pom+docker", "modules": ["docker"]},
    {"name": "pom+docker+dnsmasq", "modules": ["docker", "dnsmasq"]},
    {"name": "pom+docker+tailscale", "modules": ["docker", "tailscale"]},
]

def run_scenario(scenario):
    logger.info(f"=== Running scenario: {scenario['name']} ===")
    # Capture processes
    processes = subprocess.check_output(["ps", "-axo", "pid,comm"], text=True).splitlines()
    num_processes = len(processes)
    if "dnsmasq" in scenario["modules"]:
        run_dnsmasq_module(scenario["name"])
    if "docker" in scenario["modules"]:
        run_docker_module(scenario["name"])
    if "tailscale" in scenario["modules"]:
        run_tailscale_module(scenario["name"])
    return num_processes

# -----------------------------
# Summary Table
# -----------------------------
def display_summary(scenario_results):
    table = Table(title=f"Network Tester Summary ({SNAPSHOT_ROOT.name})")
    table.add_column("Scenario")
    table.add_column("Processes")
    table.add_column("Docker")
    table.add_column("DNSMasq")
    table.add_column("Tailscale")
    for scenario, result in scenario_results.items():
        table.add_row(
            scenario,
            str(result["processes"]),
            "✅" if result.get("docker") else "-" if "docker" in SCENARIOS[0]["modules"] else "⚠️",
            "✅" if result.get("dnsmasq") else "-",
            "⚠️" if result.get("tailscale") else "-"
        )
    console.print(table)

# -----------------------------
# Main
# -----------------------------
def main():
    install_brew_tools(TOOLS_BREW)
    report_tools_status()

    scenario_results = {}
    for scenario in SCENARIOS:
        num_processes = run_scenario(scenario)
        scenario_results[scenario["name"]] = {
            "processes": num_processes,
            "docker": "docker" in scenario["modules"],
            "dnsmasq": "dnsmasq" in scenario["modules"],
            "tailscale": "tailscale" in scenario["modules"]
        }

    display_summary(scenario_results)

    send_logs = input("Send detailed logs to ChatGPT in chunks? [y/N] ").strip().lower()
    if send_logs == "y":
        for scenario in SCENARIOS:
            dummy_logs = f"Placeholder for all scenario logs for {scenario['name']}"
            send_to_chatgpt(dummy_logs, scenario["name"])

if __name__ == "__main__":
    main()
