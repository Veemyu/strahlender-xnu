"""Owned Win32 compiler processes, assigned to a job before their first instruction."""
import ctypes
from ctypes import wintypes as w
import os
import subprocess

SIZE_T = ctypes.c_size_t


class StartupInfo(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
                ("title", w.LPWSTR), ("x", w.DWORD), ("y", w.DWORD),
                ("xsize", w.DWORD), ("ysize", w.DWORD), ("xchars", w.DWORD),
                ("ychars", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_data", ctypes.c_void_p),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE),
                ("pid", w.DWORD), ("tid", w.DWORD)]


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD), ("minimum_set", SIZE_T), ("maximum_set", SIZE_T),
                ("active", w.DWORD), ("affinity", SIZE_T), ("priority", w.DWORD),
                ("scheduling", w.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ctypes.c_ulonglong * 6),
                ("process_memory", SIZE_T), ("job_memory", SIZE_T),
                ("peak_process", SIZE_T), ("peak_job", SIZE_T)]


class Job:
    def __init__(self):
        self.handle = None
        if os.name != "nt":
            raise OSError("Win32 process jobs require Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR,
                                ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo)], w.BOOL),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "GetStdHandle": ([w.DWORD], w.HANDLE),
            "GetCurrentProcess": ([], w.HANDLE),
            "DuplicateHandle": ([w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE),
                                 w.DWORD, w.BOOL, w.DWORD], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def spawn(self, arguments, *, stdout=None, stderr=None, env=None, cwd=None):
        if not self.handle:
            raise OSError("Compiler process job is closed")
        command = subprocess.list2cmdline([str(argument) for argument in arguments])
        startup, info = StartupInfo(), ProcessInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.flags = 0x100  # STARTF_USESTDHANDLES: preserve the installer's output pipes.
        startup.stdin = self.kernel.GetStdHandle(w.DWORD(-10).value)
        startup.stdout = self.kernel.GetStdHandle(w.DWORD(-11).value)
        startup.stderr = self.kernel.GetStdHandle(w.DWORD(-12).value)
        inherited = []
        try:
            if stdout is not None or stderr is not None:
                import msvcrt
                for name, stream in (("stdout", stdout), ("stderr", stderr)):
                    if stream is None:
                        continue
                    handle = w.HANDLE()
                    process = self.kernel.GetCurrentProcess()
                    if not self.kernel.DuplicateHandle(process, msvcrt.get_osfhandle(stream.fileno()),
                                                       process, ctypes.byref(handle), 0, True, 2):
                        raise ctypes.WinError(ctypes.get_last_error())
                    inherited.append(handle)
                    setattr(startup, name, handle)
            environment = None
            if env is not None:
                environment = ctypes.create_unicode_buffer(
                    "\0".join(str(key) + "=" + str(value) for key, value in
                              sorted(env.items(), key=lambda item: item[0].upper())) + "\0\0")
            if not self.kernel.CreateProcessW(None, ctypes.create_unicode_buffer(command),
                                              None, None, True, 0x4 | 0x400,
                                              environment, str(cwd) if cwd else None,
                                              ctypes.byref(startup), ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            for handle in inherited:
                self.kernel.CloseHandle(handle)
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, info.process):
                raise ctypes.WinError(ctypes.get_last_error())
            if self.kernel.ResumeThread(info.thread) == 0xffffffff:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.kernel.TerminateProcess(info.process, 130)
            self.kernel.WaitForSingleObject(info.process, 0xffffffff)
            self.kernel.CloseHandle(info.process)
            raise
        finally:
            self.kernel.CloseHandle(info.thread)
        return Process(self.kernel, info.process, arguments)

    def cancel(self):
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 130):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


class Process:
    def __init__(self, kernel, handle, arguments):
        self.kernel, self.handle, self.arguments = kernel, handle, arguments

    def poll(self):
        return self.wait(timeout=0, polling=True)

    def wait(self, timeout=None, polling=False):
        milliseconds = 0xffffffff if timeout is None else max(0, min(0xfffffffe, int(timeout * 1000)))
        result = self.kernel.WaitForSingleObject(self.handle, milliseconds)
        if result == 258:
            if polling:
                return None
            raise subprocess.TimeoutExpired(self.arguments, timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = w.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def terminate(self):
        if not self.kernel.TerminateProcess(self.handle, 130):
            raise ctypes.WinError(ctypes.get_last_error())

    kill = terminate

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
