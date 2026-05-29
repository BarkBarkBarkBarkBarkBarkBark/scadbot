from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sketches", "0007_remove_componentref_anchor_to_json_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sketch",
            name="export_formats",
            field=models.JSONField(blank=True, default=list, help_text="requested deliverables, e.g. ['png', 'stl']"),
        ),
        migrations.AddField(
            model_name="sketch",
            name="request_json",
            field=models.JSONField(blank=True, default=dict, help_text="structured request captured from the compose form"),
        ),
    ]
