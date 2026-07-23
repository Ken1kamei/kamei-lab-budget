from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labapps", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgerecord",
            name="canonical_record_id",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="knowledgerecord",
            name="content_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="knowledgerecord",
            name="search_text",
            field=models.TextField(blank=True),
        ),
        migrations.AddIndex(
            model_name="knowledgerecord",
            index=models.Index(
                fields=["canonical_record_id"],
                name="labapps_kno_canonic_cac87c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="knowledgerecord",
            index=models.Index(
                fields=["content_sha256"],
                name="labapps_kno_content_23b557_idx",
            ),
        ),
    ]
