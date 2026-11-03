from django.urls import path

from notifications.consumers import LiveConsumer

websocket_urlpatterns = [
    path("ws/live/", LiveConsumer.as_asgi()),
]
