from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import MODULES, RolePermission


def permissions_of(role_id):
    rows = {p.module: p.as_list() for p in RolePermission.objects.filter(role_id=role_id)}
    return {module: rows.get(module, [False] * 5) for module, _ in MODULES}


class MeSerializer(serializers.Serializer):
    """Profil de l'utilisateur connecté : ce que l'interface a besoin de savoir, rien de plus."""

    def to_representation(self, user):
        role = user.role
        return {
            "id": user.id,
            "username": user.username,
            "name": user.display_name,
            "email": user.email,
            "title": user.title,
            "role": {"code": role.code, "label": role.label} if role else None,
            "isAdmin": user.is_app_admin,
            "mustChangePassword": user.must_change_password,
            "permissions": permissions_of(user.role_id) if role else {},
        }


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate(self, data):
        user = self.context["request"].user
        if not user.check_password(data["current_password"]):
            raise serializers.ValidationError({"current_password": "Mot de passe actuel incorrect."})
        if data["new_password"] == data["current_password"]:
            raise serializers.ValidationError({"new_password": "Le nouveau mot de passe doit être différent de l'actuel."})
        validate_new_password(data["new_password"], user)
        return data


def validate_new_password(password, user=None, field="new_password"):
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({field: exc.messages}) from exc
