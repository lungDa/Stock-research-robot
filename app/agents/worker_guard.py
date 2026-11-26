"""Defense in depth for snapshot workers; not an OS security boundary."""
import os
import sys

def install():
    def audit(event, args):
        if event.startswith(("socket.", "subprocess.")) or event in {
            "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty",
            "os.spawn", "os.kill", "os.killpg", "os.remove", "os.rename",
            "os.mkdir", "os.rmdir", "os.chmod", "os.chown", "os.link",
            "os.symlink", "os.truncate", "os.utime", "os.setxattr",
            "os.removexattr", "os.chdir", "os.fchdir", "os.chroot",
        }:
            raise PermissionError("snapshot worker operation denied")
        # NumPy/Pandas initialize ctypes against the current process.
        # This is a Python-level guard, not a native-code sandbox.
        if event == "ctypes.dlopen" and args[0] is not None:
            raise PermissionError("snapshot worker native library denied")
        if event == "sqlite3.connect" and args[0] != ":memory:":
            raise PermissionError("snapshot worker database denied")
        if event == "open":
            path, mode, flags = args
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                raise PermissionError("snapshot worker write denied")
    sys.addaudithook(audit)
