"""Owned temporary files: explicit registration and bounded, retryable cleanup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid


MARKER = ".ultra-board-temp.json"


def _alive(pid):
    if os.name=="nt":
        import ctypes
        api = ctypes.WinDLL("kernel32",use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.GetExitCodeProcess.argtypes = [ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x1000,False,pid)
        if not handle:
            return ctypes.get_last_error()!=87
        try:
            code = ctypes.c_ulong()
            return not api.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _save(path, document):
    pending = path.with_name(path.name + ".writing")
    pending.write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    pending.replace(path)


class Workspace:
    def __init__(self, root, purpose, files=(), owner_pid=None):
        pid = owner_pid or os.getpid()
        if not isinstance(pid,int) or pid<=0:
            raise ValueError("临时目录所属进程无效")
        self.root = Path(root).resolve()
        self.base = self.root / "data/store/tmp"
        self.path = self.base / uuid.uuid4().hex
        self.path.mkdir(parents=True)
        self.document = {"owner":"Ultra-Board","id":self.path.name,"purpose":purpose,"files":[],"pid":pid}
        self.cleanup_result = None
        _save(self.path / MARKER,self.document)
        try:
            self.reserve(files)
        except Exception:
            clean(self.root,self.path.name,owner_pid=pid)
            raise

    def reserve(self, names):
        paths = []
        for name in names:
            path = self.path / name
            path.resolve().relative_to(self.path.resolve())
            if path == self.path or path.name in {MARKER,MARKER+".writing"}:
                raise ValueError("临时文件名无效")
            relative = path.relative_to(self.path).as_posix()
            if relative not in self.document["files"]:
                self.document["files"].append(relative)
            atomic = path.with_name("."+path.name+".tmp").relative_to(self.path).as_posix()
            if atomic not in self.document["files"]:
                self.document["files"].append(atomic)
            paths.append(path)
        _save(self.path / MARKER,self.document)
        return paths

    def file(self, name):
        return self.reserve([name])[0]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.cleanup_result = clean(self.root,self.path.name,owner_pid=self.document["pid"])


def clean(root, identifier=None, owner_pid=None):
    base = Path(root).resolve() / "data/store/tmp"
    result = {"removed_workspaces":0,"removed_files":0,"in_use":0,"pending":[]}
    if not base.exists():
        return result
    candidates = [base / identifier] if identifier else list(base.iterdir())
    for directory in candidates:
        if not directory.exists():
            continue
        if directory.is_symlink() or directory.resolve().parent != base.resolve():
            result["pending"].append({"path":str(directory),"reason":"临时目录路径不符"})
            continue
        marker = directory / MARKER
        try:
            if marker.is_symlink():
                raise ValueError("临时登记文件为链接")
            document = json.loads(marker.read_text(encoding="utf-8"))
            if document.get("owner")!="Ultra-Board" or document.get("id")!=directory.name:
                raise ValueError("临时目录归属不符")
            if not isinstance(document["pid"],int) or document["pid"]<=0:
                raise ValueError("临时目录所属进程不符")
            if document["pid"]!=owner_pid and _alive(document["pid"]):
                result["in_use"] += 1
                continue
            files = {directory / MARKER,directory / (MARKER+".writing")}
            parents = {directory}
            for name in document["files"]:
                path = directory / name
                path.resolve().relative_to(directory.resolve())
                if path == directory:
                    raise ValueError("临时清单包含目录本身")
                files.add(path)
                if path.suffix==".sqlite":
                    files.update(Path(str(path)+tail) for tail in ("-wal","-shm","-journal"))
                parents.update(p for p in path.parents if p==directory or directory in p.parents)
            # Inspect every registered target before deleting any file.
            for path in files:
                if path.is_symlink() or (path.exists() and not path.is_file()):
                    raise ValueError(f"临时清单目标类型不符：{path.name}")
            for path in sorted(files-{marker},key=str):
                if path.exists():
                    path.unlink()
                    result["removed_files"] += 1
            for parent in sorted(parents-{directory},key=lambda p:len(p.parts),reverse=True):
                if parent.exists():
                    parent.rmdir()
            unknown = [p.name for p in directory.iterdir() if p!=marker]
            if unknown:
                raise ValueError("存在未登记内容："+", ".join(unknown))
            marker.unlink()
            directory.rmdir()
            result["removed_workspaces"] += 1
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result["pending"].append({"path":str(directory),"reason":str(exc)})
    return result
