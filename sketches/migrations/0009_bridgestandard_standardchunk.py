from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sketches", "0008_sketch_request_json_and_export_formats"),
    ]

    operations = [
        migrations.CreateModel(
            name="BridgeStandard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=300)),
                ("source_url", models.URLField(unique=True)),
                ("source_type", models.CharField(default="pdf", max_length=16)),
                ("section_id", models.CharField(blank=True, max_length=80)),
                ("category", models.CharField(blank=True, max_length=120)),
                ("summary", models.TextField(blank=True)),
                ("text_content", models.TextField(blank=True)),
                ("content_sha256", models.CharField(blank=True, max_length=64)),
                ("page_count", models.IntegerField(default=0)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("local_path", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("discovered", "discovered"), ("downloaded", "downloaded"), ("extracted", "extracted"), ("chunked", "chunked"), ("embedded", "embedded"), ("failed", "failed")], default="discovered", max_length=16)),
                ("error", models.TextField(blank=True)),
                ("fetched_at", models.DateTimeField(blank=True, null=True)),
                ("extracted_at", models.DateTimeField(blank=True, null=True)),
                ("embedded_at", models.DateTimeField(blank=True, null=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("title",),
            },
        ),
        migrations.CreateModel(
            name="StandardChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chunk_index", models.IntegerField()),
                ("text", models.TextField()),
                ("char_count", models.IntegerField(default=0)),
                ("token_estimate", models.IntegerField(default=0)),
                ("embedding", models.JSONField(blank=True, default=list)),
                ("embedding_model", models.CharField(blank=True, max_length=120)),
                ("metadata_json", models.JSONField(blank=True, default=dict)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
                ("standard", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chunks", to="sketches.bridgestandard")),
            ],
            options={
                "ordering": ("standard_id", "chunk_index"),
                "unique_together": {("standard", "chunk_index")},
            },
        ),
    ]
