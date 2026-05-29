from django.urls import path
from . import views
from . import views_assembly

app_name = "sketches"

urlpatterns = [
    path("", views.compose, name="compose"),
    path("db/", views.db_explorer, name="db_explorer"),
    path("s/<int:pk>/", views.show, name="show"),
    path("s/<int:pk>/revise/", views.revise, name="revise"),
    path("library/", views_assembly.library, name="library"),
    path("assemble/", views_assembly.assemble, name="assemble"),
    path("assembly/<int:pk>/edit/", views_assembly.edit_assembly, name="edit_assembly"),
    path("assembly/<int:pk>/slot/<int:ref_pk>/remove/", views_assembly.remove_slot, name="remove_slot"),
    path("assembly/<int:pk>/render/", views_assembly.render_assembly, name="render_assembly"),
    path("assembly/<int:pk>/", views_assembly.show_assembly, name="show_assembly"),
]
