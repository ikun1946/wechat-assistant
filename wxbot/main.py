"""wxbot 命令行入口。

用法：
    python -m wxbot status   # 查看配置、安全参数与微信运行情况
    python -m wxbot run      # 启动主循环（收发模块接入后可用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .safety.gateway import SafetyGateway
from .wechat import window_check


def _load_config(args):
    return load_config(Path(args.config) if args.config else None)


def cmd_providers(args) -> int:
    """列出内置厂商（图形界面「模型」页可直接选择）。"""
    from .providers import all_providers

    print("内置厂商（图形界面「模型」页可一键应用）：")
    for provider in all_providers():
        tag = "本地" if provider.local else "云端"
        print(f"  [{provider.key}] {provider.label}  ({tag})")
        if provider.base_url:
            print(f"      地址：{provider.base_url}")
        if provider.key_env:
            print(f"      Key 环境变量：{provider.key_env}")
        if provider.note:
            print(f"      说明：{provider.note}")
    return 0


def cmd_models(args) -> int:
    """列出模型库里已配置的模型（每个厂商 × 模型各自一套参数）。"""
    from .brain.model_store import ModelStore
    from .providers import get_provider

    entries = ModelStore().entries()
    if not entries:
        print("模型库为空：打开图形界面「模型」页，选厂商后点「从厂商获取模型列表」即可自动入库。")
        return 0
    print(f"模型库共 {len(entries)} 个模型：")
    for entry in entries:
        modalities = "/".join(entry.modalities)
        print(
            f"  [{get_provider(entry.provider).label}] {entry.model}"
            f"  上下文={entry.context_length:,}  模态={modalities}"
            f"  思考={entry.thinking_level}  最大输出={entry.max_output_tokens:,}"
        )
    return 0


def cmd_status(args) -> int:
    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"[配置错误] {exc}")
        return 2

    print("== wxbot 状态 ==")
    print(f"运行模式: {cfg.mode}（dry_run=只记录不发送；auto=真实发送）")
    print(f"技术路线: {cfg.route}")

    if cfg.whitelist.allow_all:
        whitelist_desc = "⚠ 全部允许（白名单限制已关闭）"
    elif cfg.whitelist.chats:
        whitelist_desc = "、".join(cfg.whitelist.chats)
    else:
        whitelist_desc = "（空：当前不会回复任何人）"
    print(f"白名单: {'开启' if cfg.whitelist.enabled else '关闭'} | {whitelist_desc}")

    s = cfg.safety
    print(f"限速: {s.max_per_minute}/分钟 · {s.max_per_hour}/小时 · {s.max_per_day}/天")
    print(
        f"静默时段: {'、'.join(s.quiet_hours) or '无'}"
        f" | 回复随机延迟: {s.min_reply_delay_sec}~{s.max_reply_delay_sec}s"
    )
    print(f"回复引擎: {cfg.reply.engine}")

    windows = window_check.find_wechat_windows()
    if windows:
        for win in windows:
            print(f"微信窗口: {win['exe'] or '(未知进程)'} pid={win['pid']} title={win['title']!r}")
    else:
        print("微信窗口: 未检测到（请确认微信已启动并登录，且主窗口未隐藏）")

    gateway = SafetyGateway(cfg.safety, cfg.whitelist)
    gateway_state = f"熔断中：{gateway.trip_reason}" if gateway.tripped else "正常"
    print(f"安全网关: {gateway_state}")
    return 0


def cmd_run(args) -> int:
    """命令行运行模式：等同图形界面的「启动」开关（Ctrl+C 停止）。"""
    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"[配置错误] {exc}")
        return 2

    from .runner import build_default_runner

    print("=" * 66)
    print("wxbot 运行中（Ctrl+C 停止）")
    print(f"  模式：{cfg.mode}（{'只记录不发送' if cfg.mode != 'auto' else '全自动'}）")
    print(f"  白名单：{'、'.join(cfg.whitelist.chats) or '（空：谁都不回）'}")
    print(f"  回复引擎：{cfg.reply.engine}")
    print("=" * 66)

    def on_event(event) -> None:
        from datetime import datetime

        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}] {event.text}", flush=True)

    runner = build_default_runner(
        cfg, on_event=on_event, poll_interval=float(getattr(args, "interval", 3.0))
    )
    runner.start()
    try:
        while runner.running:
            import time

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n收到中断信号，正在停止…")
    finally:
        runner.stop()
    stats = runner.stats
    print(
        f"已停止。本轮统计：轮询 {stats.polls} 次，识别 {stats.received} 条，"
        f"拟回复 {stats.replied} 条，已发送 {stats.sent} 条，"
        f"拦截 {stats.denied} 条，跳过 {stats.skipped} 条，出错 {stats.errors} 次。"
    )
    return 0


def cmd_learn(args) -> int:
    """AI 复盘聊天记录，整理技能条目（供 GUI 列表逐条开关）。"""
    try:
        cfg = _load_config(args)
    except ConfigError as exc:
        print(f"[配置错误] {exc}")
        return 2
    if not (cfg.llm.base_url and cfg.llm.model):
        print("[学习] 需要先配置模型（本地或云端）：请在图形界面「模型」页设置并保存。")
        return 2

    from .brain.learned import LearnedStore
    from .brain.learner import ConversationSample, LearnError, SkillLearner
    from .brain.llm import LLMEngine, LLMError
    from .brain.memory import ChatMemory

    memory = ChatMemory()
    chats = [args.chat] if args.chat else memory.chats()
    if not chats:
        print("[学习] 暂无聊天记录可学习：主循环运行一段时间后（消息会记入本地记忆）再来。")
        return 3

    samples = []
    for chat_name in chats:
        messages = memory.recent(chat_name, max(2, int(args.limit)))
        if len(messages) >= 2:
            samples.append(
                ConversationSample(chat_name=chat_name, messages=tuple(messages))
            )
    if not samples:
        print("[学习] 聊天记录太少（每条会话至少需要 2 条消息）。")
        return 3

    try:
        engine = LLMEngine(cfg.llm)
        learner = SkillLearner(LearnedStore(), generator=engine.generate)
        report = learner.learn_from(samples)
    except (LLMError, LearnError) as exc:
        print(f"[学习] 失败：{exc}")
        return 4

    print(
        f"[学习] 完成：新增 {report.added} 条，重复 {report.duplicates} 条，"
        f"无效 {report.invalid} 条；技能库共 {report.total} 条。"
    )
    print("在图形界面「技能」页可以逐条启用/停用（数据文件：data/learned_skills.json）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wxbot", description="微信自动回复助手（安全优先）")
    parser.add_argument("--config", help="配置文件路径（默认使用项目根目录 config.toml）")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    subparsers.add_parser("status", help="查看配置与运行状态")
    run_parser = subparsers.add_parser("run", help="启动自动对话循环（Ctrl+C 停止）")
    run_parser.add_argument(
        "--interval", type=float, default=3.0, help="抓屏识别间隔（秒，默认 3）"
    )
    subparsers.add_parser("gui", help="打开图形界面（开关 / 模型 / 速度 / 白名单 / 技能）")
    learn_parser = subparsers.add_parser(
        "learn", help="AI 复盘聊天记录，自动整理技能（需先配置模型）"
    )
    learn_parser.add_argument("--chat", help="只学习指定会话（默认全部）")
    learn_parser.add_argument(
        "--limit", type=int, default=80, help="每条会话最多取多少条消息（默认 80）"
    )
    subparsers.add_parser("providers", help="列出内置模型厂商")
    subparsers.add_parser("models", help="列出模型库里已配置的模型")
    args = parser.parse_args(argv)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "gui":
        from .gui import run_gui

        return run_gui()
    if args.cmd == "learn":
        return cmd_learn(args)
    if args.cmd == "providers":
        return cmd_providers(args)
    if args.cmd == "models":
        return cmd_models(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
