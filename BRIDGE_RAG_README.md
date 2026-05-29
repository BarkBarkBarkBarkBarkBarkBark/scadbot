# Bridge Standards RAG & Validation System

A Beautiful Soup-based system that scrapes CalTrans bridge standard details, stores them in a local SQLite database, and validates OpenSCAD bridge designs against professional standards.

## Features

✓ **Scraped 256+ CalTrans Bridge Standards** — All XS standard sheets from the California Department of Transportation  
✓ **Local RAG Database** — SQLite-backed searchable knowledge base  
✓ **Design Validation** — Checks geometry, safety, materials, and loading capacity  
✓ **Code Compliance** — Automatic cross-reference with applicable standards  
✓ **Professional Reports** — Generates compliance scores and recommendations  

## Architecture

```
scrape_bridge_standards.py     ← Main scraper + RAG classes
  ├── BridgeStandardsScraper      (BeautifulSoup fetch & parse)
  ├── BridgeDesignValidator       (design → parameters)
  └── BridgeStandardsValidator    (standards lookup)

validate_designs.py             ← Django integration + detailed checks
  ├── BridgeCodeValidator        (comprehensive validation)
  └── Code compliance scoring

bridge_standards.db             ← SQLite RAG database
  └── 256+ indexed standards    (searchable, categorized)
```

## Quick Start

### 1. Scrape CalTrans Standards (One-time)

```bash
cd openscad
python scrape_bridge_standards.py
```

Output:
- `bridge_standards.db` — Local knowledge base (~250KB)
- 256 standards indexed by category, title, URL
- Indexed for full-text keyword search

### 2. Validate a Design

```bash
python validate_designs.py <sketch_id>
```

Example:
```bash
python validate_designs.py 7
```

Output:
```
BRIDGE DESIGN VALIDATION REPORT
Design: Civic Ribbon Bridge
======================================================================

COMPLIANCE SCORE: 85/100 [PASS ✓]

[GEOMETRY]
  (no issues)

[SAFETY]
  ✗ Insufficient support count; minimum 2 required for stability

[MATERIALS]
  Identified: steel, wood, cable

[LOADING CAPACITY]
  Estimated capacity: 8.21 units

[APPLICABLE STANDARDS]
  1. 1.6 Use of Bridge Standard Detail Sheets (XS-SHEETS)
  2. xs2-010-1 User Guide
  ...

[RECOMMENDATIONS]
  1. Obtain detailed CalTrans standard sheets for design category
  2. Perform full finite element analysis (FEA)
  ...

✓ Report saved to validation_report_7.txt
```

### 3. Query the RAG Database

```python
from scrape_bridge_standards import BridgeStandardsScraper

scraper = BridgeStandardsScraper("bridge_standards.db")

# Search for standards
results = scraper.search_standards("suspension cable")
for r in results:
    print(f"{r['title']}: {r['content_preview']}")

# List by category
standards = scraper.list_standards(category="General")
```

## API Reference

### `BridgeStandardsScraper`

```python
scraper = BridgeStandardsScraper("bridge_standards.db")

# Scrape and save CalTrans standards
standards = scraper.scrape_main_page()
scraper.save_standards(standards)

# Search
results = scraper.search_standards("arch bridge", limit=10)

# List
all_standards = scraper.list_standards()
cat_standards = scraper.list_standards(category="Suspension Bridges")
```

### `BridgeCodeValidator`

```python
from validate_designs import BridgeCodeValidator
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'forge.settings')
import django
django.setup()

from sketches.models import Sketch

validator = BridgeCodeValidator("bridge_standards.db")
sketch = Sketch.objects.get(pk=7)
validation = validator.validate_sketch(sketch)

print(f"Compliance: {validation['compliance_score']}/100")
print(validation['report'])
```

### Validation Checks

| Check | Criteria |
|-------|----------|
| **Geometry** | Span/rise ratios, deck width, proportions |
| **Safety** | Support count, cable sizing, deck thickness |
| **Materials** | Explicit material specification |
| **Loading** | Estimated capacity vs. span length |
| **Standards** | Cross-reference with applicable CalTrans XS sheets |

## Standards Database

The database includes all CalTrans Bridge Standard Detail (XS) sheets:

- **XS1-xxx** — Temporary bridge components
- **XS2-xxx** — Single-span bridges
- **XS4-xxx** — Multi-span structures
- **XS7-xxx** — Railings, guards, safety
- **XS8-xxx** — Bearings, expansion joints
- **XS9-xxx** — Drainage, utilities
- **XS12-xxx** — Bearings (detailed)
- **XS14-xxx** — Piers, abutments, supports
- **XS16-xxx** — Girders, box sections, steel members
- **XS17-xxx** — Expansion devices, utilities
- **XS20-xxx** — Bearings, expansion

Each standard sheet includes:
- Title and document ID
- Category (materials, design, safety, etc.)
- URL to official CalTrans PDF
- Indexed keywords for full-text search

## Usage in Your App

### Add Validation to Django Views

```python
from validate_designs import BridgeCodeValidator

def show(request, pk: int):
    sketch = get_object_or_404(Sketch, pk=pk)
    
    validator = BridgeCodeValidator()
    validation = validator.validate_sketch(sketch)
    
    return render(request, 'sketches/sketch.html', {
        'sketch': sketch,
        'validation': validation,
        'compliance_score': validation['compliance_score'],
    })
```

### Template Display

```html
{% if validation %}
<div class="compliance-badge">
  <h3>Compliance Check</h3>
  <p class="score {% if validation.compliance_score >= 80 %}pass{% endif %}">
    {{ validation.compliance_score }}/100
  </p>
  {% for issue in validation.validation_checks.geometry.issues %}
    <p class="issue">{{ issue }}</p>
  {% endfor %}
</div>
{% endif %}
```

## Data Privacy & Attribution

- CalTrans standards are public domain (government documents)
- Local database stores only metadata, titles, and links
- No copyrighted content is archived; links point to official sources
- For production use, verify current CalTrans revisions at:  
  https://dot.ca.gov/programs/engineering-services/manuals/bridge-standard-details

## Advanced: Custom Validation Rules

```python
class CustomValidator(BridgeCodeValidator):
    def _check_geometry(self, params: dict) -> dict:
        # Your custom checks
        checks = super()._check_geometry(params)
        
        # Add site-specific rules
        if params.get('span_length') > 500:
            checks['issues'].append("Very long span; requires specialist review")
        
        return checks
```

## Future Enhancements

- [ ] PDF text extraction for full standard content
- [ ] FEA integration (mesh validation)
- [ ] Wind, seismic load checks
- [ ] Material database with specs
- [ ] Cost estimation
- [ ] Rendering in browser with standards overlay

## Files

| File | Purpose |
|------|---------|
| `scrape_bridge_standards.py` | Scraper + RAG classes |
| `validate_designs.py` | Validator + Django integration |
| `bridge_standards.db` | SQLite database (auto-created) |
| `validation_report_*.txt` | Per-sketch compliance reports |

## License

This tooling is for educational and design verification purposes. CalTrans standards are public; use accordingly.

---

**Questions?** Check the [CalTrans Engineering Services](https://dot.ca.gov/programs/engineering-services) site or your local jurisdiction's bridge code requirements.
