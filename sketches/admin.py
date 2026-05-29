from django.contrib import admin
from .models import BridgeStandard, Rule, Sketch, StandardChunk, ValidationResult


@admin.register(Sketch)
class SketchAdmin(admin.ModelAdmin):
	list_display = ("id", "created", "kind", "category", "status", "generator")
	list_filter = ("kind", "status", "generator", "category")
	search_fields = ("prompt", "brief", "module_name", "category", "tags")


@admin.register(BridgeStandard)
class BridgeStandardAdmin(admin.ModelAdmin):
	list_display = ("id", "title", "category", "source_type", "status", "page_count", "updated")
	list_filter = ("category", "source_type", "status")
	search_fields = ("title", "source_url", "section_id", "summary", "text_content")


@admin.register(StandardChunk)
class StandardChunkAdmin(admin.ModelAdmin):
	list_display = ("id", "standard", "chunk_index", "char_count", "embedding_model", "updated")
	list_filter = ("embedding_model",)
	search_fields = ("text", "standard__title")


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
	list_display = ("rule_id", "parameter", "comparator", "threshold_min", "threshold_max",
	                "severity", "active")
	list_filter = ("comparator", "severity", "active")
	search_fields = ("rule_id", "parameter", "description", "quote")
	list_editable = ("active", "severity")


@admin.register(ValidationResult)
class ValidationResultAdmin(admin.ModelAdmin):
	list_display = ("id", "sketch", "ran_at", "element_type", "compliance_score",
	                "passed", "warned", "failed", "skipped")
	list_filter = ("element_type",)
	search_fields = ("sketch__prompt", "element_type", "rag_notes")
	readonly_fields = ("ran_at",)
