from django.contrib import admin

from notifications.models import EmailDelivery, Notification

admin.site.register(Notification)
admin.site.register(EmailDelivery)
