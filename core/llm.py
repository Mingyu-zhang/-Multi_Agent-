"""
LLM 后端适配层
支持 OpenAI / Azure OpenAI / Anthropic Claude /
文心一言 / 通义千问 / Gemini / Ollama 本地模型
"""
from __future__ import annotations
import asyncio
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class BaseLLM(ABC):
    """LLM 适配器基类"""

    def __init__(self, model: str, **kwargs):
        self.model = model
        self.kwargs = kwargs

    @abstractmethod
    async def chat(self, messages: List[Dict], **kwargs) -> str:
        """多轮对话"""
        ...

    @abstractmethod
    async def stream_chat(self, messages: List[Dict], **kwargs):
        """流式对话（生成器）"""
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__} model={self.model}>"


# ─── OpenAI / Azure OpenAI ────────────────────────────────────────────────────

class OpenAILLM(BaseLLM):
    """OpenAI API 适配器（兼容所有 OpenAI-compatible 接口）"""

    def __init__(self, model: str = "gpt-4o",
                 api_key: str = "",
                 base_url: str = "https://api.openai.com/v1",
                 **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            except ImportError:
                raise RuntimeError("请安装 openai 包: pip install openai")
        return self._client

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        client = self._get_client()
        resp = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            **{**self.kwargs, **kwargs}
        )
        return resp.choices[0].message.content

    async def stream_chat(self, messages: List[Dict], **kwargs):
        client = self._get_client()
        stream = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            **{**self.kwargs, **kwargs}
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ─── Anthropic Claude ─────────────────────────────────────────────────────────

class ClaudeLLM(BaseLLM):
    """Anthropic Claude 适配器"""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022",
                 api_key: str = "", **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("请安装 anthropic 包: pip install anthropic")
        return self._client

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        client = self._get_client()
        # 分离 system prompt
        system = ""
        conv = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                conv.append(m)
        resp = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=conv,
        )
        return resp.content[0].text

    async def stream_chat(self, messages: List[Dict], **kwargs):
        client = self._get_client()
        system = ""
        conv = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                conv.append(m)
        async with client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=conv,
        ) as stream:
            async for text in stream.text_stream:
                yield text


# ─── 文心一言（百度 ERNIE） ────────────────────────────────────────────────────

class WenxinLLM(BaseLLM):
    """百度文心一言适配器"""

    ENDPOINT_MAP = {
        "ernie-4.0-8k": "completions_pro",
        "ernie-3.5-8k": "completions",
        "ernie-speed-128k": "ernie-speed-128k",
    }

    def __init__(self, model: str = "ernie-4.0-8k",
                 api_key: str = "", secret_key: str = "", **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key
        self.secret_key = secret_key

    async def _get_access_token(self) -> str:
        import aiohttp
        url = ("https://aip.baidubce.com/oauth/2.0/token"
               f"?grant_type=client_credentials"
               f"&client_id={self.api_key}&client_secret={self.secret_key}")
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as resp:
                data = await resp.json()
                return data["access_token"]

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        import aiohttp
        token = await self._get_access_token()
        endpoint = self.ENDPOINT_MAP.get(self.model, "completions")
        url = (f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop"
               f"/chat/{endpoint}?access_token={token}")
        conv = [m for m in messages if m["role"] != "system"]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        body = {"messages": conv}
        if system:
            body["system"] = system
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                data = await resp.json()
                return data.get("result", str(data))

    async def stream_chat(self, messages: List[Dict], **kwargs):
        # 简化：调用非流式后分批返回
        result = await self.chat(messages, **kwargs)
        yield result


# ─── 通义千问（阿里云） ────────────────────────────────────────────────────────

class QwenLLM(BaseLLM):
    """阿里通义千问适配器"""

    def __init__(self, model: str = "qwen-max",
                 api_key: str = "", **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            resp = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return resp.choices[0].message.content
        except ImportError:
            raise RuntimeError("请安装 openai 包: pip install openai")

    async def stream_chat(self, messages: List[Dict], **kwargs):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        stream = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ─── Gemini ───────────────────────────────────────────────────────────────────

class GeminiLLM(BaseLLM):
    """Google Gemini 适配器"""

    def __init__(self, model: str = "gemini-1.5-pro",
                 api_key: str = "", **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        import aiohttp
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        body = {"contents": contents}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                data = await resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

    async def stream_chat(self, messages: List[Dict], **kwargs):
        result = await self.chat(messages)
        yield result


# ─── Ollama 本地模型 ───────────────────────────────────────────────────────────

class OllamaLLM(BaseLLM):
    """Ollama 本地模型适配器（支持 llama3/mistral/qwen2 等）"""

    def __init__(self, model: str = "llama3",
                 base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(model, **kwargs)
        self.base_url = base_url.rstrip("/")

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        import aiohttp
        url = f"{self.base_url}/api/chat"
        body = {"model": self.model, "messages": messages, "stream": False}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                data = await resp.json()
                return data["message"]["content"]

    async def stream_chat(self, messages: List[Dict], **kwargs):
        import aiohttp
        url = f"{self.base_url}/api/chat"
        body = {"model": self.model, "messages": messages, "stream": True}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                async for line in resp.content:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if data.get("done"):
                            break


# ─── Mock LLM（用于测试） ──────────────────────────────────────────────────────

class MockLLM(BaseLLM):
    """测试用 Mock LLM"""

    def __init__(self, model: str = "mock", response: str = ""):
        super().__init__(model)
        self._resp = response

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        last = messages[-1]["content"] if messages else ""
        return self._resp or f"[Mock回复] 收到: {last[:50]}"

    async def stream_chat(self, messages: List[Dict], **kwargs):
        resp = await self.chat(messages)
        yield resp


# ─── LLM 工厂 ─────────────────────────────────────────────────────────────────

LLM_REGISTRY: Dict[str, type] = {
    "openai": OpenAILLM,
    "azure": OpenAILLM,           # Azure 用同一个类，改 base_url
    "claude": ClaudeLLM,
    "anthropic": ClaudeLLM,
    "wenxin": WenxinLLM,
    "ernie": WenxinLLM,
    "qwen": QwenLLM,
    "tongyi": QwenLLM,
    "gemini": GeminiLLM,
    "ollama": OllamaLLM,
    "mock": MockLLM,
}


def create_llm(provider: str, **kwargs) -> BaseLLM:
    """
    LLM 工厂函数
    用法示例:
        llm = create_llm("openai", api_key="sk-...", model="gpt-4o")
        llm = create_llm("ollama", model="qwen2")
        llm = create_llm("wenxin", api_key="xxx", secret_key="yyy")
    """
    provider = provider.lower()
    if provider not in LLM_REGISTRY:
        raise ValueError(f"不支持的 LLM 提供商: {provider}，"
                         f"可选: {list(LLM_REGISTRY.keys())}")
    cls = LLM_REGISTRY[provider]
    return cls(**kwargs)
