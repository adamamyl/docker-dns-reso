"""
modules/chatgpt.py

Handles sending large logs/snapshots to ChatGPT in manageable chunks.
Supports dry-run, verbose/quiet flags, and limits the number of posts.
"""

import math

from typing import Optional, Protocol

import modules.logger as logmod


# Define a Protocol so mypy knows what methods a logger has
class LoggerProtocol(Protocol):
    def info(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...

    def success(self, msg: str) -> None: ...

    def bell(self) -> None: ...


# Lazy access to avoid circular import issues
def get_logger() -> LoggerProtocol:
    return logmod.log


MAX_POSTS = 10  # safety limit on number of chunks


def send_to_chatgpt(
    text: str,
    scenario: str = "",
    chunk_size: int = 500,
    dry_run: bool = False,
    logger: Optional[LoggerProtocol] = None,
):
    log = logger or get_logger()
    lines = text.splitlines()
    total_chunks = math.ceil(len(lines) / chunk_size)

    if total_chunks > MAX_POSTS:
        log.warning(f"Reducing chunks from {total_chunks} to max {MAX_POSTS}")
        chunk_size = math.ceil(len(lines) / MAX_POSTS)
        total_chunks = MAX_POSTS

    log.info(f"Sending {total_chunks} chunks for scenario '{scenario}'")

    for idx in range(total_chunks):
        start = idx * chunk_size
        end = start + chunk_size
        chunk_lines = lines[start:end]
        chunk_text = "\n".join(chunk_lines)

        if idx == 0:
            # prepend instruction only on first chunk
            instructions = [
                f"You are analyzing the log/snapshot for scenario '{scenario}'.",
                "Chunks follow. Do NOT respond until all chunks are received.",
                f"I will indicate each chunk as 'Chunk X of {total_chunks}'.",
                "Your task: highlight changes, note errors/missing services, suggest potential fixes.",
                "Begin receiving chunks now.\n",
            ]
            chunk_text = "\n".join(instructions + chunk_lines)

        if dry_run:
            log.info(f"[DRY-RUN] Would send chunk {idx + 1} of {total_chunks} to ChatGPT")
        else:
            # Here we just copy to clipboard and ask the user to paste
            try:
                import subprocess

                subprocess.run(["pbcopy"], input=chunk_text.encode(), check=True)
                log.success(f"Chunk {idx + 1} of {total_chunks} copied to clipboard")
            except Exception:
                log.warning(f"Failed to copy chunk {idx + 1} to clipboard")

        # ⚡ Always ring bell and wait for user before next chunk
        log.bell()
        input(f"{logmod.YELLOW}Paste chunk {idx + 1} into ChatGPT and press Enter for next...{logmod.RESET}")

    log.info(f"All {total_chunks} chunks for scenario '{scenario}' processed")
    log.bell()
    input(f"{logmod.YELLOW}All chunks sent. Press Enter to finish...{logmod.RESET}")
