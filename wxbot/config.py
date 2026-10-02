"""配置加载、校验与写回（TOML，标准库 tomllib）。

安全立场：
- 只做「读入 + 基础校验 + 按模板写回」，不放宽任何安全默认值；
- 白名单为空时默认谁都不回复；
- API Key 永不写入 config.toml —— 只放环境变量或本地 secrets.toml（已 gitignore）。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _app_dir() -> Path:
    """配置 / 数据 / 密钥放在哪。

    打包成 exe 后，程序文件在 PyInstaller 的临时解包目录里（会随退出被删），
    **必须**把用户数据放到 exe 旁边，否则配置和聊天记忆每次启动都会丢。
    源码运行时就是项目根目录，行为不变。
    """
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


APP_DIR = _app_dir()
DEFAULT_CONFIG_PATH = APP_DIR / "config.toml"
SECRETS_PATH = APP_DIR / "secrets.toml"
DATA_DIR = APP_DIR / "data"


class ConfigError(Exception):
    """配置缺失或非法。"""


@dataclass
class SafetyConfig:
    quiet_hours: tuple[str, ...] = ("23:00-08:00",)
    max_per_minute: int = 2
    max_per_hour: int = 20
    max_per_day: int = 60
    min_reply_delay_sec: float = 2.0
    max_reply_delay_sec: float = 6.0
    auto_trip_on_failures: int = 5


@dataclass
class WhitelistConfig:
    enabled: bool = True
    allow_all: bool = False
    chats: tuple[str, ...] = ()


@dataclass
class ReplyRule:
    keywords: tuple[str, ...]
    reply: str


@dataclass
class ReplyConfig:
    engine: str = "rules"
    rules: tuple[ReplyRule, ...] = ()
    default_enabled: bool = False
    default_text: str = ""


@dataclass
class LLMConfig:
    provider: str = "custom"          # 厂商 key（见 wxbot/providers.py）
    base_url: str = ""
    model: str = ""
    api_style: str = "openai"         # openai=/chat/completions；anthropic=/messages
    api_key_env: str = ""
    system_prompt: str = ""
    temperature: float = 0.8
    max_tokens: int = 200             # 最大输出（生成上限）
    context_length: int = 32_768      # 该模型可用上下文
    modalities: tuple[str, ...] = ("text",)  # 输入的模态
    thinking_level: str = "auto"      # auto/off/low/medium/high
    timeout_sec: float = 30.0


@dataclass
class PersonaSkillConfig:
    """人设：AI 扮演成谁、怎么说话。空字段不会写进提示词。"""

    enabled: bool = True
    identity: str = ""                     # 他是谁（AI 扮演的身份）
    description: str = "说话简短、口语化，偶尔用「～」；不用书面语，不端着。"
    tone: str = "auto"                     # auto/warm/neutral/direct/humorous
    formality: int = 30                    # 0=很随意 100=很正式
    length: str = "short"                  # very_short/short/medium
    emoji: str = "rare"                    # never/rare/often
    catchphrases: tuple[str, ...] = ()     # 常用口头禅
    avoid: tuple[str, ...] = ()            # 不要做的事


TONES = ("auto", "warm", "neutral", "direct", "humorous")
TONE_LABELS = {
    "auto": "自动（不额外指定）",
    "warm": "温和亲切",
    "neutral": "中性自然",
    "direct": "干脆直接",
    "humorous": "幽默轻松",
}
LENGTHS = ("very_short", "short", "medium")
LENGTH_LABELS = {
    "very_short": "很短（一句话）",
    "short": "短（1~2 句）",
    "medium": "中等（几句，分点）",
}
EMOJIS = ("never", "rare", "often")
EMOJI_LABELS = {"never": "从不用", "rare": "偶尔用", "often": "经常用"}


@dataclass
class MemorySkillConfig:
    enabled: bool = True
    max_messages: int = 12


@dataclass
class SafetySkillConfig:
    enabled: bool = True
    banned_topics: tuple[str, ...] = ("转账", "密码", "验证码", "银行卡", "身份证")
    commitment_guard: bool = True


@dataclass
class GroupPolicySkillConfig:
    enabled: bool = True
    require_mention: bool = True
    extra_triggers: tuple[str, ...] = ()


@dataclass
class LearnedSkillConfig:
    enabled: bool = True
    auto_after_replies: int = 0  # 累计真实回复达到 N 条后自动学习一次；0=仅手动触发


@dataclass
class SkillsConfig:
    persona: PersonaSkillConfig = field(default_factory=PersonaSkillConfig)
    memory: MemorySkillConfig = field(default_factory=MemorySkillConfig)
    safety: SafetySkillConfig = field(default_factory=SafetySkillConfig)
    group_policy: GroupPolicySkillConfig = field(default_factory=GroupPolicySkillConfig)
    learned: LearnedSkillConfig = field(default_factory=LearnedSkillConfig)


@dataclass
class UiConfig:
    theme: str = "dark"            # dark / light
    poll_interval_sec: float = 3.0  # 抓屏识别间隔（图形界面「运行」页可调）


@dataclass
class AppConfig:
    mode: str = "dry_run"
    route: str = "auto"
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    whitelist: WhitelistConfig = field(default_factory=WhitelistConfig)
    reply: ReplyConfig = field(default_factory=ReplyConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    ui: UiConfig = field(default_factory=UiConfig)


def parse_quiet_span(spec: str) -> tuple[int, int]:
    """把 '23:00-08:00' 解析为 (开始分钟数, 结束分钟数)。非法格式抛 ConfigError。"""
    try:
        start_s, _, end_s = spec.partition("-")
        sh, sm = (int(part) for part in start_s.strip().split(":"))
        eh, em = (int(part) for part in end_s.strip().split(":"))
    except ValueError as exc:
        raise ConfigError(f"静默时段格式非法：{spec!r}（应形如 23:00-08:00）") from exc
    if not (0 <= sh < 24 and 0 <= sm < 60 and 0 <= eh < 24 and 0 <= em < 60):
        raise ConfigError(f"静默时段取值越界：{spec!r}")
    return sh * 60 + sm, eh * 60 + em


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def load_config(path: Path | None = None) -> AppConfig:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(
            f"配置文件不存在：{config_path}（可从 config.example.toml 复制并修改）"
        )
    return parse_config_text(config_path.read_text(encoding="utf-8"))


def parse_config_text(text: str) -> AppConfig:
    try:
        raw: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置语法错误：{exc}") from exc
    return _from_dict(raw)


def _from_dict(raw: dict[str, Any]) -> AppConfig:
    app = raw.get("app", {})
    mode = str(app.get("mode", "dry_run"))
    _require(mode in ("dry_run", "auto"), f"app.mode 只能是 dry_run 或 auto，当前：{mode!r}")
    route = str(app.get("route", "auto"))
    _require(route in ("auto", "uia", "vision"), f"app.route 只能是 auto/uia/vision，当前：{route!r}")

    wl = raw.get("whitelist", {})
    whitelist = WhitelistConfig(
        enabled=bool(wl.get("enabled", True)),
        allow_all=bool(wl.get("allow_all", False)),
        chats=tuple(str(x) for x in wl.get("chats", [])),
    )

    s = raw.get("safety", {})
    safety = SafetyConfig(
        quiet_hours=tuple(str(x) for x in s.get("quiet_hours", ["23:00-08:00"])),
        max_per_minute=int(s.get("max_per_minute", 2)),
        max_per_hour=int(s.get("max_per_hour", 20)),
        max_per_day=int(s.get("max_per_day", 60)),
        min_reply_delay_sec=float(s.get("min_reply_delay_sec", 2.0)),
        max_reply_delay_sec=float(s.get("max_reply_delay_sec", 6.0)),
        auto_trip_on_failures=int(s.get("auto_trip_on_failures", 5)),
    )
    for spec in safety.quiet_hours:
        parse_quiet_span(spec)
    _require(safety.max_per_minute >= 1, "safety.max_per_minute 必须 >= 1")
    _require(safety.max_per_hour >= 1, "safety.max_per_hour 必须 >= 1")
    _require(safety.max_per_day >= 1, "safety.max_per_day 必须 >= 1")
    _require(safety.min_reply_delay_sec > 0, "safety.min_reply_delay_sec 必须 > 0")
    _require(
        safety.min_reply_delay_sec <= safety.max_reply_delay_sec,
        "safety.min_reply_delay_sec 不能大于 max_reply_delay_sec",
    )
    _require(safety.auto_trip_on_failures >= 1, "safety.auto_trip_on_failures 必须 >= 1")

    r = raw.get("reply", {})
    engine = str(r.get("engine", "rules"))
    _require(engine in ("rules", "llm"), f"reply.engine 只能是 rules 或 llm，当前：{engine!r}")
    rules = tuple(
        ReplyRule(
            keywords=tuple(str(k) for k in item.get("keywords", [])),
            reply=str(item.get("reply", "")),
        )
        for item in r.get("rules", [])
    )
    reply = ReplyConfig(
        engine=engine,
        rules=rules,
        default_enabled=bool(r.get("default_enabled", False)),
        default_text=str(r.get("default_text", "")),
    )

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        provider=str(llm_raw.get("provider", "custom")),
        base_url=str(llm_raw.get("base_url", "")),
        model=str(llm_raw.get("model", "")),
        api_style=str(llm_raw.get("api_style", "openai")),
        api_key_env=str(llm_raw.get("api_key_env", "")),
        system_prompt=str(llm_raw.get("system_prompt", "")),
        temperature=float(llm_raw.get("temperature", 0.8)),
        max_tokens=int(llm_raw.get("max_tokens", 200)),
        context_length=int(llm_raw.get("context_length", 32_768)),
        modalities=tuple(str(m) for m in llm_raw.get("modalities", ["text"])),
        thinking_level=str(llm_raw.get("thinking_level", "auto")),
        timeout_sec=float(llm_raw.get("timeout_sec", 30.0)),
    )
    _require(0.0 <= llm.temperature <= 2.0, "llm.temperature 必须在 0~2 之间")
    _require(llm.max_tokens >= 1, "llm.max_tokens 必须 >= 1")
    _require(llm.timeout_sec > 0, "llm.timeout_sec 必须 > 0")
    _require(llm.api_style in ("openai", "anthropic"), "llm.api_style 只能是 openai 或 anthropic")
    _require(llm.context_length >= 512, "llm.context_length 必须 >= 512")
    _require(
        llm.thinking_level in ("auto", "off", "low", "medium", "high"),
        "llm.thinking_level 只能是 auto/off/low/medium/high",
    )
    unknown_modalities = [m for m in llm.modalities if m not in ("text", "image", "audio", "video", "file")]
    _require(not unknown_modalities, f"llm.modalities 含未知取值：{unknown_modalities}")
    if engine == "llm":
        _require(bool(llm.base_url), "reply.engine=llm 时必须配置 llm.base_url")
        _require(bool(llm.model), "reply.engine=llm 时必须配置 llm.model")

    skills_raw = raw.get("skills", {})
    persona_raw = skills_raw.get("persona", {})
    memory_raw = skills_raw.get("memory", {})
    safety_raw = skills_raw.get("safety", {})
    group_raw = skills_raw.get("group_policy", {})
    learned_raw = skills_raw.get("learned", {})
    skills = SkillsConfig(
        persona=PersonaSkillConfig(
            enabled=bool(persona_raw.get("enabled", True)),
            identity=str(persona_raw.get("identity", "")),
            description=str(persona_raw.get("description", PersonaSkillConfig.description)),
            tone=str(persona_raw.get("tone", "auto")),
            formality=int(persona_raw.get("formality", 30)),
            length=str(persona_raw.get("length", "short")),
            emoji=str(persona_raw.get("emoji", "rare")),
            catchphrases=tuple(str(x) for x in persona_raw.get("catchphrases", [])),
            avoid=tuple(str(x) for x in persona_raw.get("avoid", [])),
        ),
        memory=MemorySkillConfig(
            enabled=bool(memory_raw.get("enabled", True)),
            max_messages=int(memory_raw.get("max_messages", 12)),
        ),
        safety=SafetySkillConfig(
            enabled=bool(safety_raw.get("enabled", True)),
            banned_topics=tuple(
                str(x)
                for x in safety_raw.get(
                    "banned_topics", ["转账", "密码", "验证码", "银行卡", "身份证"]
                )
            ),
            commitment_guard=bool(safety_raw.get("commitment_guard", True)),
        ),
        group_policy=GroupPolicySkillConfig(
            enabled=bool(group_raw.get("enabled", True)),
            require_mention=bool(group_raw.get("require_mention", True)),
            extra_triggers=tuple(str(x) for x in group_raw.get("extra_triggers", [])),
        ),
        learned=LearnedSkillConfig(
            enabled=bool(learned_raw.get("enabled", True)),
            auto_after_replies=int(learned_raw.get("auto_after_replies", 0)),
        ),
    )
    _require(skills.memory.max_messages >= 1, "skills.memory.max_messages 必须 >= 1")
    _require(
        skills.persona.tone in ("auto", "warm", "neutral", "direct", "humorous"),
        "skills.persona.tone 取值非法",
    )
    _require(
        0 <= skills.persona.formality <= 100,
        "skills.persona.formality 必须在 0~100 之间",
    )
    _require(
        skills.persona.length in ("very_short", "short", "medium"),
        "skills.persona.length 取值非法",
    )
    _require(
        skills.persona.emoji in ("never", "rare", "often"),
        "skills.persona.emoji 取值非法",
    )
    _require(
        skills.learned.auto_after_replies >= 0,
        "skills.learned.auto_after_replies 必须 >= 0",
    )

    ui_raw = raw.get("ui", {})
    ui = UiConfig(
        theme=str(ui_raw.get("theme", "dark")),
        poll_interval_sec=float(ui_raw.get("poll_interval_sec", 3.0)),
    )
    _require(ui.theme in ("dark", "light"), "ui.theme 只能是 dark 或 light")
    _require(ui.poll_interval_sec >= 1.0, "ui.poll_interval_sec 必须 >= 1")

    return AppConfig(
        mode=mode,
        route=route,
        safety=safety,
        whitelist=whitelist,
        reply=reply,
        llm=llm,
        skills=skills,
        ui=ui,
    )


# ---------------------------------------------------------------------------
# 写回：按模板生成带注释的 TOML（图形界面「保存配置」使用）
# ---------------------------------------------------------------------------

def _toml_str(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _toml_float(value: float) -> str:
    return repr(float(value))


def dump_config_text(cfg: AppConfig) -> str:
    lines: list[str] = []
    add = lines.append
    add("# wxbot 配置文件（可由图形界面「保存配置」自动生成）")
    add("# 安全提醒：默认参数已按保守值设置；白名单为空时「谁都不回」。")
    add("")
    add("[app]")
    add(f"mode = {_toml_str(cfg.mode)}    # dry_run=只记录不发送；auto=真实发送")
    add(f"route = {_toml_str(cfg.route)}")
    add("")
    add("[whitelist]")
    add(f"enabled = {_toml_bool(cfg.whitelist.enabled)}")
    add(f"allow_all = {_toml_bool(cfg.whitelist.allow_all)}")
    add(f"chats = {_toml_list(cfg.whitelist.chats)}")
    add("")
    add("[safety]")
    add(f"quiet_hours = {_toml_list(cfg.safety.quiet_hours)}")
    add(f"max_per_minute = {cfg.safety.max_per_minute}")
    add(f"max_per_hour = {cfg.safety.max_per_hour}")
    add(f"max_per_day = {cfg.safety.max_per_day}")
    add(f"min_reply_delay_sec = {_toml_float(cfg.safety.min_reply_delay_sec)}")
    add(f"max_reply_delay_sec = {_toml_float(cfg.safety.max_reply_delay_sec)}")
    add(f"auto_trip_on_failures = {cfg.safety.auto_trip_on_failures}")
    add("")
    add("[reply]")
    add(f"engine = {_toml_str(cfg.reply.engine)}    # rules=关键词规则；llm=大模型")
    add(f"default_enabled = {_toml_bool(cfg.reply.default_enabled)}")
    add(f"default_text = {_toml_str(cfg.reply.default_text)}")
    for rule in cfg.reply.rules:
        add("")
        add("[[reply.rules]]")
        add(f"keywords = {_toml_list(rule.keywords)}")
        add(f"reply = {_toml_str(rule.reply)}")
    add("")
    add("[llm]")
    add("# 厂商与模型（图形界面「模型」页可一键切换厂商、自动获取模型列表）")
    add(f"provider = {_toml_str(cfg.llm.provider)}")
    add(f"base_url = {_toml_str(cfg.llm.base_url)}")
    add(f"model = {_toml_str(cfg.llm.model)}")
    add(f"api_style = {_toml_str(cfg.llm.api_style)}    # openai 或 anthropic")
    add(f"api_key_env = {_toml_str(cfg.llm.api_key_env)}    # 本地模型留空")
    add(f"temperature = {_toml_float(cfg.llm.temperature)}")
    add(f"max_tokens = {cfg.llm.max_tokens}    # 最大输出")
    add(f"context_length = {cfg.llm.context_length}")
    add(f"modalities = {_toml_list(cfg.llm.modalities)}    # 输入模态")
    add(f"thinking_level = {_toml_str(cfg.llm.thinking_level)}    # auto/off/low/medium/high")
    add(f"timeout_sec = {_toml_float(cfg.llm.timeout_sec)}")
    add(f"system_prompt = {_toml_str(cfg.llm.system_prompt)}")
    add("")
    add("[skills.persona]")
    add(f"enabled = {_toml_bool(cfg.skills.persona.enabled)}")
    add(f"identity = {_toml_str(cfg.skills.persona.identity)}    # 他是谁")
    add(f"description = {_toml_str(cfg.skills.persona.description)}")
    add(f"tone = {_toml_str(cfg.skills.persona.tone)}    # auto/warm/neutral/direct/humorous")
    add(f"formality = {cfg.skills.persona.formality}    # 0=很随意 100=很正式")
    add(f"length = {_toml_str(cfg.skills.persona.length)}    # very_short/short/medium")
    add(f"emoji = {_toml_str(cfg.skills.persona.emoji)}    # never/rare/often")
    add(f"catchphrases = {_toml_list(cfg.skills.persona.catchphrases)}")
    add(f"avoid = {_toml_list(cfg.skills.persona.avoid)}")
    add("")
    add("[skills.memory]")
    add(f"enabled = {_toml_bool(cfg.skills.memory.enabled)}")
    add(f"max_messages = {cfg.skills.memory.max_messages}")
    add("")
    add("[skills.safety]")
    add(f"enabled = {_toml_bool(cfg.skills.safety.enabled)}")
    add(f"banned_topics = {_toml_list(cfg.skills.safety.banned_topics)}")
    add(f"commitment_guard = {_toml_bool(cfg.skills.safety.commitment_guard)}")
    add("")
    add("[skills.group_policy]")
    add(f"enabled = {_toml_bool(cfg.skills.group_policy.enabled)}")
    add(f"require_mention = {_toml_bool(cfg.skills.group_policy.require_mention)}")
    add(f"extra_triggers = {_toml_list(cfg.skills.group_policy.extra_triggers)}")
    add("")
    add("[skills.learned]")
    add(f"enabled = {_toml_bool(cfg.skills.learned.enabled)}")
    add(f"auto_after_replies = {cfg.skills.learned.auto_after_replies}    # 0=仅手动学习")
    add("")
    add("[ui]")
    add(f"theme = {_toml_str(cfg.ui.theme)}    # dark / light")
    add(f"poll_interval_sec = {_toml_float(cfg.ui.poll_interval_sec)}")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 本地密钥（secrets.toml）：绝不写入 config.toml / 日志 / 仓库
# ---------------------------------------------------------------------------

def load_secret_api_key() -> str | None:
    if not SECRETS_PATH.exists():
        return None
    try:
        data = tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None
    key = data.get("llm", {}).get("api_key", "")
    return str(key).strip() or None


def save_secret_api_key(api_key: str) -> None:
    SECRETS_PATH.write_text(
        "# 本地密钥文件（不要提交到版本库）。由图形界面写入，也可手动编辑。\n"
        "[llm]\n"
        f"api_key = {_toml_str(api_key)}\n",
        encoding="utf-8",
    )
