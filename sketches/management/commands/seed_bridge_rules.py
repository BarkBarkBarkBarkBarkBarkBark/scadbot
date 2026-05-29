"""management command: seed_bridge_rules
Seeds deterministic Rule objects grounded in CalTrans Bridge Design Standards.
Run once: python manage.py seed_bridge_rules
Re-run is idempotent (get_or_create on rule_id).
"""
from django.core.management.base import BaseCommand
from sketches.models import Rule

# ── Rule seed data ────────────────────────────────────────────────────────────
# Each dict maps to a Rule instance.
# Sources: CalTrans BDS 2019, Caltrans Highway Design Manual §300, AASHTO LRFD
# Units: mm unless noted.  lane_count and similar are unitless.

RULES: list[dict] = [
    # ── Span / clearance ──────────────────────────────────────────────────────
    {
        "rule_id": "span_length_min",
        "parameter": "span_length",
        "comparator": "min",
        "threshold_min": 3000,  # 3 m
        "description": "Minimum span length for a bridge structure",
        "severity": "warn",
        "bridge_types": [],
        "element_types": ["bridge"],
        "quote": "Structures with spans less than 3 m are typically classified as culverts.",
    },
    {
        "rule_id": "span_length_max_simple",
        "parameter": "span_length",
        "comparator": "max",
        "threshold_max": 300_000,  # 300 m single span practical limit for concrete
        "description": "Practical maximum simple-span length (concrete/steel)",
        "severity": "warn",
        "bridge_types": [],
        "element_types": ["bridge"],
        "quote": "Simple spans exceeding 300 m require special study and project-specific approval.",
    },
    {
        "rule_id": "clearance_min_roadway",
        "parameter": "clearance",
        "comparator": "min",
        "threshold_min": 5100,   # CalTrans HDM §309.1 — 5.1 m minimum vertical clearance
        "description": "Minimum vertical clearance over roadway (CalTrans HDM §309.1)",
        "severity": "fail",
        "bridge_types": [],
        "element_types": [],
        "quote": (
            "For new structures crossing state highways, the minimum vertical clearance "
            "shall be 5.1 m (16.7 ft) over the roadway."
        ),
    },
    {
        "rule_id": "clearance_min_rail",
        "parameter": "clearance",
        "comparator": "min",
        "threshold_min": 7100,   # 7.1 m over active rail lines
        "description": "Minimum vertical clearance over active rail (CalTrans §309.2)",
        "severity": "warn",
        "bridge_types": [],
        "element_types": [],
        "quote": (
            "Bridges crossing active railroad tracks shall provide a minimum vertical clearance "
            "of 7.1 m above the top of rail."
        ),
    },
    # ── Deck width / lane ────────────────────────────────────────────────────
    {
        "rule_id": "deck_width_min_1lane",
        "parameter": "deck_width",
        "comparator": "min",
        "threshold_min": 4200,  # CalTrans HDM §301 single lane with shoulders
        "description": "Minimum deck width for single-lane bridge",
        "severity": "fail",
        "bridge_types": [],
        "element_types": ["deck", "bridge"],
        "quote": (
            "Single-lane bridges shall have a minimum clear roadway width of 4.2 m "
            "including shoulders. (CalTrans HDM Table 301.1)"
        ),
    },
    {
        "rule_id": "lane_width_min",
        "parameter": "lane_width",
        "comparator": "min",
        "threshold_min": 3600,  # 3.6 m standard lane
        "description": "Minimum lane width (CalTrans HDM §301.1)",
        "severity": "fail",
        "bridge_types": [],
        "element_types": [],
        "quote": "Standard lane widths on state highways shall be 3.6 m (12 ft).",
    },
    {
        "rule_id": "lane_width_max",
        "parameter": "lane_width",
        "comparator": "max",
        "threshold_max": 4200,
        "description": "Maximum lane width before requiring additional safety features",
        "severity": "warn",
        "bridge_types": [],
        "element_types": [],
        "quote": "Lane widths exceeding 4.2 m require barrier review.",
    },
    {
        "rule_id": "deck_thickness_min",
        "parameter": "deck_thickness",
        "comparator": "min",
        "threshold_min": 175,   # CalTrans BDS §5.14.1.5 min 175 mm concrete deck
        "description": "Minimum reinforced-concrete deck thickness (CalTrans BDS §5.14.1.5)",
        "severity": "fail",
        "bridge_types": [],
        "element_types": ["deck"],
        "quote": (
            "The minimum thickness of cast-in-place concrete deck slabs shall be 175 mm."
        ),
    },
    # ── Arch ──────────────────────────────────────────────────────────────────
    {
        "rule_id": "arch_rise_to_span_min",
        "parameter": "arch_height",
        "comparator": "min",
        "threshold_min": None,   # computed dynamically — kept as doc rule
        "description": "Arch rise ≥ span/8 for structural efficiency",
        "severity": "warn",
        "bridge_types": ["arch"],
        "element_types": ["arch"],
        "quote": "The rise-to-span ratio for arch bridges is typically between 1:4 and 1:8.",
    },
    # ── Cable / suspension ────────────────────────────────────────────────────
    {
        "rule_id": "cable_radius_min",
        "parameter": "cable_radius",
        "comparator": "min",
        "threshold_min": 25,    # 25 mm radius / 50 mm dia — structural cable minimum
        "description": "Minimum structural cable radius for suspension bridges",
        "severity": "warn",
        "bridge_types": ["suspension", "cable-stayed"],
        "element_types": ["cable"],
        "quote": (
            "Main cables shall have a diameter of not less than 50 mm to ensure "
            "adequate strength and corrosion reserve."
        ),
    },
    {
        "rule_id": "pylon_height_min",
        "parameter": "pylon_height",
        "comparator": "min",
        "threshold_min": 10_000,  # 10 m — a pylon shorter than 10 m is architecturally degenerate
        "description": "Minimum pylon height for suspension/cable-stayed bridges",
        "severity": "warn",
        "bridge_types": ["suspension", "cable-stayed"],
        "element_types": ["pylon"],
        "quote": "Pylons shall be proportioned to achieve the required cable geometry and clearance.",
    },
    # ── Lane count ────────────────────────────────────────────────────────────
    {
        "rule_id": "lane_count_min",
        "parameter": "lane_count",
        "comparator": "min",
        "threshold_min": 1,
        "description": "Bridge must have at least one traffic lane",
        "severity": "fail",
        "bridge_types": [],
        "element_types": [],
        "quote": "",
    },
    {
        "rule_id": "lane_count_max",
        "parameter": "lane_count",
        "comparator": "max",
        "threshold_max": 12,
        "description": "More than 12 lanes requires special study",
        "severity": "warn",
        "bridge_types": [],
        "element_types": [],
        "quote": "Bridges with more than 12 lanes require individual project approval.",
    },
    # ── Deck height ───────────────────────────────────────────────────────────
    {
        "rule_id": "deck_height_min",
        "parameter": "deck_height",
        "comparator": "min",
        "threshold_min": 200,
        "description": "Minimum total depth of superstructure above datum",
        "severity": "warn",
        "bridge_types": [],
        "element_types": ["deck", "bridge"],
        "quote": (
            "The minimum structure depth (including deck) shall be sufficient to "
            "accommodate longitudinal reinforcement, shear, and camber."
        ),
    },
    # ── Wall / girder ─────────────────────────────────────────────────────────
    {
        "rule_id": "wall_thickness_min",
        "parameter": "wall_thickness",
        "comparator": "min",
        "threshold_min": 100,   # 100 mm min concrete wall
        "description": "Minimum concrete wall or girder web thickness",
        "severity": "warn",
        "bridge_types": [],
        "element_types": [],
        "quote": (
            "Web or wall thickness shall not be less than 100 mm. "
            "(CalTrans BDS §5.13.2.3)"
        ),
    },
]


class Command(BaseCommand):
    help = "Seed Rule objects from the embedded CalTrans rule library."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing rules before seeding.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            deleted, _ = Rule.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing rules."))

        created_count = 0
        updated_count = 0

        for data in RULES:
            obj, created = Rule.objects.get_or_create(
                rule_id=data["rule_id"],
                defaults={k: v for k, v in data.items() if k != "rule_id"},
            )
            if created:
                created_count += 1
                self.stdout.write(f"  + created: {obj.rule_id}")
            else:
                # Update in place so re-runs pick up changes
                for k, v in data.items():
                    if k != "rule_id":
                        setattr(obj, k, v)
                obj.save()
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {created_count} created, {updated_count} updated. "
                f"Total rules: {Rule.objects.count()}"
            )
        )
