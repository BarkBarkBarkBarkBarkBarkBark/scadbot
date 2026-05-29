#!/usr/bin/env python3
"""
Scrape CalTrans bridge standard details and build a searchable RAG.
Stores document metadata and creates a local knowledge base for validation.
"""

import os
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


@dataclass
class BridgeStandard:
    """A single bridge standard document or section."""
    title: str
    url: str
    content: str
    section_id: Optional[str] = None
    category: Optional[str] = None
    fetched_at: str = ""
    
    def __post_init__(self):
        if not self.fetched_at:
            self.fetched_at = datetime.now().isoformat()


class BridgeStandardsScraper:
    """Scrape and store bridge standards from CalTrans."""
    
    BASE_URL = "https://dot.ca.gov/programs/engineering-services/manuals/bridge-standard-details"
    
    def __init__(self, db_path: str = "bridge_standards.db"):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; BridgeStandardsRAG/1.0)'
        })
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database for storing standards."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS standards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT UNIQUE,
                content TEXT,
                section_id TEXT,
                category TEXT,
                keywords TEXT,
                fetched_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a page and return BeautifulSoup object."""
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.content, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def extract_text_with_structure(self, soup: BeautifulSoup) -> str:
        """Extract meaningful text from page, preserving structure."""
        # Remove script/style tags
        for tag in soup(['script', 'style', 'nav', 'footer']):
            tag.decompose()
        
        # Extract headers, paragraphs, lists as structured text
        text_parts = []
        main = soup.find(['main', 'article']) or soup.find('body')
        
        if not main:
            main = soup
        
        for elem in main.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td']):
            text = elem.get_text(strip=True)
            if text and len(text) > 3:
                if elem.name.startswith('h'):
                    text_parts.append(f"\n## {text}\n")
                elif elem.name in ['li']:
                    text_parts.append(f"  • {text}\n")
                else:
                    text_parts.append(f"{text}\n")
        
        return "".join(text_parts)
    
    def extract_pdf_links(self, soup: BeautifulSoup) -> list[dict]:
        """Extract PDF and document links from page."""
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(href.lower().endswith(ext) for ext in ['.pdf', '.doc', '.docx']):
                links.append({
                    'title': a.get_text(strip=True),
                    'url': urljoin(self.BASE_URL, href),
                    'type': href.split('.')[-1].lower()
                })
        return links
    
    def scrape_main_page(self) -> list[BridgeStandard]:
        """Scrape the main bridge standards page."""
        print(f"Fetching main page: {self.BASE_URL}")
        soup = self.fetch_page(self.BASE_URL)
        if not soup:
            return []
        
        standards = []
        text_content = self.extract_text_with_structure(soup)
        
        # Store main page content
        if text_content.strip():
            standards.append(BridgeStandard(
                title="Bridge Standard Details Overview",
                url=self.BASE_URL,
                content=text_content,
                category="Overview"
            ))
        
        # Extract and process document links
        doc_links = self.extract_pdf_links(soup)
        print(f"Found {len(doc_links)} document links")
        
        for doc in doc_links:
            print(f"  - {doc['title']} ({doc['type']})")
            # Note: PDF extraction would require additional libs (PyPDF2, pdfplumber)
            # For now, store metadata
            standards.append(BridgeStandard(
                title=doc['title'],
                url=doc['url'],
                content=f"[{doc['type'].upper()} Document]\n{doc['title']}\n{doc['url']}",
                category=self._categorize_doc(doc['title'])
            ))
        
        return standards
    
    def _categorize_doc(self, title: str) -> str:
        """Guess category from document title."""
        title_lower = title.lower()
        if any(x in title_lower for x in ['suspension', 'cable', 'catenary']):
            return "Suspension Bridges"
        elif any(x in title_lower for x in ['arch', 'bow']):
            return "Arch Bridges"
        elif any(x in title_lower for x in ['truss', 'beam']):
            return "Truss & Beam Bridges"
        elif any(x in title_lower for x in ['steel', 'material']):
            return "Materials"
        elif any(x in title_lower for x in ['foundation', 'pier', 'abutment']):
            return "Foundations & Supports"
        elif any(x in title_lower for x in ['load', 'force', 'stress', 'design']):
            return "Design & Loading"
        elif any(x in title_lower for x in ['safety', 'rail', 'guard']):
            return "Safety"
        else:
            return "General"
    
    def save_standards(self, standards: list[BridgeStandard]):
        """Save standards to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for std in standards:
            keywords = " ".join([
                std.title.lower(),
                (std.category or "").lower(),
                std.content[:200].lower()
            ])
            
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO standards
                    (title, url, content, section_id, category, keywords, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    std.title,
                    std.url,
                    std.content,
                    std.section_id,
                    std.category,
                    keywords,
                    std.fetched_at
                ))
            except sqlite3.IntegrityError:
                pass  # URL already exists
        
        conn.commit()
        conn.close()
        print(f"Saved {len(standards)} standards to {self.db_path}")
    
    def list_standards(self, category: Optional[str] = None) -> list[dict]:
        """List all stored standards, optionally filtered by category."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute(
                "SELECT title, category, url FROM standards WHERE category = ? ORDER BY title",
                (category,)
            )
        else:
            cursor.execute("SELECT title, category, url FROM standards ORDER BY category, title")
        
        results = [
            {'title': r[0], 'category': r[1], 'url': r[2]}
            for r in cursor.fetchall()
        ]
        conn.close()
        return results
    
    def search_standards(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search standards by keyword."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Simple keyword search in keywords and content
        search_term = f"%{query.lower()}%"
        cursor.execute("""
            SELECT title, category, content, url
            FROM standards
            WHERE keywords LIKE ? OR content LIKE ?
            ORDER BY (
                CASE WHEN title LIKE ? THEN 1
                     WHEN keywords LIKE ? THEN 2
                     ELSE 3
                END
            )
            LIMIT ?
        """, (search_term, search_term, search_term, search_term, limit))
        
        results = [
            {
                'title': r[0],
                'category': r[1],
                'content_preview': r[2][:300] + "..." if len(r[2]) > 300 else r[2],
                'url': r[3]
            }
            for r in cursor.fetchall()
        ]
        conn.close()
        return results


class BridgeDesignValidator:
    """Validate bridge designs against standards."""
    
    def __init__(self, db_path: str = "bridge_standards.db"):
        self.db_path = db_path
    
    def validate_design(self, scad_content: str, design_name: str = "Unknown") -> dict:
        """Validate a bridge design (OpenSCAD source) against known standards."""
        issues = []
        warnings = []
        recommendations = []
        
        # Extract design parameters from SCAD
        params = self._extract_scad_params(scad_content)
        
        # Check against standards
        if params.get('deck_width') and params['deck_width'] < 20:
            warnings.append("Deck width appears narrow (<20 units); verify clearance standards")
        
        if params.get('cable_count', 0) == 0 and 'suspension' in design_name.lower():
            issues.append("Suspension bridge should define cable configurations")
        
        if params.get('arch_height'):
            if params['arch_height'] < params.get('span_length', 100) / 10:
                recommendations.append("Arch rise-to-span ratio may be non-optimal (typical: 1/8 to 1/5)")
        
        # Search for relevant standards
        validator = BridgeStandardsValidator(self.db_path)
        relevant_docs = validator.find_relevant_standards(design_name, params)
        
        return {
            'design': design_name,
            'issues': issues,
            'warnings': warnings,
            'recommendations': recommendations,
            'parameters': params,
            'relevant_standards': relevant_docs
        }
    
    def _extract_scad_params(self, scad: str) -> dict:
        """Extract key parameters from OpenSCAD source."""
        params = {}
        
        # Simple regex extraction for common variable names
        patterns = {
            'deck_width': r'deck_width\s*=\s*(\d+(?:\.\d+)?)',
            'span_length': r'bridge_length\s*=\s*(\d+(?:\.\d+)?)',
            'arch_height': r'arch_height\s*=\s*(\d+(?:\.\d+)?)',
            'cable_count': r'(?:cable|suspension).*?(\d+)',
            'pylon_height': r'pylon_height\s*=\s*(\d+(?:\.\d+)?)',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, scad, re.IGNORECASE)
            if match:
                try:
                    params[key] = float(match.group(1))
                except (ValueError, IndexError):
                    pass
        
        return params


class BridgeStandardsValidator:
    """Query standards database for validation."""
    
    def __init__(self, db_path: str = "bridge_standards.db"):
        self.db_path = db_path
    
    def find_relevant_standards(self, design_type: str, params: dict) -> list[dict]:
        """Find relevant standards for a given design type and parameters."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        keywords = []
        if 'suspension' in design_type.lower():
            keywords.extend(['suspension', 'cable', 'catenary'])
        elif 'arch' in design_type.lower():
            keywords.extend(['arch', 'bow'])
        elif 'truss' in design_type.lower():
            keywords.extend(['truss', 'beam'])
        
        keywords.extend(['load', 'safety', 'material', 'design'])
        
        results = []
        for kw in keywords:
            cursor.execute(
                "SELECT title, category, url FROM standards WHERE keywords LIKE ? LIMIT 3",
                (f"%{kw}%",)
            )
            results.extend([
                {'title': r[0], 'category': r[1], 'url': r[2], 'keyword': kw}
                for r in cursor.fetchall()
            ])
        
        conn.close()
        
        # Deduplicate by title
        seen = set()
        unique = []
        for r in results:
            if r['title'] not in seen:
                unique.append(r)
                seen.add(r['title'])
        
        return unique[:5]


def main():
    """Run the scraper and demonstrate usage."""
    print("=" * 70)
    print("CalTrans Bridge Standards RAG Scraper")
    print("=" * 70)
    
    scraper = BridgeStandardsScraper("bridge_standards.db")
    
    # Scrape standards
    print("\n[1] Scraping CalTrans bridge standards...")
    standards = scraper.scrape_main_page()
    
    if standards:
        scraper.save_standards(standards)
        print(f"✓ Scraped {len(standards)} standards")
    else:
        print("✗ No standards found")
    
    # List available standards
    print("\n[2] Available standard categories:")
    all_standards = scraper.list_standards()
    categories = set(s['category'] for s in all_standards if s['category'])
    for cat in sorted(categories):
        count = len([s for s in all_standards if s['category'] == cat])
        print(f"  • {cat}: {count} standards")
    
    # Demonstrate search
    print("\n[3] Searching for 'suspension bridge'...")
    results = scraper.search_standards("suspension bridge")
    for r in results[:3]:
        print(f"  • {r['title']}")
        print(f"    {r['content_preview']}")
        print()
    
    # Validate a design
    print("\n[4] Validating example bridge design...")
    validator = BridgeDesignValidator("bridge_standards.db")
    
    civic_bridge_scad = open("models/civic_ribbon_bridge.scad").read()
    validation = validator.validate_design(civic_bridge_scad, "Civic Ribbon Bridge")
    
    print(f"Design: {validation['design']}")
    print(f"Parameters extracted: {validation['parameters']}")
    if validation['issues']:
        print(f"Issues: {validation['issues']}")
    if validation['warnings']:
        print(f"Warnings: {validation['warnings']}")
    if validation['recommendations']:
        print(f"Recommendations: {validation['recommendations']}")
    print(f"\nRelevant Standards:")
    for std in validation['relevant_standards']:
        print(f"  • {std['title']} ({std['category']})")
        print(f"    {std['url']}")


if __name__ == "__main__":
    main()
