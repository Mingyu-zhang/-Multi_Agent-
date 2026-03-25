"""
IM 集成模块 - 微信、飞书 接口适配
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class IMAdapter(ABC):
    """IM适配器基类"""

    def __init__(self, system):
        self.system = system

    @abstractmethod
    async def start(self):
        """启动监听"""
        ...

    @abstractmethod
    async def stop(self):
        """停止监听"""
        ...

    @abstractmethod
    async def send_message(self, to_user: str, content: str, **kwargs):
        """发送消息"""
        ...


# ─── 微信个人号（gewechat/itchat） ────────────────────────────────────────────

class WeChatAdapter(IMAdapter):
    """
    微信个人号适配器
    底层支持两种方案：
    1. itchat（网页微信协议，已逐步受限）
    2. gewechat / wechaty（Hook方案，需配置代理）
    """

    def __init__(self, system, mode: str = "itchat",
                 webhook_url: str = "",
                 gewechat_base_url: str = "http://localhost:2531",
                 gewechat_token: str = ""):
        super().__init__(system)
        self.mode = mode
        self.webhook_url = webhook_url
        self.gewechat_base_url = gewechat_base_url
        self.gewechat_token = gewechat_token
        self._running = False

    async def start(self):
        if self.mode == "itchat":
            await self._start_itchat()
        elif self.mode == "gewechat":
            await self._start_gewechat()

    async def _start_itchat(self):
        """itchat 登录（扫码）"""
        try:
            import itchat
            self._itchat = itchat

            @itchat.msg_register([itchat.content.TEXT])
            def _on_text(msg):
                content = msg["Text"]
                from_user = msg["FromUserName"]
                nickname = msg.get("User", {}).get("NickName", from_user)
                asyncio.create_task(
                    self._process_message(content, from_user, nickname)
                )

            itchat.auto_login(hotReload=True)
            self._running = True
            print("[OK] 微信(itchat)已登录，等待消息...")
            itchat.run(blockThread=False)
        except ImportError:
            print("⚠️  itchat 未安装，请运行: pip install itchat")

    async def _start_gewechat(self):
        """gewechat HTTP 回调模式"""
        print(f"[OK] 微信(gewechat)监听模式已启动，回调URL: {self.webhook_url}")
        self._running = True

    async def _process_message(self, content: str, from_user: str, nickname: str):
        """处理收到的微信消息"""
        reply = await self.system.ask(
            content=content,
            from_user=from_user,
            im_platform="wechat",
        )
        await self.send_message(from_user, reply)

    async def handle_webhook(self, data: Dict) -> str:
        """处理 gewechat webhook 回调"""
        msg_type = data.get("msgType", "")
        if msg_type == "text":
            content = data.get("content", "")
            from_user = data.get("fromUserName", "")
            asyncio.create_task(self._process_message(content, from_user, from_user))
        return "ok"

    async def send_message(self, to_user: str, content: str, **kwargs):
        if self.mode == "itchat":
            try:
                self._itchat.send(content, toUserName=to_user)
            except Exception as e:
                print(f"微信发送失败: {e}")
        elif self.mode == "gewechat":
            import aiohttp
            url = f"{self.gewechat_base_url}/v2/api/message/postText"
            body = {
                "appId": self.gewechat_token,
                "toWxid": to_user,
                "content": content,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body) as resp:
                    result = await resp.json()
                    return result

    async def stop(self):
        self._running = False
        if self.mode == "itchat":
            try:
                self._itchat.logout()
            except Exception:
                pass


# ─── 微信公众号 / 企业微信 ─────────────────────────────────────────────────────

class WeChatOAAdapter(IMAdapter):
    """
    微信公众号适配器
    通过公众号消息推送接入
    需要在微信公众平台配置服务器URL
    """

    def __init__(self, system, app_id: str, app_secret: str, token: str):
        super().__init__(system)
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = token
        self._access_token = ""
        self._token_expires = 0

    async def _refresh_token(self):
        import aiohttp
        url = (f"https://api.weixin.qq.com/cgi-bin/token"
               f"?grant_type=client_credential&appid={self.app_id}&secret={self.app_secret}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data["expires_in"] - 60

    def verify_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        """验证微信消息签名"""
        items = sorted([self.token, timestamp, nonce])
        check_str = "".join(items)
        check_hash = hashlib.sha1(check_str.encode()).hexdigest()
        return check_hash == signature

    async def handle_message(self, xml_data: str) -> str:
        """处理公众号XML消息，返回XML回复"""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_data)
        msg_type = root.findtext("MsgType", "")
        from_user = root.findtext("FromUserName", "")
        to_user = root.findtext("ToUserName", "")
        content = root.findtext("Content", "")

        if msg_type != "text":
            return self._xml_reply(from_user, to_user, "暂时只支持文字消息")

        reply = await self.system.ask(content, from_user=from_user, im_platform="wechat_oa")

        return self._xml_reply(from_user, to_user, reply)

    def _xml_reply(self, to_user, from_user, content):
        ts = int(time.time())
        return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{ts}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""

    async def send_message(self, to_user: str, content: str, **kwargs):
        """主动推送客服消息（需要48小时窗口期）"""
        if time.time() > self._token_expires:
            await self._refresh_token()
        import aiohttp
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self._access_token}"
        body = {
            "touser": to_user,
            "msgtype": "text",
            "text": {"content": content}
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                return await resp.json()

    async def start(self):
        print("[OK] 微信公众号适配器已就绪（需挂载到 FastAPI /wechat 路由）")

    async def stop(self):
        pass


# ─── 飞书 Lark ────────────────────────────────────────────────────────────────

class FeishuAdapter(IMAdapter):
    """
    飞书机器人适配器
    通过飞书开放平台 Event API 接收消息
    需要在飞书开发者控制台配置事件订阅回调URL
    """

    def __init__(self, system,
                 app_id: str, app_secret: str,
                 verification_token: str = "",
                 encrypt_key: str = ""):
        super().__init__(system)
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self._access_token = ""
        self._token_expires = 0

    async def _refresh_token(self):
        import aiohttp
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        body = {"app_id": self.app_id, "app_secret": self.app_secret}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                data = await resp.json()
                self._access_token = data.get("tenant_access_token", "")
                self._token_expires = time.time() + data.get("expire", 7000) - 60

    def _decrypt(self, encrypt: str) -> dict:
        """解密飞书加密消息"""
        if not self.encrypt_key:
            return {}
        import base64
        from Crypto.Cipher import AES

        key = hashlib.sha256(self.encrypt_key.encode()).digest()
        data = base64.b64decode(encrypt)
        iv = data[:16]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(data[16:])
        # 去除填充
        padding = decrypted[-1]
        decrypted = decrypted[:-padding]
        return json.loads(decrypted)

    async def handle_event(self, body: Dict) -> Dict:
        """处理飞书事件推送"""
        # URL验证
        if "challenge" in body:
            return {"challenge": body["challenge"]}

        # 解密（如果启用了加密）
        if "encrypt" in body:
            body = self._decrypt(body["encrypt"])

        event_type = body.get("header", {}).get("event_type", "")

        if event_type == "im.message.receive_v1":
            event = body.get("event", {})
            msg = event.get("message", {})
            sender = event.get("sender", {})

            msg_type = msg.get("message_type", "")
            if msg_type == "text":
                content = json.loads(msg.get("content", "{}")).get("text", "")
                sender_id = sender.get("sender_id", {}).get("open_id", "")
                chat_id = msg.get("chat_id", "")
                msg_id = msg.get("message_id", "")

                # 避免重复处理
                asyncio.create_task(
                    self._process_message(content, sender_id, chat_id, msg_id)
                )

        return {"msg": "ok"}

    async def _process_message(self, content: str, sender_id: str,
                                chat_id: str, msg_id: str):
        """处理飞书消息"""
        reply = await self.system.ask(
            content=content,
            from_user=sender_id,
            im_platform="feishu",
        )
        await self.send_message(chat_id, reply)

    async def send_message(self, chat_id: str, content: str,
                           msg_type: str = "text", **kwargs):
        """发送飞书消息"""
        if time.time() > self._token_expires:
            await self._refresh_token()

        import aiohttp
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {"receive_id_type": "chat_id"}

        if msg_type == "text":
            body_content = json.dumps({"text": content})
        else:
            body_content = content  # card/image等

        body = {
            "receive_id": chat_id,
            "msg_type": msg_type,
            "content": body_content,
        }
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params, json=body, headers=headers) as resp:
                return await resp.json()

    async def send_card(self, chat_id: str, card_content: Dict):
        """发送飞书卡片消息（富文本）"""
        await self.send_message(
            chat_id,
            json.dumps(card_content),
            msg_type="interactive"
        )

    async def start(self):
        print("[OK] 飞书适配器已就绪（需挂载到 FastAPI /feishu 路由）")

    async def stop(self):
        pass


# ─── 钉钉 ─────────────────────────────────────────────────────────────────────

class DingTalkAdapter(IMAdapter):
    """
    钉钉机器人适配器
    支持企业内部应用消息
    """

    def __init__(self, system, app_key: str, app_secret: str):
        super().__init__(system)
        self.app_key = app_key
        self.app_secret = app_secret
        self._access_token = ""
        self._token_expires = 0

    async def _refresh_token(self):
        import aiohttp
        url = "https://oapi.dingtalk.com/gettoken"
        params = {"appkey": self.app_key, "appsecret": self.app_secret}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                self._access_token = data.get("access_token", "")
                self._token_expires = time.time() + data.get("expires_in", 7000) - 60

    async def handle_event(self, body: Dict) -> Dict:
        """处理钉钉事件"""
        event_type = body.get("msgtype", "")
        if event_type == "text":
            content = body.get("text", {}).get("content", "").strip()
            sender_id = body.get("senderStaffId", "")
            conversation_id = body.get("conversationId", "")

            asyncio.create_task(
                self._process_message(content, sender_id, conversation_id)
            )
        return {"msgtype": "empty"}

    async def _process_message(self, content: str, sender_id: str, conv_id: str):
        reply = await self.system.ask(content, from_user=sender_id, im_platform="dingtalk")
        await self.send_message(conv_id, reply)

    async def send_message(self, to_user: str, content: str, **kwargs):
        if time.time() > self._token_expires:
            await self._refresh_token()
        import aiohttp
        url = "https://oapi.dingtalk.com/topapi/message/orgchat/send"
        body = {
            "msg": {"msgtype": "text", "text": {"content": content}},
            "to": {"conversation_id": to_user}
        }
        headers = {"x-acs-dingtalk-access-token": self._access_token}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                return await resp.json()

    async def start(self):
        print("[OK] 钉钉适配器已就绪")

    async def stop(self):
        pass


# ─── Telegram ─────────────────────────────────────────────────────────────────

class TelegramAdapter(IMAdapter):
    """Telegram Bot 适配器"""

    def __init__(self, system, bot_token: str):
        super().__init__(system)
        self.bot_token = bot_token
        self._bot = None

    async def start(self):
        try:
            from telegram.ext import ApplicationBuilder, MessageHandler, filters
            from telegram import Update
            from telegram.ext import ContextTypes

            async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
                text = update.message.text
                user_id = str(update.message.from_user.id)
                chat_id = update.message.chat_id
                reply = await self.system.ask(text, from_user=user_id, im_platform="telegram")
                await context.bot.send_message(chat_id=chat_id, text=reply)

            app = ApplicationBuilder().token(self.bot_token).build()
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
            self._app = app
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            print("[OK] Telegram Bot 已启动")
        except ImportError:
            print("⚠️  请安装: pip install python-telegram-bot")

    async def send_message(self, to_user: str, content: str, **kwargs):
        if self._app:
            await self._app.bot.send_message(chat_id=int(to_user), text=content)

    async def stop(self):
        if self._app:
            await self._app.stop()
