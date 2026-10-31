from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit

from .serializers import ChangePasswordSerializer, LoginSerializer, MeSerializer


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """Dépose le cookie csrftoken ; le frontend le renvoie dans l'en-tête X-CSRFToken."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="post")
class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, username=data.validated_data["username"], password=data.validated_data["password"])
        if user is None:
            audit.record(None, f"Utilisateur {data.validated_data['username'][:60]}", "Connexion refusée")
            # Même message que le compte existe ou non.
            raise ApiError("INVALID_CREDENTIALS", "Identifiant ou mot de passe incorrect.", status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        audit.record(user, f"Utilisateur {user.username}", "Connexion")
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        audit.record(user, f"Utilisateur {user.username}", "Mot de passe changé")
        return Response(MeSerializer(user).data)
