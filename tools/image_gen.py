# image_gen.py — 硅基流动图片生成工具
# 通过 SiliconFlow API（OpenAI 兼容协议）调用文生图模型

import base64
import time
from pathlib import Path
from openai import OpenAI

# 硅基流动 API 端点
SF_BASE_URL = "https://api.siliconflow.cn/v1"

# 可用模型
AVAILABLE_MODELS = {
    "z-image-turbo": "Tongyi-MAI/Z-Image-Turbo",
    "z-image": "Tongyi-MAI/Z-Image",
    "ernie-image": "baidu/ERNIE-Image-Turbo",
    "kolors": "Kwai-Kolors/Kolors",
    "qwen-image": "Qwen/Qwen-Image",
}

# 默认模型
DEFAULT_MODEL = "Tongyi-MAI/Z-Image-Turbo"

# 支持的尺寸
SUPPORTED_SIZES = ["1024x1024", "1024x768", "768x1024", "512x512", "768x768"]


def _get_client(config: dict) -> OpenAI:
    """获取硅基流动 API 客户端"""
    api_key = config.get("siliconflow_api_key", "")
    if not api_key:
        raise ValueError(
            "未配置 SILICONFLOW_API_KEY。请设置环境变量 SILICONFLOW_API_KEY，"
            "或在 config/.env 中添加 SILICONFLOW_API_KEY=your_key"
        )
    return OpenAI(api_key=api_key, base_url=SF_BASE_URL)


def _resolve_model(model_name: str) -> str:
    """解析模型名称，支持简称"""
    model_lower = model_name.lower()
    if model_lower in AVAILABLE_MODELS:
        return AVAILABLE_MODELS[model_lower]
    # 如果已经是完整模型名，原样返回
    return model_name


def _download_image(url: str, output_path: Path) -> int:
    """从 URL 下载图片到本地，返回文件大小"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "MyAgent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return len(data)


def image_generate(params: dict, config: dict) -> str:
    """
    文生图工具 — 通过硅基流动 API 生成图片。

    参数:
        prompt: 图片描述文本（支持中文和英文）
        model: 模型名称（默认: z-image-turbo）
               可选: z-image-turbo / z-image / ernie-image / kolors / qwen-image
        size: 图片尺寸（默认: 1024x1024）
        n: 生成数量（默认: 1）
        negative_prompt: 负面提示词（可选，排除不想出现的元素）
        output: 输出文件路径（默认: generated_image.png）
    """
    prompt = params.get("prompt", "")
    if not prompt:
        return "Error: 'prompt' parameter is required for image generation."

    model_name = params.get("model", DEFAULT_MODEL)
    size = params.get("size", "1024x1024")
    n = params.get("n", 1)
    negative_prompt = params.get("negative_prompt", "")
    output = params.get("output", "generated_image.png")

    # 校验参数
    if size not in SUPPORTED_SIZES:
        return f"Error: unsupported size '{size}'. Supported: {', '.join(SUPPORTED_SIZES)}"

    if n < 1 or n > 4:
        return "Error: 'n' must be between 1 and 4."

    resolved_model = _resolve_model(model_name)

    # 调用 API
    try:
        client = _get_client(config)

        gen_kwargs = {
            "model": resolved_model,
            "prompt": prompt,
            "n": n,
            "size": size,
        }
        if negative_prompt:
            gen_kwargs["extra_body"] = {"negative_prompt": negative_prompt}

        response = client.images.generate(**gen_kwargs)

        # 处理结果
        output_paths = []
        total_size = 0

        for i, img in enumerate(response.data):
            if img.url:
                # 从 URL 下载
                if n == 1:
                    out_path = Path(output)
                else:
                    # 多张图片时自动编号
                    stem = Path(output).stem
                    suffix = Path(output).suffix or ".png"
                    out_path = Path(output).parent / f"{stem}_{i+1}{suffix}"

                if not out_path.is_absolute():
                    out_path = Path(config.get("cwd", ".")) / out_path

                file_size = _download_image(img.url, out_path)
                output_paths.append(str(out_path))
                total_size += file_size

            elif img.b64_json:
                # base64 直接解码
                if n == 1:
                    out_path = Path(output)
                else:
                    stem = Path(output).stem
                    suffix = Path(output).suffix or ".png"
                    out_path = Path(output).parent / f"{stem}_{i+1}{suffix}"

                if not out_path.is_absolute():
                    out_path = Path(config.get("cwd", ".")) / out_path

                img_bytes = base64.b64decode(img.b64_json)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(img_bytes)
                output_paths.append(str(out_path))
                total_size += len(img_bytes)

        # 构建返回信息
        lines = [
            "Image generation complete!",
            f"  Model: {resolved_model}",
            f"  Size: {size}",
            f"  Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}",
        ]
        if negative_prompt:
            lines.append(f"  Negative prompt: {negative_prompt[:80]}...")

        lines.append(f"  Generated: {n} image(s)")
        for p in output_paths:
            lines.append(f"  Output: {p}")
        lines.append(f"  Total size: {total_size:,} bytes")

        return "\n".join(lines)

    except ValueError as e:
        return str(e)
    except Exception as e:
        error_msg = str(e)
        # 尝试提取 API 返回的详细错误
        if hasattr(e, "body") and e.body:
            try:
                import json
                body = json.loads(e.body) if isinstance(e.body, str) else e.body
                error_msg = body.get("message", error_msg)
            except Exception:
                pass
        return f"Error calling SiliconFlow image API: {error_msg}"


def image_list_models(params: dict, config: dict) -> str:
    """列出所有可用的文生图模型"""
    lines = ["Available image generation models (SiliconFlow):"]
    for short_name, full_name in AVAILABLE_MODELS.items():
        lines.append(f"  {short_name} → {full_name}")
    lines.append("")
    lines.append("Usage: specify model name (short or full) in the 'model' parameter.")
    lines.append(f"Default: {DEFAULT_MODEL}")
    return "\n".join(lines)
