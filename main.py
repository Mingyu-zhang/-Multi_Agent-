"""
三省六部制 Multi-Agent 系统 - 主启动入口
"""
import asyncio
import os
import sys

import uvicorn

# 确保模块路径正确
sys.path.insert(0, os.path.dirname(__file__))

from core.llm import create_llm
from core.system import SanShengLiuBuSystem
from im.adapters import FeishuAdapter, WeChatOAAdapter, DingTalkAdapter
from web.api import app, set_system


# ─── 配置（建议改用 config/settings.yaml 或 .env） ────────────────────────────

CONFIG = {
    # LLM 配置（选择一种）
    "llm": {
        "provider": os.getenv("LLM_PROVIDER", "mock"),   # mock/openai/claude/qwen/wenxin/gemini/ollama
        "model": os.getenv("LLM_MODEL", ""),
        "api_key": os.getenv("LLM_API_KEY", ""),
        "secret_key": os.getenv("LLM_SECRET_KEY", ""),   # 文心一言需要
        "base_url": os.getenv("LLM_BASE_URL", ""),        # 自定义API地址
    },

    # 飞书配置
    "feishu": {
        "enabled": os.getenv("FEISHU_ENABLED", "false").lower() == "true",
        "app_id": os.getenv("FEISHU_APP_ID", ""),
        "app_secret": os.getenv("FEISHU_APP_SECRET", ""),
        "verification_token": os.getenv("FEISHU_VERIFY_TOKEN", ""),
        "encrypt_key": os.getenv("FEISHU_ENCRYPT_KEY", ""),
    },

    # 微信公众号配置
    "wechat_oa": {
        "enabled": os.getenv("WECHAT_OA_ENABLED", "false").lower() == "true",
        "app_id": os.getenv("WECHAT_APP_ID", ""),
        "app_secret": os.getenv("WECHAT_APP_SECRET", ""),
        "token": os.getenv("WECHAT_TOKEN", ""),
    },

    # 钉钉配置
    "dingtalk": {
        "enabled": os.getenv("DINGTALK_ENABLED", "false").lower() == "true",
        "app_key": os.getenv("DINGTALK_APP_KEY", ""),
        "app_secret": os.getenv("DINGTALK_APP_SECRET", ""),
    },

    # Web服务
    "server": {
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT", "8000")),
        "reload": os.getenv("RELOAD", "false").lower() == "true",
    }
}


async def main():
    # 1. 创建LLM
    llm_cfg = CONFIG["llm"]
    provider = llm_cfg.pop("provider", "mock")
    # 过滤空字符串
    kwargs = {k: v for k, v in llm_cfg.items() if v}
    llm = create_llm(provider, **kwargs)
    print(f"[LLM] {llm}")

    # 2. 创建系统（不传 lifespan，由 FastAPI lifespan 控制）
    system = SanShengLiuBuSystem(llm=llm)

    # 3. 初始化IM适配器
    feishu = None
    if CONFIG["feishu"]["enabled"]:
        fc = CONFIG["feishu"]
        feishu = FeishuAdapter(
            system,
            app_id=fc["app_id"],
            app_secret=fc["app_secret"],
            verification_token=fc["verification_token"],
            encrypt_key=fc["encrypt_key"],
        )
        print("[OK] 飞书适配器已启用")

    wechat_oa = None
    if CONFIG["wechat_oa"]["enabled"]:
        wc = CONFIG["wechat_oa"]
        wechat_oa = WeChatOAAdapter(
            system,
            app_id=wc["app_id"],
            app_secret=wc["app_secret"],
            token=wc["token"],
        )
        print("[OK] 微信公众号适配器已启用")

    dingtalk = None
    if CONFIG["dingtalk"]["enabled"]:
        dt = CONFIG["dingtalk"]
        dingtalk = DingTalkAdapter(
            system,
            app_key=dt["app_key"],
            app_secret=dt["app_secret"],
        )
        print("[OK] 钉钉适配器已启用")

    # 4. 注入到 FastAPI
    set_system(system, wechat_oa=wechat_oa, feishu=feishu, dingtalk=dingtalk)

    # 5. 启动系统
    await system.start()

    # 6. 启动Web服务
    sc = CONFIG["server"]
    print(f"\n[系统] 三省六部制 Multi-Agent 系统")
    print(f"   Web 控制台: http://localhost:{sc['port']}")
    print(f"   API 文档:   http://localhost:{sc['port']}/docs")
    print(f"   飞书回调:   http://your-domain:{sc['port']}/feishu")
    print(f"   微信回调:   http://your-domain:{sc['port']}/wechat")
    print()

    config = uvicorn.Config(
        app, host=sc["host"], port=sc["port"],
        reload=sc["reload"], log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
