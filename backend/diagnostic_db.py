import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

try:
    django.setup()
    from django.conf import settings

    db = settings.DATABASES["default"]

    print("ENGINE:", db.get("ENGINE"))
    print("HOST:", db.get("HOST"))
    print("PORT:", db.get("PORT"))
    print("NAME:", db.get("NAME"))
    print("USER:", db.get("USER"))
    print("PASSWORD PRESENT:", bool(db.get("PASSWORD")))

except Exception:
    import traceback
    traceback.print_exc()
