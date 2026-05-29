from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import PromptForm
from .models import BridgeStandard, Sketch, StandardChunk
from .pipeline.pgvector_store import using_pgvector, vector_row_count
from . import worker


@require_POST
def revise(request, pk: int):
    sketch = get_object_or_404(Sketch, pk=pk)
    change = (request.POST.get("change") or "").strip()
    if not change or not sketch.scad_source:
        return redirect("sketches:show", pk=sketch.pk)
    sketch.revision_request = change
    sketch.status = "pending"
    sketch.error = ""
    sketch.log(f"queued revision — starting background worker")
    sketch.save()
    worker.start(sketch.pk)
    return redirect("sketches:show", pk=sketch.pk)


def compose(request):
    form = PromptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        prompt, request_json, export_formats = form.build_request()
        sketch = Sketch.objects.create(
            prompt=prompt,
            request_json=request_json,
            export_formats=export_formats,
            scad_source="",
            generator="pending",
            status="pending",
        )
        sketch.log("queued — starting background worker")
        sketch.save()
        worker.start(sketch.pk)
        return redirect("sketches:show", pk=sketch.pk)

    return render(request, "sketches/compose.html", {
        "form": form,
        "recent": Sketch.objects.all()[:8],
    })


def show(request, pk: int):
    sketch = get_object_or_404(Sketch, pk=pk)
    in_progress = sketch.status in {"pending", "planning", "generating", "rendering"}
    return render(request, "sketches/sketch.html", {
        "sketch": sketch,
        "in_progress": in_progress,
    })


def db_explorer(request):
    tab = (request.GET.get("tab") or "sketches").strip().lower()
    if tab not in {"sketches", "standards", "chunks"}:
        tab = "sketches"
    q = (request.GET.get("q") or "").strip()
    try:
        limit = max(10, min(200, int(request.GET.get("limit", "50"))))
    except ValueError:
        limit = 50

    sketches = Sketch.objects.order_by("-created")
    standards = BridgeStandard.objects.annotate(chunk_total=Count("chunks")).order_by("title")
    chunks = StandardChunk.objects.select_related("standard").order_by("-updated")

    if q:
        sketches = sketches.filter(
            Q(prompt__icontains=q)
            | Q(brief__icontains=q)
            | Q(module_name__icontains=q)
            | Q(category__icontains=q)
        )
        standards = standards.filter(
            Q(title__icontains=q)
            | Q(category__icontains=q)
            | Q(section_id__icontains=q)
            | Q(text_content__icontains=q)
        )
        chunks = chunks.filter(
            Q(text__icontains=q)
            | Q(standard__title__icontains=q)
            | Q(standard__category__icontains=q)
        )

    context = {
        "active_tab": tab,
        "query": q,
        "limit": limit,
        "summary": {
            "sketches": Sketch.objects.count(),
            "components": Sketch.objects.filter(kind="component").count(),
            "assemblies": Sketch.objects.filter(kind="assembly").count(),
            "standards": BridgeStandard.objects.count(),
            "chunks": StandardChunk.objects.count(),
            "vector_rows": vector_row_count() if using_pgvector() else 0,
            "using_pgvector": using_pgvector(),
        },
        "sketch_rows": sketches[:limit],
        "standard_rows": standards[:limit],
        "chunk_rows": chunks[:limit],
    }
    return render(request, "sketches/db_explorer.html", context)
