from __future__ import annotations

from typing import Any, Dict

from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(
        required=True, write_only=True,
        style={'input_type': 'password'},
    )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        raw = (attrs.get('username') or '').strip()
        password = (attrs.get('password') or '').strip()

        if '@' in raw:
            try:
                user = User.objects.get(email=raw)
                username = user.username
            except User.DoesNotExist:
                raise serializers.ValidationError('Invalid credentials.')
        else:
            username = raw

        user = authenticate(username=username, password=password)

        if not user:
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('User account is disabled.')

        attrs['user'] = user
        return attrs
