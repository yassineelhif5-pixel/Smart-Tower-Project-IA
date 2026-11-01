import secrets

from django.contrib.auth import get_user_model
from rest_framework import serializers

from accounts.models import ADMIN_ROLE, PLATFORM_ROLE, Role
from accounts.serializers import validate_new_password
from projects.models import Client

User = get_user_model()


def temporary_password():
    return secrets.token_urlsafe(12)


def active_admin_count(tenant):
    return User.objects.filter(tenant=tenant, role_id=ADMIN_ROLE, is_active=True).count()


class AdminUserSerializer(serializers.ModelSerializer):
    # Le rôle Pilote n'est jamais attribuable depuis un tenant ; le client doit appartenir au même tenant.
    role = serializers.SlugRelatedField(slug_field="code", queryset=Role.objects.exclude(code=PLATFORM_ROLE))
    client = serializers.SlugRelatedField(slug_field="code", queryset=Client.objects.all(), allow_null=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant = getattr(getattr(request, "user", None), "tenant", None)
        self.fields["client"].queryset = Client.objects.filter(tenant=tenant) if tenant else Client.objects.none()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False, max_length=128)
    projectCount = serializers.SerializerMethodField()
    mustChangePassword = serializers.BooleanField(source="must_change_password", read_only=True)
    lastLogin = serializers.DateTimeField(source="last_login", read_only=True)
    firstName = serializers.CharField(source="first_name", required=False, allow_blank=True, max_length=150)
    lastName = serializers.CharField(source="last_name", required=False, allow_blank=True, max_length=150)
    isActive = serializers.BooleanField(source="is_active", required=False)

    class Meta:
        model = User
        fields = ["id", "username", "firstName", "lastName", "email", "role", "title", "team", "client",
                  "isActive", "mustChangePassword", "lastLogin", "projectCount", "password"]

    def get_projectCount(self, user):
        return user.project_accesses.count()

    def validate(self, data):
        instance = self.instance
        role = data.get("role", instance.role if instance else None)
        client = data.get("client", instance.client if instance else None)
        if role is None:
            raise serializers.ValidationError({"role": "Le rôle est obligatoire."})
        if not role.internal and client is None:
            raise serializers.ValidationError({"client": "Un compte du portail client doit être rattaché à un client."})
        if role.internal:
            data["client"] = None
        request_user = self.context["request"].user
        if instance is not None and instance.role_id == ADMIN_ROLE and instance.is_active:
            losing_admin = role.code != ADMIN_ROLE or data.get("is_active", True) is False
            if losing_admin and instance.pk == request_user.pk:
                raise serializers.ValidationError(
                    {"role": "Vous ne pouvez pas retirer votre propre rôle d'administrateur ni désactiver votre compte."})
            if losing_admin and active_admin_count(instance.tenant) <= 1:
                raise serializers.ValidationError({"role": "Il doit rester au moins un administrateur actif."})
        password = data.get("password")
        if password:
            validate_new_password(password, field="password")
        return data

    def create(self, data):
        password = data.pop("password", "") or temporary_password()
        user = User(**data, must_change_password=True)
        user.set_password(password)
        user.save()
        user._temporary_password = password
        return user

    def update(self, user, data):
        data.pop("password", None)  # le mot de passe se change par l'action dédiée
        for field, value in data.items():
            setattr(user, field, value)
        user.save()
        return user


class AccessSerializer(serializers.Serializer):
    class ProjectItem(serializers.Serializer):
        project = serializers.CharField(max_length=20)
        canEdit = serializers.BooleanField(default=True)

    class ActionItem(serializers.Serializer):
        action = serializers.CharField(max_length=20)
        canEdit = serializers.BooleanField(default=False)

    projects = ProjectItem(many=True)
    actions = ActionItem(many=True)


class PermissionsSerializer(serializers.Serializer):
    permissions = serializers.DictField(child=serializers.ListField(child=serializers.BooleanField(), min_length=5, max_length=5))


class TokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    readOnly = serializers.BooleanField(default=True)
    expiresInDays = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Un jeton ne peut agir qu'au nom d'un compte actif du même tenant.
        self.fields["user"].queryset = User.objects.filter(is_active=True, tenant=self.context.get("tenant"))


class SecretSerializer(serializers.Serializer):
    value = serializers.CharField(max_length=4000, trim_whitespace=True)


class ChannelSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    settings = serializers.DictField(required=False)

    EMAIL_FIELDS = {"host", "port", "username", "from_address", "security"}

    def validate(self, data):
        kind = self.context["kind"]
        conf = data.get("settings") or {}
        if kind == "email":
            unknown = set(conf) - self.EMAIL_FIELDS
            if unknown:
                raise serializers.ValidationError({"settings": f"Champs inconnus : {', '.join(sorted(unknown))}."})
            clean = {
                "host": str(conf.get("host", "")).strip()[:200],
                "username": str(conf.get("username", "")).strip()[:200],
                "from_address": str(conf.get("from_address", "")).strip()[:200],
                "security": conf.get("security", "starttls"),
            }
            try:
                clean["port"] = int(conf.get("port") or 587)
            except (TypeError, ValueError):
                raise serializers.ValidationError({"settings.port": "Le port doit être un nombre."})
            if not 1 <= clean["port"] <= 65535:
                raise serializers.ValidationError({"settings.port": "Port entre 1 et 65535."})
            if clean["security"] not in ("starttls", "ssl", "none"):
                raise serializers.ValidationError({"settings.security": "Valeur attendue : starttls, ssl ou none."})
            if clean["from_address"]:
                serializers.EmailField().run_validation(clean["from_address"])
            if data["enabled"] and not (clean["host"] and clean["from_address"]):
                raise serializers.ValidationError({"settings": "Le serveur SMTP et l'adresse d'expéditeur sont obligatoires pour activer l'e-mail."})
            data["settings"] = clean
        else:
            data["settings"] = {}
        return data


class RulesSerializer(serializers.Serializer):
    rules = serializers.DictField(child=serializers.DictField(child=serializers.BooleanField()))


class ChannelTestSerializer(serializers.Serializer):
    to = serializers.EmailField(required=False)
