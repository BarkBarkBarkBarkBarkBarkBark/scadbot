#!/usr/bin/env python3
"""
Django command to validate bridge designs against CalTrans standards.
Use: python manage.py validate_design [sketch_id]
"""

import os
import django
import json
import re
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'forge.settings')
django.setup()

from sketches.models import Sketch
from scrape_bridge_standards import BridgeDesignValidator, BridgeStandardsValidator


class BridgeCodeValidator:
    """
    Comprehensive validator against CalTrans bridge standards.
    Checks structural parameters, materials, safety, and design best practices.
    """
    
    def __init__(self, db_path: str = "bridge_standards.db"):
        self.db_path = db_path
        self.validator = BridgeDesignValidator(db_path)
        self.standards = BridgeStandardsValidator(db_path)
    
    def validate_sketch(self, sketch: Sketch) -> dict:
        """Validate a Sketch model against bridge standards."""
        scad_code = sketch.scad_source
        design_name = sketch.prompt
        
        # Extract parameters
        params = self._extract_all_params(scad_code)
        
        # Run validation checks
        checks = {
            'geometry': self._check_geometry(params),
            'safety': self._check_safety_params(params),
            'materials': self._check_materials(scad_code),
            'loading': self._check_loading_capacity(params),
            'standards_reference': self._find_applicable_standards(design_name, params),
        }
        
        # Calculate overall compliance score
        compliance_score = self._calculate_compliance(checks)
        
        return {
            'sketch_id': sketch.pk,
            'design_name': design_name,
            'parameters': params,
            'validation_checks': checks,
            'compliance_score': compliance_score,
            'report': self._generate_report(checks, params, design_name),
        }
    
    def _extract_all_params(self, scad: str) -> dict:
        """Extract all structural parameters from OpenSCAD code."""
        params = {}
        
        # Span and length
        patterns = {
            # Dimensions
            'span_length': [r'bridge_length\s*=\s*([\d.]+)', r'span.*?=\s*([\d.]+)'],
            'deck_width': [r'deck_width\s*=\s*([\d.]+)', r'width.*?=\s*([\d.]+)'],
            'deck_height': [r'deck.*?height\s*=\s*([\d.]+)'],
            'pylon_height': [r'pylon_height\s*=\s*([\d.]+)', r'tower.*?height\s*=\s*([\d.]+)'],
            
            # Structural elements
            'arch_height': [r'arch_height\s*=\s*([\d.]+)'],
            'cable_radius': [r'cable.*?r\s*=\s*([\d.]+)'],
            'suspension_cables': [r'(?:cable|suspension).*?=\s*(\d+)'],
            'truss_depth': [r'truss.*?depth\s*=\s*([\d.]+)'],
            'support_count': [r'support\s*=\s*(\d+)', r'pylon.*?=\s*(\d+)'],
            
            # Material thickness
            'deck_thickness': [r'deck.*?thickness\s*=\s*([\d.]+)'],
            'beam_thickness': [r'beam.*?=\s*([\d.]+)'],
            'wall_thickness': [r'wall.*?=\s*([\d.]+)', r'thickness\s*=\s*([\d.]+)'],
        }
        
        for key, pattern_list in patterns.items():
            for pattern in pattern_list:
                match = re.search(pattern, scad, re.IGNORECASE)
                if match:
                    try:
                        params[key] = float(match.group(1))
                        break
                    except (ValueError, IndexError):
                        pass
        
        return params
    
    def _check_geometry(self, params: dict) -> dict:
        """Validate geometric proportions against best practices."""
        issues = []
        warnings = []
        
        if params.get('span_length') and params.get('arch_height'):
            ratio = params['arch_height'] / params['span_length']
            if ratio < 0.08:
                warnings.append(f"Arch rise-to-span ratio ({ratio:.3f}) is very flat; typical: 0.10-0.20")
            elif ratio > 0.40:
                warnings.append(f"Arch rise-to-span ratio ({ratio:.3f}) is very high; typical: 0.10-0.20")
        
        if params.get('deck_width', 0) < 16:
            issues.append(f"Deck width ({params['deck_width']}) below minimum clearance (16-24 units)")
        elif params.get('deck_width', 0) > 100:
            warnings.append(f"Deck width ({params['deck_width']}) unusually wide; verify support capacity")
        
        if params.get('span_length', 0) < 40:
            issues.append(f"Span length ({params['span_length']}) appears short for a bridge")
        
        return {
            'issues': issues,
            'warnings': warnings,
            'parameters_checked': len(params),
        }
    
    def _check_safety_params(self, params: dict) -> dict:
        """Validate safety-critical parameters."""
        issues = []
        warnings = []
        
        # Support spacing
        if params.get('support_count', 0) < 2:
            issues.append("Insufficient support count; minimum 2 required for stability")
        
        # Cable properties
        if 'cable_radius' in params and params['cable_radius'] < 0.3:
            warnings.append(f"Cable radius ({params['cable_radius']}) may be too small")
        
        # Deck thickness
        if 'deck_thickness' in params and params['deck_thickness'] < 2:
            warnings.append(f"Deck thickness ({params['deck_thickness']}) below typical minimum (2-4 units)")
        
        # Pylon height for suspension
        if 'suspension' in str(params).lower() or params.get('suspension_cables'):
            if params.get('pylon_height', 0) < params.get('span_length', 0) / 4:
                issues.append("Pylon height insufficient for suspension cables (typical: span/4 to span/3)")
        
        return {
            'issues': issues,
            'warnings': warnings,
            'critical_checks': 4,
        }
    
    def _check_materials(self, scad: str) -> dict:
        """Identify materials mentioned in design."""
        materials = {}
        material_keywords = {
            'steel': ['steel', 'metal', 'iron'],
            'concrete': ['concrete', 'cement'],
            'composite': ['composite', 'fiber', 'reinforced'],
            'wood': ['wood', 'timber'],
            'cable': ['cable', 'steel cable', 'wire rope'],
        }
        
        for material, keywords in material_keywords.items():
            for keyword in keywords:
                if keyword.lower() in scad.lower():
                    materials[material] = True
                    break
        
        issues = []
        if not materials:
            issues.append("No materials explicitly defined; CalTrans standards require material specification")
        
        return {
            'materials_identified': materials,
            'issues': issues,
        }
    
    def _check_loading_capacity(self, params: dict) -> dict:
        """Estimate loading capacity from geometry."""
        warnings = []
        
        span = params.get('span_length', 100)
        deck_width = params.get('deck_width', 20)
        deck_thickness = params.get('deck_thickness', 3)
        supports = params.get('support_count', 2)
        
        # Rough capacity estimate (not rigorous; for indication only)
        estimated_capacity = (deck_thickness * deck_width * supports) / (span / 10)
        
        if estimated_capacity < 1:
            warnings.append(f"Estimated load capacity very low; verify structural design")
        
        return {
            'estimated_capacity_units': estimated_capacity,
            'calculation_basis': 'thickness × width × supports / (span÷10)',
            'warnings': warnings,
            'note': 'Estimate only; full FEA required for production design',
        }
    
    def _find_applicable_standards(self, design_name: str, params: dict) -> list:
        """Find relevant CalTrans standards for this design."""
        standards = self.standards.find_relevant_standards(design_name, params)
        
        # Add standard interpretations
        for std in standards:
            if 'xs16' in std.get('title', '').lower():
                std['category_description'] = 'Steel structures'
            elif 'xs20' in std.get('title', '').lower():
                std['category_description'] = 'Bearings and expansion joints'
            elif 'xs17' in std.get('title', '').lower():
                std['category_description'] = 'Utilities and drainage'
        
        return standards
    
    def _calculate_compliance(self, checks: dict) -> float:
        """Calculate overall compliance score (0-100)."""
        score = 100
        
        # Deduct for issues
        geometry_issues = len(checks['geometry'].get('issues', []))
        safety_issues = len(checks['safety'].get('issues', []))
        material_issues = len(checks['materials'].get('issues', []))
        
        score -= geometry_issues * 10
        score -= safety_issues * 15
        score -= material_issues * 10
        
        # Deduct for warnings
        geometry_warnings = len(checks['geometry'].get('warnings', []))
        safety_warnings = len(checks['safety'].get('warnings', []))
        loading_warnings = len(checks['loading'].get('warnings', []))
        
        score -= geometry_warnings * 3
        score -= safety_warnings * 5
        score -= loading_warnings * 2
        
        return max(0, min(100, score))
    
    def _generate_report(self, checks: dict, params: dict, design_name: str) -> str:
        """Generate a human-readable validation report."""
        report = []
        report.append(f"BRIDGE DESIGN VALIDATION REPORT")
        report.append(f"Design: {design_name}")
        report.append(f"Generated: {__import__('datetime').datetime.now().isoformat()}")
        report.append("=" * 70)
        
        # Summary
        score = self._calculate_compliance(checks)
        status = "PASS ✓" if score >= 80 else "REVIEW ⚠" if score >= 60 else "FAIL ✗"
        report.append(f"\nCOMPLIANCE SCORE: {score}/100 [{status}]")
        
        # Geometry
        report.append(f"\n[GEOMETRY]")
        for issue in checks['geometry'].get('issues', []):
            report.append(f"  ✗ {issue}")
        for warning in checks['geometry'].get('warnings', []):
            report.append(f"  ⚠ {warning}")
        
        # Safety
        report.append(f"\n[SAFETY]")
        for issue in checks['safety'].get('issues', []):
            report.append(f"  ✗ {issue}")
        for warning in checks['safety'].get('warnings', []):
            report.append(f"  ⚠ {warning}")
        
        # Materials
        report.append(f"\n[MATERIALS]")
        materials = checks['materials'].get('materials_identified', {})
        if materials:
            report.append(f"  Identified: {', '.join(materials.keys())}")
        else:
            report.append(f"  ✗ {checks['materials']['issues'][0]}")
        
        # Loading
        report.append(f"\n[LOADING CAPACITY]")
        report.append(f"  Estimated capacity: {checks['loading']['estimated_capacity_units']:.2f} units")
        report.append(f"  {checks['loading']['note']}")
        
        # Standards Reference
        report.append(f"\n[APPLICABLE STANDARDS]")
        for i, std in enumerate(checks['standards_reference'][:5], 1):
            report.append(f"  {i}. {std['title']}")
            if 'category_description' in std:
                report.append(f"     ({std['category_description']})")
        
        # Recommendations
        report.append(f"\n[RECOMMENDATIONS]")
        report.append("  1. Obtain detailed CalTrans standard sheets for design category")
        report.append("  2. Perform full finite element analysis (FEA)")
        report.append("  3. Verify materials meet CalTrans specifications")
        report.append("  4. Review loading and safety factors with engineer")
        report.append("  5. Submit for professional structural review")
        
        return "\n".join(report)


def main():
    """Validate all sketches or a specific one."""
    import sys
    
    validator = BridgeCodeValidator("bridge_standards.db")
    
    if len(sys.argv) > 1:
        # Validate specific sketch
        sketch_id = sys.argv[1]
        try:
            sketch = Sketch.objects.get(pk=sketch_id)
            validation = validator.validate_sketch(sketch)
            print(validation['report'])
            
            # Save to file
            report_file = f"validation_report_{sketch_id}.txt"
            with open(report_file, 'w') as f:
                f.write(validation['report'])
            print(f"\n✓ Report saved to {report_file}")
            
        except Sketch.DoesNotExist:
            print(f"Sketch #{sketch_id} not found")
    else:
        # Validate all sketches
        sketches = Sketch.objects.filter(scad_source__isnull=False).exclude(scad_source='')
        print(f"Validating {sketches.count()} sketches...\n")
        
        for sketch in sketches:
            validation = validator.validate_sketch(sketch)
            print(f"[{validation['compliance_score']}/100] {validation['design_name'][:50]}")
            for issue in validation['validation_checks']['geometry'].get('issues', []):
                print(f"    ✗ {issue}")


if __name__ == "__main__":
    main()
