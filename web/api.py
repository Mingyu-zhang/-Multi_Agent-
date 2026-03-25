"""
FastAPI Web 服务
提供：
1. REST API 接口（直接对话）
2. 微信公众号 Webhook
3. 飞书事件订阅 Webhook
4. 钉钉事件 Webhook
5. Web 管理控制台
"""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, Request, Response, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── 请求/响应 Schema ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    user_id: str = "web_user"
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None


class LLMSwitchRequest(BaseModel):
    provider: str           # openai / claude / qwen / wenxin / ollama / gemini
    model: str = ""
    api_key: str = ""
    secret_key: str = ""    # 文心一言需要
    base_url: str = ""      # 自定义API端点


# ─── 全局系统实例（由 main.py 注入） ──────────────────────────────────────────
_system = None
_wechat_oa = None
_feishu = None
_dingtalk = None


def set_system(system, wechat_oa=None, feishu=None, dingtalk=None):
    global _system, _wechat_oa, _feishu, _dingtalk
    _system = system
    _wechat_oa = wechat_oa
    _feishu = feishu
    _dingtalk = dingtalk


# ─── FastAPI App ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期管理"""
    if _system:
        await _system.start()
    yield
    if _system:
        await _system.stop()


app = FastAPI(
    title="三省六部制 Multi-Agent 系统",
    description="基于中国古代三省六部制构建的多Agent框架",
    version="1.0.0",
    lifespan=lifespan,
)

# 静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ─── 对话接口 ──────────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """REST API 对话接口"""
    if not _system:
        raise HTTPException(500, "系统未初始化")
    reply = await _system.ask(req.message, from_user=req.user_id, im_platform="web")
    return ChatResponse(reply=reply)


@app.get("/api/history")
async def history(session_id: str = None, limit: int = 20):
    """获取消息历史"""
    if not _system:
        raise HTTPException(500, "系统未初始化")
    msgs = _system.get_history(session_id)[-limit:]
    return [
        {
            "id": m.id,
            "sender": m.sender,
            "receiver": m.receiver,
            "type": m.msg_type.value,
            "content": m.content[:200],
            "timestamp": m.timestamp.isoformat(),
            "session_id": m.session_id,
        }
        for m in msgs
    ]


@app.post("/api/llm/switch")
async def switch_llm(req: LLMSwitchRequest):
    """热切换LLM后端"""
    if not _system:
        raise HTTPException(500, "系统未初始化")
    from core.llm import create_llm
    kwargs = {"model": req.model} if req.model else {}
    if req.api_key:
        kwargs["api_key"] = req.api_key
    if req.secret_key:
        kwargs["secret_key"] = req.secret_key
    if req.base_url:
        kwargs["base_url"] = req.base_url
    try:
        llm = create_llm(req.provider, **kwargs)
        _system.switch_llm(llm)
        return {"status": "ok", "llm": str(llm)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/status")
async def status():
    """系统状态"""
    if not _system:
        return {"status": "not_initialized"}
    return {
        "status": "running",
        "llm": str(_system.llm),
        "agents": ["中书省", "门下省", "尚书省", "吏部", "户部", "礼部", "兵部", "刑部", "工部"],
        "message_count": len(_system.bus._history),
    }


# ─── 微信公众号 Webhook ────────────────────────────────────────────────────────

@app.get("/wechat")
async def wechat_verify(signature: str, timestamp: str, nonce: str, echostr: str):
    """微信公众号接入验证"""
    if _wechat_oa and _wechat_oa.verify_signature(signature, timestamp, nonce):
        return Response(content=echostr, media_type="text/plain")
    raise HTTPException(403, "验证失败")


@app.post("/wechat")
async def wechat_message(request: Request):
    """接收微信公众号消息"""
    if not _wechat_oa:
        return Response(content="success", media_type="text/plain")
    body = await request.body()
    reply_xml = await _wechat_oa.handle_message(body.decode("utf-8"))
    return Response(content=reply_xml, media_type="application/xml")


# ─── 飞书 Webhook ──────────────────────────────────────────────────────────────

@app.post("/feishu")
async def feishu_event(request: Request):
    """接收飞书事件推送"""
    if not _feishu:
        return JSONResponse({"msg": "not configured"})
    body = await request.json()
    result = await _feishu.handle_event(body)
    return JSONResponse(result)


# ─── 钉钉 Webhook ──────────────────────────────────────────────────────────────

@app.post("/dingtalk")
async def dingtalk_event(request: Request):
    """接收钉钉消息"""
    if not _dingtalk:
        return JSONResponse({"msgtype": "empty"})
    body = await request.json()
    result = await _dingtalk.handle_event(body)
    return JSONResponse(result)


# ─── Web 控制台 ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def console():
    """Web管理控制台"""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(template_path):
        with open(template_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>三省六部制 Multi-Agent 系统正在运行</h1><p>请配置 templates/index.html</p>"
