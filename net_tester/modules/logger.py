import sys

# --- ANSI ---
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
RESET = "\033[0m"
BOLD = "\033[1m"

# --- Emoji ---
OK = "✅"
INFO = "ℹ️"
WARN = "⚠️"
ERR = "❌"
DEBUG = "🔎"
MODULE = "📦"

# --- Bell ---
BELL = "\a"  # terminal bell


class Logger:
    def __init__(self, *, quiet=False, verbose=False, debug=False):
        self.quiet = quiet
        self.verbose = verbose
        self.debug_enabled = debug

    # --- core output ---
    def _emit(self, msg):
        sys.stdout.write(msg + "\n")

    # --- levels ---
    def info(self, msg):
        if self.quiet:
            return
        self._emit(f"{BOLD}{BLUE}{INFO} {msg}{RESET}")

    def success(self, msg):
        if self.quiet:
            return
        self._emit(f"{BOLD}{GREEN}{OK} {msg}{RESET}")

    def warn(self, msg):
        self._emit(f"{BOLD}{YELLOW}{WARN} {msg}{RESET}")

    def error(self, msg):
        self._emit(f"{BOLD}{RED}{ERR} {msg}{RESET}")

    def debug(self, msg):
        if not self.debug_enabled:
            return
        self._emit(f"{MAGENTA}{DEBUG} {msg}{RESET}")

    def bell(self):
        sys.stdout.write(BELL + "\n")

    # --- structure ---
    def module_start(self, name: str):
        if self.quiet:
            return
        line = "=" * 70
        title = f" {MODULE} STARTING MODULE: {name.upper()} {MODULE} "
        self._emit("\n" + line)
        self._emit(f"{BOLD}{CYAN}{title.center(70, '=')}{RESET}")
        self._emit(line + "\n")


# Create a default logger instance
log = Logger()


def configure_logger(*, quiet=False, verbose=False, debug=False) -> Logger:
    return Logger(quiet=quiet, verbose=verbose, debug=debug)
