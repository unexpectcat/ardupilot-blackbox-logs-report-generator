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
    stem = os.path.splitext(os.path.basename(p))[0]
    return int(stem) if stem.isdigit() else -1


def discover_logs_in_dir(directory):
    """All .BIN/.bin logs in a directory, in flight order (by numeric filename).

    Dataflash SD cards commonly have no working RTC, so every file's mtime is
    identical (e.g. 1980-01-01) - filesystem "latest" is meaningless here; the
    zero-padded log number is the only reliable chronological order.
    """
    files = glob.glob(os.path.join(directory, "*.BIN")) + glob.glob(os.path.join(directory, "*.bin"))
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

    return joined
