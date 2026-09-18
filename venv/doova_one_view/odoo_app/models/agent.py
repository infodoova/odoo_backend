from django.db import models
import uuid

class ChatSession(models.Model):
    session_id = models.CharField(max_length=255, unique=True, primary_key=True)
    title = models.CharField(max_length=255, default="New Chat")
    summary = models.TextField(blank=True, default="")
    plan_state = models.JSONField(null=True, blank=True)
    plan_created_at = models.DateTimeField(null=True, blank=True)
    active_date_window = models.JSONField(null=True, blank=True)
    active_tenant_ids = models.JSONField(null=True, blank=True)
    active_company_ids = models.JSONField(null=True, blank=True)
    turn_count = models.IntegerField(default=0)
    tenant_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = 'agent_chat_sessions'
        ordering = ['-updated_at']

class ChatMessage(models.Model):
    id = models.AutoField(primary_key=True)
    session = models.ForeignKey(ChatSession, related_name='messages', on_delete=models.CASCADE)
    role = models.CharField(max_length=50) # 'user' or 'assistant'
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    message_type = models.CharField(max_length=50, default="text") # 'text', 'chart', etc.
    payload = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'agent_chat_messages'
        ordering = ['created_at']
