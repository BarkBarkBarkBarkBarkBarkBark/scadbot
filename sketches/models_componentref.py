from django.db import models

class ComponentRef(models.Model):
    assembly = models.ForeignKey('Sketch', on_delete=models.CASCADE, related_name='component_refs')
    component = models.ForeignKey('Sketch', on_delete=models.CASCADE, related_name='used_in_assemblies')
    component_revision = models.IntegerField(default=0, help_text="Pin to a specific revision if needed")
    instance_name = models.CharField(max_length=64, blank=True, help_text="Instance label for this placement")
    params_json = models.JSONField(default=dict, blank=True, help_text="Parameter overrides for this instance")
    translate = models.JSONField(default=list, blank=True, help_text="[x, y, z] translation")
    rotate = models.JSONField(default=list, blank=True, help_text="[x, y, z] rotation (deg)")
    scale = models.JSONField(default=list, blank=True, help_text="[x, y, z] scale factors")
    anchor_to_json = models.JSONField(default=dict, blank=True, help_text="Anchor placement: {parent_slot, anchor_name}")
    order = models.IntegerField(default=0, help_text="Order in assembly")

    class Meta:
        ordering = ("order",)

    def __str__(self):
        return f"{self.assembly_id} uses {self.component_id} as {self.instance_name or self.component.module_name}"