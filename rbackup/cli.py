from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

from . import __version__
from . import audit
from .app import App
from .backup import run_backup
from .config import default_config_path, init_config
from .diff import run_diff
from .doctor import run_doctor
from .errors import RbackupError, UsageError
from .prune import run_prune
from .restore import run_restore
from .status import run_status
from .verify import run_verify
from .versions import run_versions
from .watch import run_watch
from .webconfig import (
    config_backup_dir,
    list_config_backups,
    restore_config_backup,
)
from .webui import run_web


def _add_common(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument(
        "--config",
        default=default,
        metavar="PATH",
        help="配置文件路径（默认 ./rbackup.toml 或系统配置目录）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=argparse.SUPPRESS if suppress else 0,
        help="输出更多日志（可重复）",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="减少诊断日志（不隐藏命令结果）",
    )


def _subparser(sub: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    parser = sub.add_parser(name, help=help_text, description=help_text)
    _add_common(parser, suppress=True)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rbackup",
        description="每设备前缀、云端版本、零本地索引的 rclone 加密备份工具",
    )
    _add_common(parser)
    parser.add_argument("--version", action="version", version=f"rbackup {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="命令")

    p = _subparser(sub, "init", "生成配置模板")
    p.add_argument("--device", help="设备名（默认取主机名）")
    p.add_argument(
        "--remote",
        default="b_crypt",
        help="rclone crypt remote 名（底层指向本地 B 同步目录）",
    )
    p.add_argument("--force", action="store_true", help="覆盖已有配置文件")

    p = _subparser(sub, "web", "启动本地 Web 配置页面")
    p.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    p = _subparser(sub, "doctor", "检查 rclone、remote、目录和状态文件")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "backup", "把本地类别 copy 到本设备前缀（不 sync）")
    p.add_argument("categories", nargs="*", metavar="类别")
    p.add_argument("--dry-run", action="store_true", help="只显示 rclone 计划，不写入")
    p.add_argument(
        "--force",
        action="store_true",
        help="远端相对状态基线有漂移时，仍用本地覆盖同名远端文件",
    )
    p.add_argument("--verify", action="store_true", help="上传后运行 rclone cryptcheck")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "watch", "轮询远端变化，只报告，是否处理由用户决定")
    p.add_argument("categories", nargs="*", metavar="类别")
    p.add_argument("--interval", type=float, help="轮询间隔秒数（默认取配置）")
    p.add_argument("--once", action="store_true", help="打印基线/漂移后退出")
    p.add_argument(
        "--exit-on-change",
        action="store_true",
        help="检测到第一批变化后退出（适合 CI/通知脚本）",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="检测到变化后在终端询问恢复/覆盖/忽略",
    )
    p.add_argument(
        "--restore-dir",
        help="交互恢复的目标根目录（默认 ./rbackup-restore）",
    )
    p.add_argument("--json", action="store_true", dest="json_output", help="输出 JSONL 事件")
    p.add_argument("--max-events", type=int, default=50, help="人类可读模式最多展示多少项")

    p = _subparser(sub, "status", "显示状态基线，并按需检查远端漂移")
    p.add_argument("categories", nargs="*", metavar="类别")
    p.add_argument("--json", action="store_true", dest="json_output")
    p.add_argument("--check", action="store_true", help="有漂移时退出码 3")
    p.add_argument(
        "--offline",
        action="store_true",
        help="只读 _state，不列举当前远端数据（仍会读取状态文件）",
    )

    p = _subparser(sub, "diff", "比较本地与远端当前版本（不下载）")
    p.add_argument("categories", nargs="*", metavar="类别")
    p.add_argument("--json", action="store_true", dest="json_output")
    p.add_argument("--check", action="store_true", help="有差异时退出码 3")
    p.add_argument("--max-items", type=int, default=200, help="每个分组最多展示多少项")

    p = _subparser(sub, "verify", "用 rclone cryptcheck 校验本地明文与远端密文")
    p.add_argument("categories", nargs="*", metavar="类别")
    p.add_argument("--one-way", action="store_true", help="只校验本地存在的文件")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "versions", "列出云端历史版本")
    p.add_argument("category", nargs="?", metavar="类别")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "prune", "清理云端历史版本（当前数据不受影响）")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--keep", type=int, help="保留最新 N 个版本（默认取配置）")
    group.add_argument("--older-than", type=int, dest="older_than_days", help="删除 N 天前的版本")
    p.add_argument("--yes", action="store_true", help="确认执行删除")
    p.add_argument("--dry-run", action="store_true", help="只列出计划")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "restore", "从当前版本或历史版本恢复到本地")
    p.add_argument("category", metavar="类别")
    p.add_argument("remote_path", nargs="?", default="", metavar="远端路径")
    p.add_argument("--dest", required=True, metavar="本地目标", help="目标文件或目录")
    p.add_argument("--version", dest="version_id", help="历史版本 ID（见 versions 命令）")
    p.add_argument("--force", action="store_true", help="允许覆盖已存在的目标")
    p.add_argument("--dry-run", action="store_true", help="只显示计划")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "audit", "查看写操作的审计日志（删除/恢复/上传/保存配置）")
    p.add_argument("--limit", type=int, default=50, help="最多显示多少条（默认 50）")
    p.add_argument("--json", action="store_true", dest="json_output")

    p = _subparser(sub, "config-backup", "查看或恢复配置文件的自动备份")
    p.add_argument("--list", action="store_true", help="列出历史备份（默认动作）")
    p.add_argument("--restore", metavar="文件名", help="用指定备份覆盖当前配置")
    p.add_argument("--yes", action="store_true", help="恢复时不再询问")
    p.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _configure_stdio() -> None:
    """管道/重定向时统一 UTF-8；真实控制台保留 Python 的原生编码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                continue
        except (AttributeError, OSError):
            pass
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _configure_logging(verbose: int, quiet: bool) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )


def _init(args: argparse.Namespace) -> int:
    target = (
        Path(args.config).expanduser()
        if args.config
        else default_config_path()
    )
    path = init_config(
        target,
        device=args.device,
        remote=args.remote,
        force=args.force,
    )
    print(f"已生成配置：{path}")
    print("\n下一步：")
    print("  1. 创建本地 B 同步目录，并让网盘客户端把 B 同步到云端")
    print("  2. rclone config 创建 crypt remote（如 b_crypt），其 remote 指向 B 本地目录")
    print("  3. 编辑配置中的 [categories.<类别>] path/excludes")
    print(f"  4. rbackup --config \"{path}\" doctor")
    print(f"  5. rbackup --config \"{path}\" backup --dry-run")
    return 0


def _resolve_config_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve(strict=False)
    return default_config_path().expanduser().resolve(strict=False)


def _cmd_audit(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    entries = audit.read_entries(path, max(1, args.limit))
    log_path = audit.audit_path(path)
    if args.json_output:
        print(json.dumps(
            {"path": str(log_path), "entries": entries}, ensure_ascii=False
        ))
        return 0
    if not entries:
        print(f"还没有审计记录：{log_path}")
        return 0
    print(f"审计日志：{log_path}（最近 {len(entries)} 条）\n")
    for entry in entries:
        stamp = str(entry.get("ts", ""))[:19].replace("T", " ")
        op = entry.get("op", "?")
        scope = entry.get("category") or ",".join(entry.get("categories") or [])
        count = entry.get("count")
        result = (
            "预演" if entry.get("dry_run")
            else ("失败" if entry.get("ok") is False else ("部分失败" if entry.get("failed") else "成功"))
        )
        detail = []
        if scope:
            detail.append(str(scope))
        if count is not None:
            detail.append(f"{count} 项")
        if entry.get("version"):
            detail.append(f"版本 {entry['version']}")
        if entry.get("error"):
            detail.append(str(entry["error"]))
        print(f"{stamp}  {op:<14} {result:<6} {' · '.join(detail)}")
    return 0


def _cmd_config_backup(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)

    if args.restore:
        if not args.yes:
            answer = input(f"用备份 {args.restore} 覆盖 {path}？[y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("已取消。")
                return 1
        source, safety = restore_config_backup(path, args.restore)
        audit.record(
            path,
            "config.restore",
            backup=source.name,
            safety=str(safety) if safety else None,
            actor="cli",
        )
        print(f"已恢复配置：{source}")
        if safety:
            print(f"覆盖前的配置备份：{safety}")
        return 0

    backups = list_config_backups(path)
    if args.json_output:
        print(json.dumps(
            {"path": str(path), "dir": str(config_backup_dir(path)), "backups": backups},
            ensure_ascii=False,
        ))
        return 0
    if not backups:
        print(f"还没有配置备份。每次保存配置会自动留一份，目录：{config_backup_dir(path)}")
        return 0
    print(f"配置备份目录：{config_backup_dir(path)}（共 {len(backups)} 份）\n")
    for item in backups:
        size_kb = max(1, round(item["size"] / 1024))
        print(f"{item['mtime'][:19].replace('T', ' ')}  {size_kb:>4} KB  {item['name']}")
    print(f"\n恢复某一份：rbackup config-backup --restore <文件名>")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", 0), getattr(args, "quiet", False))
    try:
        if args.command == "init":
            return _init(args)
        if args.command == "web":
            return run_web(
                args.config,
                port=args.port,
                open_browser=not args.no_browser,
            )
        # 这两个命令只读本地文件，不需要解析出完整的备份配置
        if args.command == "audit":
            return _cmd_audit(args)
        if args.command == "config-backup":
            return _cmd_config_backup(args)

        app = App.create(
            args.config,
            require_crypt=args.command != "doctor",
        )
        if args.command == "doctor":
            return run_doctor(app, json_output=args.json_output)
        if args.command == "backup":
            result = run_backup(
                app,
                args.categories,
                dry_run=args.dry_run,
                force=args.force,
                verify=args.verify,
                json_output=args.json_output,
            )
            return int(result["exit_code"])
        if args.command == "watch":
            if args.max_events < 1:
                raise UsageError("--max-events 至少为 1")
            return run_watch(
                app,
                args.categories,
                interval=args.interval,
                once=args.once,
                exit_on_change=args.exit_on_change,
                interactive=args.interactive,
                restore_dir=Path(args.restore_dir) if args.restore_dir else None,
                json_output=args.json_output,
                max_events=args.max_events,
            )
        if args.command == "status":
            return run_status(
                app,
                args.categories,
                json_output=args.json_output,
                check=args.check,
                offline=args.offline,
            )
        if args.command == "diff":
            if args.max_items < 1:
                raise UsageError("--max-items 至少为 1")
            return run_diff(
                app,
                args.categories,
                json_output=args.json_output,
                check=args.check,
                max_items=args.max_items,
            )
        if args.command == "verify":
            return run_verify(
                app,
                args.categories,
                one_way=args.one_way,
                json_output=args.json_output,
            )
        if args.command == "versions":
            return run_versions(app, args.category, json_output=args.json_output)
        if args.command == "prune":
            code = run_prune(
                app,
                keep=args.keep,
                older_than_days=args.older_than_days,
                yes=args.yes,
                dry_run=args.dry_run,
                json_output=args.json_output,
            )
            if not args.dry_run:
                audit.record(
                    app.config.path,
                    "prune",
                    actor="cli",
                    keep=args.keep,
                    older_than_days=args.older_than_days,
                    ok=code == 0,
                )
            return code
        if args.command == "restore":
            code = run_restore(
                app,
                args.category,
                args.remote_path,
                args.dest,
                version_id=args.version_id,
                force=args.force,
                dry_run=args.dry_run,
                json_output=args.json_output,
            )
            if not args.dry_run:
                audit.record(
                    app.config.path,
                    "restore",
                    actor="cli",
                    category=args.category,
                    items=[args.remote_path or "."],
                    dest=args.dest,
                    version=args.version_id,
                    force=args.force,
                    ok=code == 0,
                )
            return code
        raise UsageError(f"未知命令：{args.command}")
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0
    except RbackupError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        if getattr(args, "verbose", 0):
            traceback.print_exc()
        print(f"内部错误：{exc}", file=sys.stderr)
        return 1
