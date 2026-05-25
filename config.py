# config.py — 配置加载与持久化
# 仅支持 deepseek-v4-pro（OpenAI 兼容协议，cixtech 端点）

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
PROJECT_DIR = Path(__file__).parent
CONFIG_DIR = Path.home() / ".my_agent"

# ===== 单一 Provider 配置 =====
# DeepSeek-V4-Pro（OpenAI 兼容协议）
BASE_URL = "https://aihub.cixtech.com/v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_API_KEY = "sk-qauQRlz8FeTFqBoxGV7IHdErlhetZun5RA7jhXnmKZlDAHQF"

# 单次回复的最大输出 token 数
# 4096 是 GPT-3.5 时代的默认值，对现代模型 + 中文回复来说经常不够
# 8192 在大多数场景下够用，长文档生成可以调到 16384
DEFAULT_MAX_TOKENS = 8192

# 为了向后兼容（main.py 还引用了 PROVIDER_CONFIG 和 detect_provider）
PROVIDER_CONFIG = {
    "deepseek": {
        "base_url": BASE_URL,
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": DEFAULT_MODEL,
    },
}


def detect_provider(model: str) -> str:
    """只有一个 provider"""
    return "deepseek"


def load_config(cwd: str = None) -> dict:
    """加载配置，优先级：环境变量 > .env 文件 > 内置默认值"""
    # 加载 .env 文件（多个位置查找）
    load_dotenv(PROJECT_DIR / ".env")          # 脚本所在目录的 .env
    load_dotenv(Path(cwd or ".") / ".env")     # 工作目录的 .env
    load_dotenv(CONFIG_DIR / ".env")           # ~/.my_agent/.env

    # 允许用环境变量覆盖
    model = os.getenv("AGENT_MODEL", DEFAULT_MODEL)
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AGENT_API_KEY") or DEFAULT_API_KEY
    base_url = os.getenv("AGENT_BASE_URL", BASE_URL)

    config = {
        "model": model,
        "provider": "deepseek",
        "api_key": api_key,
        "base_url": base_url,
        "cwd": cwd or os.getcwd(),
        "permission_mode": os.getenv("AGENT_PERMISSION", "normal"),  # normal | accept-all
        "max_tokens": int(os.getenv("AGENT_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        "temperature": float(os.getenv("AGENT_TEMPERATURE", "0.7")),
    }

    return config


def save_config(config: dict):
    """保存配置到 ~/.my_agent/config.json"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = CONFIG_DIR / "config.json"
    saveable = {k: v for k, v in config.items() if isinstance(v, (str, int, float, bool))}
    config_file.write_text(json.dumps(saveable, indent=2, ensure_ascii=False), encoding="utf-8")
