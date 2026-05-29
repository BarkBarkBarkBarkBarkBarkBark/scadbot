#!/usr/bin/env python3
"""
CLI tool for bridge standards RAG and design validation.
Usage: python bridge_rag_cli.py [command] [args]
"""

import sys
import argparse
from pathlib import Path
from scrape_bridge_standards import BridgeStandardsScraper, BridgeDesignValidator


def cmd_scrape(args):
    """Scrape CalTrans standards."""
    scraper = BridgeStandardsScraper(args.db)
    print(f"Scraping CalTrans standards to {args.db}...")
    standards = scraper.scrape_main_page()
    if standards:
        scraper.save_standards(standards)
        print(f"✓ Scraped and saved {len(standards)} standards")
    else:
        print("✗ No standards found")


def cmd_search(args):
    """Search standards database."""
    scraper = BridgeStandardsScraper(args.db)
    results = scraper.search_standards(args.query, limit=args.limit)
    
    if not results:
        print(f"No results for: {args.query}")
        return
    
    print(f"\nSearch results for '{args.query}' ({len(results)} results):\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['title']}")
        print(f"   Category: {r['category']}")
        print(f"   URL: {r['url']}")
        if args.verbose:
            print(f"   Preview: {r['content_preview'][:150]}...")
        print()


def cmd_list(args):
    """List standards by category."""
    scraper = BridgeStandardsScraper(args.db)
    
    if args.category:
        standards = scraper.list_standards(category=args.category)
        print(f"\n[{args.category}] ({len(standards)} standards):\n")
    else:
        standards = scraper.list_standards()
        categories = {}
        for s in standards:
            cat = s['category'] or 'Unknown'
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(s)
        
        print("\nStandards by category:\n")
        for cat in sorted(categories.keys()):
            print(f"  {cat}: {len(categories[cat])} standards")
        print()
        return
    
    for std in standards:
        print(f"  • {std['title']}")
        print(f"    {std['url']}")


def cmd_validate(args):
    """Validate an OpenSCAD file or Django sketch."""
    import os
    
    if args.scad_file:
        # Validate OpenSCAD file directly
        if not Path(args.scad_file).exists():
            print(f"✗ File not found: {args.scad_file}")
            return
        
        scad_code = Path(args.scad_file).read_text()
        design_name = Path(args.scad_file).stem
    elif args.sketch_id:
        # Validate Django sketch
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'forge.settings')
        import django
        django.setup()
        from sketches.models import Sketch
        
        try:
            sketch = Sketch.objects.get(pk=args.sketch_id)
            scad_code = sketch.scad_source
            design_name = sketch.prompt[:50]
        except Sketch.DoesNotExist:
            print(f"✗ Sketch #{args.sketch_id} not found")
            return
    else:
        print("✗ Provide either --scad-file or --sketch-id")
        return
    
    validator = BridgeDesignValidator(args.db)
    validation = validator.validate_design(scad_code, design_name)
    
    print("\nDESIGN VALIDATION RESULTS")
    print("=" * 60)
    print(f"Design: {validation['design']}")
    print(f"Parameters: {validation['parameters']}")
    print(f"Relevant Standards: {len(validation['relevant_standards'])}")
    
    for std in validation['relevant_standards']:
        print(f"  • {std['title']}")
    
    if validation['issues']:
        print(f"\nIssues ({len(validation['issues'])}):")
        for issue in validation['issues']:
            print(f"  ✗ {issue}")
    
    if validation['warnings']:
        print(f"\nWarnings ({len(validation['warnings'])}):")
        for warning in validation['warnings']:
            print(f"  ⚠ {warning}")
    
    if validation['recommendations']:
        print(f"\nRecommendations:")
        for rec in validation['recommendations']:
            print(f"  → {rec}")


def cmd_stats(args):
    """Show database statistics."""
    scraper = BridgeStandardsScraper(args.db)
    
    all_standards = scraper.list_standards()
    categories = set(s['category'] for s in all_standards if s['category'])
    
    print(f"\nDatabase: {args.db}")
    print(f"Total standards: {len(all_standards)}")
    print(f"Categories: {len(categories)}")
    print()
    
    for cat in sorted(categories):
        count = len([s for s in all_standards if s['category'] == cat])
        print(f"  {cat}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description='Bridge Standards RAG & Design Validation CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape CalTrans standards
  python bridge_rag_cli.py scrape

  # Search for "suspension bridge"
  python bridge_rag_cli.py search "suspension bridge" -v

  # List all "Arch Bridges" standards
  python bridge_rag_cli.py list --category "Arch Bridges"

  # Validate an OpenSCAD file
  python bridge_rag_cli.py validate --scad-file models/my_bridge.scad

  # Validate a Django sketch (requires Django setup)
  python bridge_rag_cli.py validate --sketch-id 7

  # Show database stats
  python bridge_rag_cli.py stats
        """
    )
    
    parser.add_argument('--db', default='bridge_standards.db', help='Path to database')
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # Scrape
    subparsers.add_parser('scrape', help='Scrape CalTrans standards')
    
    # Search
    search_parser = subparsers.add_parser('search', help='Search standards')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('-l', '--limit', type=int, default=10, help='Limit results')
    search_parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    
    # List
    list_parser = subparsers.add_parser('list', help='List standards')
    list_parser.add_argument('-c', '--category', help='Filter by category')
    
    # Validate
    validate_parser = subparsers.add_parser('validate', help='Validate design')
    validate_parser.add_argument('--scad-file', help='Path to OpenSCAD file')
    validate_parser.add_argument('--sketch-id', type=int, help='Django sketch ID')
    
    # Stats
    subparsers.add_parser('stats', help='Show database statistics')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Dispatch to command
    commands = {
        'scrape': cmd_scrape,
        'search': cmd_search,
        'list': cmd_list,
        'validate': cmd_validate,
        'stats': cmd_stats,
    }
    
    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
