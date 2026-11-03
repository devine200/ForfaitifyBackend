import json
import logging
from urllib.parse import parse_qs, unquote

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)
User = get_user_model()


@database_sync_to_async
def user_from_token(raw: str):
    try:
        token = AccessToken(raw)
        return User.objects.get(id=token["user_id"])
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError):
        return None


class LiveConsumer(AsyncWebsocketConsumer):
    """Authenticated live bus: invalidate signals + notification.created."""

    user = None
    user_group = None
    rooms: set[str]

    async def connect(self):
        self.rooms = set()
        self.user = AnonymousUser()
        self.user_group = None

        qs = self.scope.get("query_string", b"").decode()
        params = parse_qs(qs)
        token_list = params.get("token") or []
        token = unquote(token_list[0]) if token_list else None
        if token:
            user = await user_from_token(token)
            if user is None or not user.is_active:
                await self.close(code=4001)
                return
            self.user = user
            await self._join_user_groups()
            await self.accept()
            await self.send_json({"v": 1, "type": "connected", "ts": None})
            return

        # Accept first, expect auth message within handshake
        await self.accept()

    async def _join_user_groups(self):
        self.user_group = f"user.{self.user.id}"
        await self.channel_layer.group_add(self.user_group, self.channel_name)
        if getattr(self.user, "is_admin", False):
            await self.channel_layer.group_add("role.admin", self.channel_name)

    async def disconnect(self, code):
        if self.user_group:
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
        if getattr(self.user, "is_admin", False):
            await self.channel_layer.group_discard("role.admin", self.channel_name)
        for room in list(self.rooms):
            await self.channel_layer.group_discard(room, self.channel_name)
        self.rooms.clear()

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        msg_type = data.get("type")
        if msg_type == "auth":
            if getattr(self.user, "is_authenticated", False):
                return
            user = await user_from_token(data.get("token") or "")
            if user is None or not user.is_active:
                await self.close(code=4001)
                return
            self.user = user
            await self._join_user_groups()
            await self.send_json({"v": 1, "type": "connected", "ts": None})
            return
        if not getattr(self.user, "is_authenticated", False):
            await self.close(code=4001)
            return
        if msg_type == "ping":
            await self.send_json({"v": 1, "type": "pong"})
            return
        if msg_type == "subscribe":
            room = self._parse_room(data.get("room"))
            if room and room not in self.rooms:
                await self.channel_layer.group_add(room, self.channel_name)
                self.rooms.add(room)
            return
        if msg_type == "unsubscribe":
            room = self._parse_room(data.get("room"))
            if room and room in self.rooms:
                await self.channel_layer.group_discard(room, self.channel_name)
                self.rooms.discard(room)

    def _parse_room(self, raw: str | None) -> str | None:
        if not raw or "|" not in raw:
            return None
        kind, rid = raw.split("|", 1)
        if kind == "invoice" and rid:
            return f"invoice.{rid}"
        if kind == "ticket" and rid:
            return f"ticket.{rid}"
        return None

    async def live_event(self, event):
        message = event.get("message") or {}
        await self.send_json(message)

    async def send_json(self, content):
        await self.send(text_data=json.dumps(content))
