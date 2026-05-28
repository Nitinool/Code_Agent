# tts.py — MiMo-V2.5-TTS 语音合成工具
# 通过 Xiaomi MiMo API（OpenAI 兼容协议）将文本转为语音

import os
import base64
from pathlib import Path
from openai import OpenAI

# MiMo TTS API 端点
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"

# 预置音色列表
PRESET_VOICES = {
    "默认": "mimo_default",
    "冰糖": "冰糖",
    "茉莉": "茉莉",
    "苏打": "苏打",
    "白桦": "白桦",
    "Mia": "Mia",
    "Chloe": "Chloe",
    "Milo": "Milo",
    "Dean": "Dean",
}

# 支持的音频格式
SUPPORTED_FORMATS = ["wav", "mp3", "pcm16"]


def _get_mimo_client(config: dict) -> OpenAI:
    """获取 MiMo API 客户端"""
    api_key = os.getenv("MIMO_API_KEY") or config.get("mimo_api_key", "")
    if not api_key:
        raise ValueError(
            "未配置 MIMO_API_KEY。请设置环境变量 MIMO_API_KEY，"
            "或在 ~/.my_agent/.env 中添加 MIMO_API_KEY=your_key"
        )
    return OpenAI(api_key=api_key, base_url=MIMO_BASE_URL)


def _resolve_voice(voice: str) -> str:
    """解析音色名称，支持中文名和 Voice ID"""
    if voice in PRESET_VOICES:
        return PRESET_VOICES[voice]
    # 如果直接传了 Voice ID，原样返回
    return voice


def tts_synthesize(params: dict, config: dict) -> str:
    """
    语音合成工具 — 将文本转为语音文件。

    参数:
        text: 要合成的文本内容
        voice: 音色名称（默认: 冰糖），可选: 冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean
        style: 风格描述（自然语言，可选），如 "轻快上扬的语调，语速稍快"
        format: 输出音频格式（默认: wav），可选: wav/mp3/pcm16
        output: 输出文件路径（默认: tts_output.wav）
        model: TTS 模型（默认: mimo-v2.5-tts）
               - mimo-v2.5-tts: 预置音色
               - mimo-v2.5-tts-voicedesign: 文本设计音色
               - mimo-v2.5-tts-voiceclone: 音色复刻（需提供 voice_sample）
        voice_sample: 音色复刻用的音频文件路径（仅 voiceclone 模型需要）
    """
    text = params.get("text", "")
    if not text:
        return "Error: 'text' parameter is required for TTS synthesis."

    voice = params.get("voice", "冰糖")
    style = params.get("style", "")
    audio_format = params.get("format", "wav")
    output_path = params.get("output", "tts_output.wav")
    model = params.get("model", "mimo-v2.5-tts")
    voice_sample = params.get("voice_sample", "")

    # 校验格式
    if audio_format not in SUPPORTED_FORMATS:
        return f"Error: unsupported format '{audio_format}'. Supported: {', '.join(SUPPORTED_FORMATS)}"

    # 解析音色
    resolved_voice = _resolve_voice(voice)

    # 音色复刻模式：读取音频样本
    if model == "mimo-v2.5-tts-voiceclone":
        if not voice_sample:
            return "Error: 'voice_sample' parameter is required for voiceclone model."
        sample_path = Path(voice_sample)
        if not sample_path.exists():
            return f"Error: voice sample file not found: {voice_sample}"
        try:
            sample_bytes = sample_path.read_bytes()
            sample_b64 = base64.b64encode(sample_bytes).decode("utf-8")
            # 根据扩展名推断 MIME 类型
            suffix = sample_path.suffix.lower()
            mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                        ".m4a": "audio/mp4", ".flac": "audio/flac", ".aac": "audio/aac"}
            mime_type = mime_map.get(suffix, "audio/mpeg")
            resolved_voice = f"data:{mime_type};base64,{sample_b64}"
        except Exception as e:
            return f"Error reading voice sample: {e}"

    # 构建消息
    messages = [
        {
            "role": "user",
            "content": style if style else "",
        },
        {
            "role": "assistant",
            "content": text,
        },
    ]

    # 调用 MiMo TTS API
    try:
        client = _get_mimo_client(config)

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            audio={
                "format": audio_format,
                "voice": resolved_voice,
            },
        )

        # 解析响应
        message = completion.choices[0].message
        if hasattr(message, "audio") and message.audio:
            audio_data = message.audio.data
            audio_bytes = base64.b64decode(audio_data)

            # 写入文件
            out = Path(output_path)
            if not out.is_absolute():
                out = Path(config.get("cwd", ".")) / out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(audio_bytes)

            duration_ms = getattr(message.audio, "duration", 0) or 0
            duration_s = duration_ms / 1000 if duration_ms else "?"

            return (
                f"TTS synthesis complete!\n"
                f"  Voice: {voice}\n"
                f"  Model: {model}\n"
                f"  Format: {audio_format}\n"
                f"  Duration: {duration_s}s\n"
                f"  Output: {out}\n"
                f"  Size: {len(audio_bytes)} bytes"
            )
        else:
            return f"Error: no audio data in response. Content: {message.content}"

    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error calling MiMo TTS API: {e}"


def tts_list_voices(params: dict, config: dict) -> str:
    """列出所有可用的预置音色"""
    lines = ["Available preset voices:"]
    for name, voice_id in PRESET_VOICES.items():
        lines.append(f"  {name} (Voice ID: {voice_id})")
    return "\n".join(lines)