"""Own the complete game process tree with a Windows kill-on-close Job.

The client starts suspended, joins the Job, then runs. Its descendants cannot
outlive the launcher's Job handle, even if the client exits before cleanup.
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import time


class _BasicLimits(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64),
                ('flags', w.DWORD), ('min_working_set', c.c_size_t),
                ('max_working_set', c.c_size_t), ('process_limit', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class _IOCounters(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class _ExtendedLimits(c.Structure):
    _fields_ = [('basic', _BasicLimits), ('io', _IOCounters),
                ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                ('peak_process_memory', c.c_size_t), ('peak_job_memory', c.c_size_t)]


class _Accounting(c.Structure):
    _fields_ = [(name, c.c_int64) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
        (name, w.DWORD) for name in ('page_faults', 'total', 'active', 'terminated')]


class _Startup(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                ('title', w.LPWSTR), ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD),
                ('height', w.DWORD), ('x_chars', w.DWORD), ('y_chars', w.DWORD),
                ('fill', w.DWORD), ('flags', w.DWORD), ('show', w.WORD),
                ('reserved_size', w.WORD), ('reserved_data', c.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class _Process(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


def run(command, *, cwd, env, log, cleanup_path):
    """Run a native program; return its exit code or 130 after Ctrl-C."""
    if os.name != 'nt':
        raise OSError('Windows Job launcher requires Windows')
    import msvcrt
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL,
                            w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(_Startup), c.POINTER(_Process)], w.BOOL),
        'ResumeThread': ([w.HANDLE], w.DWORD),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'GetExitCodeProcess': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result

    def check(result):
        if not result:
            raise c.WinError(c.get_last_error())
        return result

    job = check(kernel.CreateJobObjectW(None, None))
    process = _Process()
    assigned = False
    audit = {'root_pid': None, 'cleanup_complete': False, 'active_processes': None}
    try:
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        check(kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)))
        startup = _Startup()
        startup.cb = c.sizeof(startup)
        startup.flags = 0x100  # STARTF_USESTDHANDLES
        startup.stdout = startup.stderr = msvcrt.get_osfhandle(log.fileno())
        # Only these two Python file handles are made inheritable, briefly for
        # CreateProcess. The Job handle itself must never be inherited.
        with open(os.devnull, 'rb') as stdin:
            startup.stdin = msvcrt.get_osfhandle(stdin.fileno())
            handles = (startup.stdin, startup.stdout)
            previous = [os.get_handle_inheritable(handle) for handle in handles]
            try:
                for handle in handles:
                    os.set_handle_inheritable(handle, True)
                environment = c.create_unicode_buffer('\0'.join(
                    key + '=' + value for key, value in sorted(env.items(), key=lambda item: item[0].upper())) + '\0')
                line = c.create_unicode_buffer(subprocess.list2cmdline(list(map(str, command))))
                # SUSPENDED | UNICODE_ENVIRONMENT | NEW_PROCESS_GROUP. The
                # launcher receives Ctrl-C; the engine does not race its cleanup.
                check(kernel.CreateProcessW(str(command[0]), line, None, None, True, 0x604,
                                            environment, str(cwd), c.byref(startup), c.byref(process)))
            finally:
                for handle, inherited in zip(handles, previous):
                    os.set_handle_inheritable(handle, inherited)
        audit['root_pid'] = process.pid
        check(kernel.AssignProcessToJobObject(job, process.process))
        assigned = True
        if kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
            raise c.WinError(c.get_last_error())
        while True:
            status = kernel.WaitForSingleObject(process.process, 100)
            if status == 0:  # WAIT_OBJECT_0
                code = w.DWORD()
                check(kernel.GetExitCodeProcess(process.process, c.byref(code)))
                return code.value
            if status != 258:  # WAIT_TIMEOUT
                raise c.WinError(c.get_last_error())
    except KeyboardInterrupt:
        return 130
    finally:
        try:
            if process.process and not assigned:
                check(kernel.TerminateProcess(process.process, 125))
                kernel.WaitForSingleObject(process.process, 5000)
            check(kernel.TerminateJobObject(job, 130))
            deadline = time.monotonic() + 5
            while True:
                accounting = _Accounting()
                check(kernel.QueryInformationJobObject(job, 1, c.byref(accounting), c.sizeof(accounting), None))
                audit['active_processes'] = accounting.active
                if accounting.active == 0:
                    audit['cleanup_complete'] = True
                    break
                if time.monotonic() >= deadline:
                    raise OSError('Windows game Job cleanup did not complete')
                time.sleep(.02)
        finally:
            for handle in (process.thread, process.process, job):
                if handle:
                    kernel.CloseHandle(handle)
            Path(cleanup_path).write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
