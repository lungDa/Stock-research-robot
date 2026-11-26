"""Defense in depth for snapshot workers; not an OS security boundary."""
import os
import sys

def install():
    # Resolve symlinks before checking paths. Only runtime/code resources
    # and timezone data are needed by snapshot analysis.
    import sysconfig
    roots = tuple(os.path.realpath(p) for p in {
        sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib"),
        sysconfig.get_path("purelib"), sysconfig.get_path("platlib"),
        "/usr/share/zoneinfo",
    } if p)
    repo = os.path.realpath(os.path.join(os.path.dirname(__file__), "../.."))
    code_roots = tuple(os.path.join(repo, p) for p in ("app", "jobs"))
    def allowed_read(path):
        if isinstance(path, int):
            return path in (0, 1, 2)
        path = os.path.realpath(os.fsdecode(path))
        parts = path.lower().split(os.sep)
        if any(p.startswith(".env") or p in {".git", ".ssh", ".aws", "secrets", "credentials"} or p.endswith((".pem", ".key", ".p12", ".pfx")) for p in parts):
            return False
        if any(path.startswith(root + os.sep) for root in roots):
            return True
        return any(path.startswith(root + os.sep) for root in code_roots) and path.endswith((".py", ".pyc"))
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
            if not allowed_read(path):
                raise PermissionError("snapshot worker read denied")
    sys.addaudithook(audit)
