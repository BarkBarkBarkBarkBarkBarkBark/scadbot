from django import forms
from .models import Sketch

class AssemblyForm(forms.Form):
    name = forms.CharField(max_length=100, required=True)
    prompt = forms.CharField(widget=forms.Textarea, required=False)
    # Dynamically add fields for each component slot in the view

class AddComponentForm(forms.Form):
    component_id = forms.IntegerField(widget=forms.HiddenInput)
    instance_name = forms.CharField(max_length=64, required=False)
    translate = forms.CharField(max_length=64, required=False, help_text="[x, y, z]")
    rotate = forms.CharField(max_length=64, required=False, help_text="[x, y, z]")
    params = forms.CharField(widget=forms.Textarea, required=False, help_text="JSON of param overrides")
