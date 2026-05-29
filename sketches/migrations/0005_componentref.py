from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ("sketches", "0004_sketch_category_sketch_interface_json_sketch_kind_and_more"),
    ]
    operations = [
        migrations.CreateModel(
            name="ComponentRef",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("component_revision", models.IntegerField(default=0)),
                ("instance_name", models.CharField(max_length=64, blank=True)),
                ("params_json", models.JSONField(default=dict, blank=True)),
                ("translate", models.JSONField(default=list, blank=True)),
                ("rotate", models.JSONField(default=list, blank=True)),
                ("scale", models.JSONField(default=list, blank=True)),
                ("anchor_to_json", models.JSONField(default=dict, blank=True)),
                ("order", models.IntegerField(default=0)),
                ("assembly", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="component_refs", to="sketches.sketch")),
                ("component", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="used_in_assemblies", to="sketches.sketch")),
            ],
            options={"ordering": ("order",)},
        ),
    ]
