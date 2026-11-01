from __future__ import annotations


class RbackupError(Exception):
    """所有可预期错误的基类，携带进程退出码。"""

    exit_code = 1


class ConfigError(RbackupError):
    exit_code = 2


class UsageError(RbackupError):
    exit_code = 2


class RemoteDriftError(RbackupError):
    """远端在两次运行之间发生变化，需要用户明确决定。"""

    exit_code = 3


class VerifyError(RbackupError):
    exit_code = 4


class AlreadyRunningError(RbackupError):
    exit_code = 1
