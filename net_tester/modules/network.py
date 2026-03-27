# modules/network.py
"""
Minimal network capture wrapper for orchestrator.
Delegates actual work to capture.py while preserving flags and logging.
"""

from typing import Dict, Any, Optional
from modules import capture
import modules.logger as logmod


def capture_network_state(log: Optional[logmod.Logger] = None, dry_run: bool = False) -> Dict[str, Any]:
    """
    Capture network state for orchestrator:
    - interfaces, addresses, routes
    - DNS summary + resolv.conf
    - sample doggo lookup
    - processes (NDJSON)

    Failures are tolerated; missing binaries or permissions won't abort.
    """
    log = log or logmod.log

    try:
        state = capture.capture_network_state(dry_run=dry_run)
        log.debug("Network state captured successfully")
    except Exception as e:
        log.warn(f"Failed to capture network state: {e}")
        state = {
            "interfaces": [],
            "addresses": [],
            "routes": [],
            "dns": {},
            "processes": "",
        }

    return state
