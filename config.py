# config.py — 配置加载与持久化

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
PROJECT_DIR = Path(__file__).parent
CONFIG_DIR = Path.home() / ".my_agent"

# ===== Provider 配置映射 =====
# 智谱清言和百炼千问都兼容 OpenAI API 格式
PROVIDER_CONFIG = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY",
        "default_model": "glm-4-plus",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "QWEN_API_KEY",
        "default_model": "qwen-plus",
    },
    "openai": {
        "base_url": None,  # 使用 OpenAI 默认地址
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
}

# 模型名 → provider 自动推断
MODEL_PREFIX_MAP = {
    "glm-": "zhipu",
    "qwen-": "qwen",
    "gpt-": "openai",
}


def detect_provider(model: str) -> str:
    """根据模型名推断 provider（大小写不敏感）"""
    model_lower = model.lower()
    for prefix, provider in MODEL_PREFIX_MAP.items():
        if model_lower.startswith(prefix):
            return provider
    return "openai"  # 默认回退


def load_config(cwd: str = None) -> dict:
    """加载配置，优先级：环境变量 > .env 文件 > 默认值"""
    # 加载 .env 文件（多个位置查找）
    load_dotenv(PROJECT_DIR / ".env")          # 脚本所在目录的 .env
    load_dotenv(Path(cwd or ".") / ".env")     # 工作目录的 .env
    load_dotenv(CONFIG_DIR / ".env")           # ~/.my_agent/.env

    model = os.getenv("AGENT_MODEL", "qwen-plus")
    provider = detect_provider(model)

    # 如果用户显式指定了 provider，优先使用
    explicit_provider = os.getenv("AGENT_PROVIDER")
    if explicit_provider and explicit_provider in PROVIDER_CONFIG:
        provider = explicit_provider

    pconf = PROVIDER_CONFIG[provider]

    # 获取 API Key
    api_key = os.getenv(pconf["env_key"], "")

    config = {
        "model": model,
        "provider": provider,
        "api_key": api_key,
        "base_url": pconf["base_url"],
        "cwd": cwd or os.getcwd(),
        "permission_mode": os.getenv("AGENT_PERMISSION", "normal"),  # normal | accept-all
        "max_tokens": int(os.getenv("AGENT_MAX_TOKENS", "4096")),
        "temperature": float(os.getenv("AGENT_TEMPERATURE", "0.7")),
    }

    return config


def save_config(config: dict):
    """保存配置到 ~/.my_agent/config.json"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = CONFIG_DIR / "config.json"
    # 只保存可序列化的字段
    saveable = {k: v for k, v in config.items() if isinstance(v, (str, int, float, bool))}
    config_file.write_text(json.dumps(saveable, indent=2, ensure_ascii=False), encoding="utf-8")
