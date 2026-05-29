from django import forms


class PromptForm(forms.Form):
    BRIDGE_CHOICES = [
        ("", "auto / inferred"),
        ("truss", "truss"),
        ("arch", "arch"),
        ("suspension", "suspension"),
        ("cable_stayed", "cable-stayed"),
        ("beam", "beam"),
        ("pedestrian", "pedestrian"),
    ]
    MATERIAL_CHOICES = [
        ("", "auto / inferred"),
        ("steel", "steel"),
        ("concrete", "concrete"),
        ("wood", "wood"),
        ("composite", "composite"),
    ]
    FEATURE_CHOICES = [
        ("railings", "railings"),
        ("piers", "piers"),
        ("arches", "arches"),
        ("cables", "cables"),
        ("towers", "towers"),
        ("walkway", "walkway"),
        ("garden", "public garden"),
        ("plaque", "dedication plaque"),
    ]

    prompt = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "e.g. a graceful 120mm arched bridge with railings and piers",
            "autofocus": True,
        }),
        max_length=2000,
        required=False,
    )
    bridge_type = forms.ChoiceField(choices=BRIDGE_CHOICES, required=False)
    span_mm = forms.FloatField(min_value=20, required=False, label="span (mm)")
    deck_width_mm = forms.FloatField(min_value=5, required=False, label="deck width (mm)")
    clearance_mm = forms.FloatField(min_value=0, required=False, label="clearance (mm)")
    max_height_mm = forms.FloatField(min_value=0, required=False, label="max height (mm)")
    lane_count = forms.IntegerField(min_value=1, required=False, label="lane / path count")
    material = forms.ChoiceField(choices=MATERIAL_CHOICES, required=False)
    features = forms.MultipleChoiceField(
        choices=FEATURE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "special constraints, landmark details, landscape, fabrication notes…",
        }),
    )
    export_png = forms.BooleanField(required=False, initial=True, label="PNG preview")
    export_stl = forms.BooleanField(required=False, initial=True, label="STL export")

    def clean(self):
        cleaned = super().clean()
        prompt = (cleaned.get("prompt") or "").strip()
        bridge_type = cleaned.get("bridge_type") or ""
        notes = (cleaned.get("notes") or "").strip()
        if not any([prompt, bridge_type, notes]):
            raise forms.ValidationError(
                "Provide a freeform prompt or fill in the structured bridge request."
            )
        if not cleaned.get("export_png") and not cleaned.get("export_stl"):
            raise forms.ValidationError("Select at least one export format.")
        return cleaned

    def build_request(self) -> tuple[str, dict, list[str]]:
        cleaned = self.cleaned_data
        features = cleaned.get("features") or []
        request_json = {
            "bridge_type": cleaned.get("bridge_type") or "",
            "span_mm": cleaned.get("span_mm"),
            "deck_width_mm": cleaned.get("deck_width_mm"),
            "clearance_mm": cleaned.get("clearance_mm"),
            "max_height_mm": cleaned.get("max_height_mm"),
            "lane_count": cleaned.get("lane_count"),
            "material": cleaned.get("material") or "",
            "features": features,
            "notes": (cleaned.get("notes") or "").strip(),
            "prompt": (cleaned.get("prompt") or "").strip(),
        }
        export_formats = []
        if cleaned.get("export_png"):
            export_formats.append("png")
        if cleaned.get("export_stl"):
            export_formats.append("stl")

        lines = []
        if request_json["prompt"]:
            lines.append(request_json["prompt"])
        structured = []
        if request_json["bridge_type"]:
            structured.append(f"bridge type: {request_json['bridge_type']}")
        if request_json["span_mm"]:
            structured.append(f"span: {request_json['span_mm']:g} mm")
        if request_json["deck_width_mm"]:
            structured.append(f"deck width: {request_json['deck_width_mm']:g} mm")
        if request_json["clearance_mm"] is not None:
            structured.append(f"clearance: {request_json['clearance_mm']:g} mm")
        if request_json["max_height_mm"] is not None:
            structured.append(f"max height: {request_json['max_height_mm']:g} mm")
        if request_json["lane_count"]:
            structured.append(f"lane/path count: {request_json['lane_count']}")
        if request_json["material"]:
            structured.append(f"material intent: {request_json['material']}")
        if features:
            structured.append("features: " + ", ".join(features))
        if request_json["notes"]:
            structured.append("notes: " + request_json["notes"])
        if structured:
            lines.append("structured bridge request")
            lines.extend(f"- {item}" for item in structured)
        lines.append("deliverables: " + ", ".join(fmt.upper() for fmt in export_formats))
        prompt = "\n".join(lines).strip()
        return prompt, request_json, export_formats
