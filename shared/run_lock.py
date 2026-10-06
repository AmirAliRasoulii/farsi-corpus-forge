"""
Run directory locking mechanism using OS-level file locks.
Prevents concurrent execution in the same output/run directory.
"""
import os
import sys

try:
    import fcntl
except ImportError:
    fcntl = None


class RunDirectoryLock:
    """
    Acquires an exclusive lock file in the output directory.
    Releases on exit or crash.
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.lock_file_path = os.path.join(output_dir, ".run.lock")
        self.file_handle = None

    def __enter__(self):
        os.makedirs(self.output_dir, exist_ok=True)
        self.file_handle = open(self.lock_file_path, "w")
        if fcntl:
            try:
                fcntl.flock(self.file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, BlockingIOError):
                self.file_handle.close()
                raise RuntimeError(
                    f"Directory '{self.output_dir}' is currently locked by another running process. "
                    "Concurrent runs in the same directory are prohibited to prevent state corruption."
                )
        self.file_handle.write(f"PID: {os.getpid()}\n")
        self.file_handle.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file_handle:
            if fcntl:
                try:
                    fcntl.flock(self.file_handle, fcntl.LOCK_UN)
                except Exception:
                    pass
            self.file_handle.close()
            try:
                if os.path.exists(self.lock_file_path):
                    os.remove(self.lock_file_path)
            except Exception:
                pass
