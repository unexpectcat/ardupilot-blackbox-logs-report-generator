"""Finding/ordering .BIN logs on disk, and recovering a CLI path argument."""

import os
import glob

SD_GLOBS = [
    "/run/media/*/*/APM/LOGS",
    "/media/*/*/APM/LOGS",
    "/media/*/APM/LOGS",
    "/Volumes/*/APM/LOGS",
]

MERGED_LABEL = "All logs in folder (merged flight)"


def find_sd_logs_dir():
    for pattern in SD_GLOBS:
        for d in sorted(glob.glob(pattern)):
            if glob.glob(os.path.join(d, "*.BIN")) or glob.glob(os.path.join(d, "*.bin")):
                return d
    return None


def _log_number(p):
    """Sort key for discovered logs: numerically-named dataflash logs (the
    common case) sort first, in numeric order; anything else (e.g. a .tlog
    named by timestamp) sorts after, alphabetically by filename."""
    stem = os.path.splitext(os.path.basename(p))[0]
    return (0, int(stem)) if stem.isdigit() else (1, os.path.basename(p).lower())


def discover_logs_in_dir(directory):
    """All .BIN/.bin dataflash logs and .tlog telemetry logs in a directory,
    in flight order (by numeric filename for dataflash logs).

    Dataflash SD cards commonly have no working RTC, so every file's mtime is
    identical (e.g. 1980-01-01) - filesystem "latest" is meaningless here; the
    zero-padded log number is the only reliable chronological order.
    """
    files = (glob.glob(os.path.join(directory, "*.BIN")) + glob.glob(os.path.join(directory, "*.bin")) +
             glob.glob(os.path.join(directory, "*.tlog")) + glob.glob(os.path.join(directory, "*.TLOG")))
    return sorted(files, key=_log_number)


def _resolve_cli_path(argv):
    """Recover a path argument from argv, tolerating shells that split an
    unquoted folder/file name containing spaces into several argv entries
    (e.g. a folder named "first flight ardu" typed without quotes).

    Returns None (no args), a single path string, a list of path strings
    (several explicit files given, to merge as one flight), or - if nothing
    resolves - the best-guess joined string so the caller can report it.
    """
    args = argv[1:]
    if not args:
        return None
    if len(args) == 1:
        return args[0]

    joined = os.path.expanduser(" ".join(args))
    if os.path.exists(joined):
        return joined

    expanded = [os.path.expanduser(a) for a in args]
    if all(os.path.exists(a) for a in expanded):
        return expanded

    # Neither "it's all one spaced-out path" nor "every arg is its own valid
    # file" panned out - a common cause is a botched unquoted attempt typed
    # alongside an already-correct (quoted/escaped) one, e.g.
    #   ~/Documents/foo bar ../other/foo\ bar/APM/LOGS/
    # where the first two tokens are a stray, unquoted retry and the rest is
    # the real, already-valid path. Try dropping leading tokens (longest
    # remaining suffix first), then trailing tokens (longest remaining prefix
    # first), and use the first reconstruction that actually exists.
    for i in range(1, len(args)):
        candidate = os.path.expanduser(" ".join(args[i:]))
        if os.path.exists(candidate):
            return candidate
    for j in range(len(args) - 1, 0, -1):
        candidate = os.path.expanduser(" ".join(args[:j]))
        if os.path.exists(candidate):
            return candidate

    return joined
