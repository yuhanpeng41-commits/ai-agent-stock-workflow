"""Check credentials without printing them. Run from the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
webhook = os.getenv("FEISHU_WEBHOOK", "")
print("FEISHU_WEBHOOK:", "已配置" if webhook else "未配置")
print("FEISHU_SECRET:", "已配置" if os.getenv("FEISHU_SECRET") else "未配置（未启用签名时可留空）")
