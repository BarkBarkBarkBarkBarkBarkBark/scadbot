from django.db import models


class Sketch(models.Model):
    STATUS_CHOICES = [
        ("idle", "idle"),
        ("pending", "pending"),
        ("planning", "planning"),
        ("generating", "generating"),
        ("rendering", "rendering"),
        ("done", "done"),
        ("failed", "failed"),
    ]

    KIND_CHOICES = [
        ("component", "component"),  # a single reusable part (default)
        ("assembly", "assembly"),    # a scene composed of components
    ]

    created = models.DateTimeField(auto_now_add=True)
    prompt = models.TextField()
    scad_source = models.TextField(blank=True)
    preview = models.ImageField(upload_to="png/", blank=True)
    mesh = models.FileField(upload_to="stl/", blank=True)
    error = models.TextField(blank=True)
    generator = models.CharField(max_length=64, default="heuristic")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    stage_log = models.TextField(blank=True, help_text="timestamped progress messages")
    brief = models.TextField(blank=True, help_text="engineering brief from phase 1")
    request_json = models.JSONField(default=dict, blank=True,
        help_text="structured request captured from the compose form")
    export_formats = models.JSONField(default=list, blank=True,
        help_text="requested deliverables, e.g. ['png', 'stl']")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="component")
    module_name = models.CharField(max_length=80, blank=True,
        help_text="top-level OpenSCAD module name (the composer entry point)")
    interface_json = models.JSONField(default=dict, blank=True,
        help_text="params, anchors, modules — the component contract")
    category = models.CharField(max_length=40, blank=True,
        help_text="furniture | structure | foliage | mechanical | …")
    tags = models.CharField(max_length=200, blank=True,
        help_text="comma-separated search tags")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="revisions",
        help_text="if set, this sketch is a revision of the parent",
    )
    revision_request = models.TextField(
        blank=True,
        help_text="natural-language change request applied to the parent",
    )

    class Meta:
        ordering = ("-created",)

    def __str__(self) -> str:
        return f"Sketch#{self.pk} \u2014 {self.prompt[:40]}"

    def log(self, message: str) -> None:
        from django.utils import timezone
        stamp = timezone.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.stage_log = (self.stage_log + "\n" + line).strip() if self.stage_log else line

    def lineage(self) -> list["Sketch"]:
        """Return ancestor chain (root first, self last)."""
        chain: list[Sketch] = [self]
        node = self.parent
        while node is not None and len(chain) < 20:
            chain.insert(0, node)
            node = node.parent
        return chain

    def requested_formats(self) -> set[str]:
        formats = self.export_formats or ["png", "stl"]
        return {str(item).lower() for item in formats if item}


class ComponentRef(models.Model):
    """One component placement inside an assembly."""
    assembly = models.ForeignKey(
        Sketch, on_delete=models.CASCADE, related_name="component_refs",
    )
    component = models.ForeignKey(
        Sketch, on_delete=models.CASCADE, related_name="used_in_assemblies",
    )
    instance_name = models.CharField(max_length=64, blank=True,
        help_text="Label for this placement (defaults to module_name)")
    params_json = models.JSONField(default=dict, blank=True,
        help_text="Parameter overrides, e.g. {\"height\": 1200}")
    translate = models.JSONField(default=list, blank=True,
        help_text="[x, y, z] translation in mm")
    rotate = models.JSONField(default=list, blank=True,
        help_text="[x, y, z] Euler rotation in degrees")
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ("order",)

    def __str__(self) -> str:
        label = self.instance_name or self.component.module_name or f"comp#{self.component_id}"
        return f"assembly#{self.assembly_id} ← {label}"

    def translate_vec(self) -> list:
        t = self.translate
        return t if (isinstance(t, list) and len(t) == 3) else [0, 0, 0]

    def rotate_vec(self) -> list:
        r = self.rotate
        return r if (isinstance(r, list) and len(r) == 3) else [0, 0, 0]


class BridgeStandard(models.Model):
    STATUS_CHOICES = [
        ("discovered", "discovered"),
        ("downloaded", "downloaded"),
        ("extracted", "extracted"),
        ("chunked", "chunked"),
        ("embedded", "embedded"),
        ("failed", "failed"),
    ]

    title = models.CharField(max_length=300)
    source_url = models.URLField(unique=True)
    source_type = models.CharField(max_length=16, default="pdf")
    section_id = models.CharField(max_length=80, blank=True)
    category = models.CharField(max_length=120, blank=True)
    summary = models.TextField(blank=True)
    text_content = models.TextField(blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    page_count = models.IntegerField(default=0)
    metadata_json = models.JSONField(default=dict, blank=True)
    local_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="discovered")
    error = models.TextField(blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    extracted_at = models.DateTimeField(null=True, blank=True)
    embedded_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title


class StandardChunk(models.Model):
    standard = models.ForeignKey(
        BridgeStandard, on_delete=models.CASCADE, related_name="chunks",
    )
    chunk_index = models.IntegerField()
    text = models.TextField()
    char_count = models.IntegerField(default=0)
    token_estimate = models.IntegerField(default=0)
    embedding = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("standard_id", "chunk_index")
        unique_together = ("standard", "chunk_index")

    def __str__(self) -> str:
        return f"{self.standard_id}#{self.chunk_index}"


# ─── Validation ───────────────────────────────────────────────────────────────

class Rule(models.Model):
    """A single deterministic compliance rule extracted from a bridge standard."""
    COMPARATOR_CHOICES = [
        ("min", "≥ threshold_min"),
        ("max", "≤ threshold_max"),
        ("range", "threshold_min ≤ value ≤ threshold_max"),
    ]
    SEVERITY_CHOICES = [
        ("warn", "warning"),
        ("fail", "fail"),
    ]

    rule_id = models.CharField(max_length=60, unique=True,
        help_text="Stable slug, e.g. 'deck_width_min'")
    parameter = models.CharField(max_length=80,
        help_text="SCAD variable name to extract, e.g. 'deck_width'")
    comparator = models.CharField(max_length=8, choices=COMPARATOR_CHOICES)
    threshold_min = models.FloatField(null=True, blank=True,
        help_text="Lower bound (mm or unitless)")
    threshold_max = models.FloatField(null=True, blank=True,
        help_text="Upper bound (mm or unitless)")
    bridge_types = models.JSONField(default=list, blank=True,
        help_text="[] = all bridge types; or ['suspension', 'arch', …]")
    element_types = models.JSONField(default=list, blank=True,
        help_text="[] = all elements; or ['deck', 'pylon', 'cable', …]")
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES, default="fail")
    source_standard = models.ForeignKey(
        BridgeStandard, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="rules",
    )
    quote = models.TextField(blank=True,
        help_text="Verbatim text from the standard that backs this rule")
    description = models.CharField(max_length=300, blank=True,
        help_text="Human-readable rule description")
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("rule_id",)

    def __str__(self) -> str:
        return f"Rule[{self.rule_id}] {self.comparator}"


class ValidationResult(models.Model):
    """Stored compliance report for a single Sketch."""
    sketch = models.OneToOneField(
        Sketch, on_delete=models.CASCADE, related_name="validation",
    )
    ran_at = models.DateTimeField(auto_now_add=True)
    compliance_score = models.FloatField(default=0.0,
        help_text="0–100 percent compliance")
    passed = models.IntegerField(default=0)
    warned = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    element_type = models.CharField(max_length=40, blank=True,
        help_text="Auto-detected structural element: deck, pylon, cable, arch, truss, abutment, …")
    results_json = models.JSONField(default=list,
        help_text="List of {rule_id, parameter, status, value, threshold, message}")
    rag_notes = models.TextField(blank=True,
        help_text="LLM-generated standards compliance commentary")
    auto_repair_prompt = models.TextField(blank=True,
        help_text="Targeted repair prompt if failed rules exist")

    class Meta:
        ordering = ("-ran_at",)

    def __str__(self) -> str:
        return f"Validation#{self.sketch_id} score={self.compliance_score:.0f}%"

    @property
    def status_label(self) -> str:
        if self.failed:
            return "fail"
        if self.warned:
            return "warn"
        return "pass"
