import time
from typing import Dict

from net_tester.utils import run_cmd


def wait_for_docker(log, args, timeout: int = 45) -> Dict[str, object]:
    """
    Wait for Docker daemon to become available.

    Never blocks forever.
    Never throws.
    """
    start = time.time()

    while time.time() - start < timeout:
        result = run_cmd(["docker", "info"], check=False)
        if result.returncode == 0:
            log.success("Docker daemon is running")
            return {"running": True}

        time.sleep(1)

    log.warning("Docker daemon not available after timeout")
    return {"running": False}
