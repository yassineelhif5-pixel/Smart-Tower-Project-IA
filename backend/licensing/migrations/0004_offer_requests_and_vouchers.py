import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("licensing", "0003_default_offer_catalog"),
        ("tenants", "0002_default_tenant"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(
            model_name="licenserequest",
            name="target_version",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                   related_name="offer_requests", to="licensing.offerversion"),
        ),
        migrations.CreateModel(
            name="OfferVoucher",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batch_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("code_hash", models.CharField(max_length=64, unique=True)),
                ("code_hint", models.CharField(max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("redeemed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_offer_vouchers", to=settings.AUTH_USER_MODEL)),
                ("offer_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="vouchers", to="licensing.offerversion")),
                ("redeemed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="redeemed_offer_vouchers", to=settings.AUTH_USER_MODEL)),
                ("redeemed_tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="redeemed_offer_vouchers", to="tenants.tenant")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="revoked_offer_vouchers", to=settings.AUTH_USER_MODEL)),
                ("target_tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="offer_vouchers", to="tenants.tenant")),
            ],
            options={"ordering": ["-created_at", "id"]},
        ),
    ]
