"""
核心基类模块
三省六部制 Multi-Agent 系统
"""
from __future__ import annotations
import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class MessageType(Enum):
    """消息类型"""
    USER_INPUT = "user_input"       # 用户输入
    TASK = "task"                   # 任务下达
    RESULT = "result"               # 任务结果
    REVIEW = "review"               # 审阅请求
    APPROVAL = "approval"           # 批准/驳回
    EXECUTE = "execute"             # 执行命令
    REPORT = "report"               # 上报
    SYSTEM = "system"               # 系统消息


class Priority(Enum):
    """优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class Message:
    """消息体 - 三省六部间传递的公文"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    sender: str = ""                          # 发送方（官署名）
    receiver: str = ""                        # 接收方（官署名）
    msg_type: MessageType = MessageType.TASK
    content: str = ""                         # 消息内容
    context: Dict[str, Any] = field(default_factory=dict)  # 上下文
    priority: Priority = Priority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)
    parent_id: Optional[str] = None           # 关联消息ID（回复链）
    session_id: str = ""                      # 会话/请求ID

    def reply(self, sender: str, content: str,
              msg_type: MessageType = MessageType.RESULT) -> "Message":
        """生成回复消息"""
        return Message(
            sender=sender,
            receiver=self.sender,
            msg_type=msg_type,
            content=content,
            context=self.context.copy(),
            priority=self.priority,
            parent_id=self.id,
            session_id=self.session_id,
        )


class MessageBus:
    """
    消息总线 - 三省六部间的邸报传递系统
    各官署通过总线订阅/发布消息
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._history: List[Message] = []

    def subscribe(self, agent_name: str, handler: Callable):
        """订阅消息（注册官署）"""
        if agent_name not in self._subscribers:
            self._subscribers[agent_name] = []
        self._subscribers[agent_name].append(handler)

    async def publish(self, message: Message):
        """发布消息（传递公文）"""
        self._history.append(message)
        await self._queue.put(message)

    async def start(self):
        """启动消息总线"""
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                receiver = msg.receiver
                if receiver in self._subscribers:
                    for handler in self._subscribers[receiver]:
                        asyncio.create_task(handler(msg))
                elif receiver == "broadcast":
                    for handlers in self._subscribers.values():
                        for h in handlers:
                            asyncio.create_task(h(msg))
            except asyncio.TimeoutError:
                pass

    def stop(self):
        self._running = False

    def get_history(self, session_id: str = None, limit: int = 50) -> List[Message]:
        """获取消息历史"""
        hist = self._history
        if session_id:
            hist = [m for m in hist if m.session_id == session_id]
        return hist[-limit:]


class BaseAgent(ABC):
    """
    官署基类
    三省六部中每个官署都继承此类
    """

    def __init__(self, name: str, title: str, bus: MessageBus,
                 llm_backend=None, system_prompt: str = ""):
        self.name = name          # 官署代号，如 "zhongshu"
        self.title = title        # 官署名称，如 "中书省"
        self.bus = bus
        self.llm = llm_backend
        self.system_prompt = system_prompt
        self.memory: List[Dict] = []   # 官署记忆（上下文）
        self._active = False

        # 注册到消息总线
        bus.subscribe(name, self._on_message)

    async def _on_message(self, message: Message):
        """收到消息时的处理入口"""
        try:
            await self.handle(message)
        except Exception as e:
            err_msg = message.reply(
                self.name,
                f"[{self.title}] 处理出错: {str(e)}",
                MessageType.REPORT
            )
            await self.bus.publish(err_msg)

    @abstractmethod
    async def handle(self, message: Message):
        """处理消息（子类实现）"""
        ...

    async def think(self, prompt: str, context: List[Dict] = None) -> str:
        """调用LLM进行思考"""
        if self.llm is None:
            return f"[{self.title}] 无LLM后端，无法思考"

        messages = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.extend(context)
        messages.append({"role": "user", "content": prompt})

        return await self.llm.chat(messages)

    async def send(self, receiver: str, content: str,
                   msg_type: MessageType = MessageType.TASK,
                   session_id: str = "",
                   context: Dict = None):
        """向其他官署发送消息"""
        msg = Message(
            sender=self.name,
            receiver=receiver,
            msg_type=msg_type,
            content=content,
            context=context or {},
            session_id=session_id,
        )
        await self.bus.publish(msg)

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def __repr__(self):
        return f"<Agent {self.title}({self.name})>"
