"""Deterministic OpenSCAD templates used as a high-quality fallback."""
from __future__ import annotations
import re


def _num(text: str, default: float) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm)?", text)
    if not m:
        return default
    val = float(m.group(1))
    return val * 10.0 if (m.group(2) == "cm") else val


def _bridge_span(prompt: str) -> float:
        return max(60.0, min(180.0, _num(prompt.lower(), 120.0)))


def truss_bridge(prompt: str) -> str:
        span = _bridge_span(prompt)
        width = round(span * 0.22, 2)
        deck = round(span * 0.055, 2)
        height = round(span * 0.26, 2)
        bay_count = 8 if span < 130 else 10
        bay = round(span / bay_count, 3)
        rail = round(max(1.2, span * 0.012), 2)
        pier_h = round(span * 0.17, 2)

        return f"""// scadforge civic truss bridge
// Prompt: printable bridge with deck, piers, railings, and Warren trusses.
    $fn=18;

span={span};
width={width};
deck_t={deck};
truss_h={height};
bay_n={bay_count};
bay={bay};
rail_r={rail};
pier_h={pier_h};

module rounded_box(size=[10,10,10], r=1.2) {{
    cube(size, center=true);
}}

module strut(a=[0,0,0], b=[1,0,0], r=1) {{
    hull() {{
        translate(a) cube([r*2,r*2,r*2], center=true);
        translate(b) cube([r*2,r*2,r*2], center=true);
    }}
}}

module pier(x=0) {{
    translate([x, -width*0.33, -pier_h/2-deck_t/2]) rounded_box([width*0.18, width*0.18, pier_h], 1.1);
    translate([x,  width*0.33, -pier_h/2-deck_t/2]) rounded_box([width*0.18, width*0.18, pier_h], 1.1);
    translate([x, 0, -deck_t*0.85]) cube([width*0.55, width*0.95, deck_t*0.45], center=true);
}}

module side_truss(y=0) {{
    z0=deck_t/2 + rail_r;
    z1=truss_h;
    // top and bottom chords
    strut([-span/2,y,z0], [span/2,y,z0], rail_r);
    strut([-span/2,y,z1], [span/2,y,z1], rail_r);
    // vertical end posts
    strut([-span/2,y,z0], [-span/2,y,z1], rail_r*0.9);
    strut([ span/2,y,z0], [ span/2,y,z1], rail_r*0.9);
    // Warren truss triangles with alternating diagonals
    for(i=[0:bay_n-1]) {{
        x0=-span/2 + i*bay;
        x1=x0 + bay;
        xm=(x0+x1)/2;
        strut([x0,y,z0], [xm,y,z1], rail_r*0.75);
        strut([xm,y,z1], [x1,y,z0], rail_r*0.75);
        strut([x0,y,z0], [x0,y,z1*0.72], rail_r*0.52);
    }}
}}

module guard_rails() {{
    for(y=[-width/2-rail_r*1.4, width/2+rail_r*1.4]) {{
        strut([-span/2,y,deck_t*1.35], [span/2,y,deck_t*1.35], rail_r*0.5);
        for(i=[0:bay_n]) {{
            x=-span/2 + i*bay;
            strut([x,y,deck_t/2], [x,y,deck_t*1.65], rail_r*0.38);
        }}
    }}
}}

module bridge() {{
    // road deck and thin asphalt cap
    translate([0,0,0]) rounded_box([span, width, deck_t], 1.4);
    translate([0,0,deck_t/2+0.22]) cube([span*0.92, width*0.72, 0.45], center=true);
    // abutments and piers
    pier(-span*0.42); pier(0); pier(span*0.42);
    translate([-span/2-width*0.18,0,-deck_t*0.52]) rounded_box([width*0.35,width*1.2,deck_t*1.25],1.0);
    translate([ span/2+width*0.18,0,-deck_t*0.52]) rounded_box([width*0.35,width*1.2,deck_t*1.25],1.0);
    side_truss(-width/2-rail_r*2.2);
    side_truss( width/2+rail_r*2.2);
    // cross braces between trusses
    for(i=[0:bay_n]) {{
        x=-span/2 + i*bay;
        strut([x,-width/2-rail_r*2.2,truss_h], [x,width/2+rail_r*2.2,truss_h], rail_r*0.45);
    }}
    guard_rails();
}}

bridge();
"""


def arched_bridge(prompt: str) -> str:
        span = _bridge_span(prompt)
        width = round(span * 0.24, 2)
        arch_h = round(span * 0.34, 2)
        deck_t = round(span * 0.055, 2)
        rib = round(max(1.6, span * 0.018), 2)
        posts = 9

        return f"""// scadforge arched civic bridge
    $fn=18;
span={span}; width={width}; arch_h={arch_h}; deck_t={deck_t}; rib={rib}; posts={posts};

    module strut(a=[0,0,0], b=[1,0,0], r=1) {{ hull() {{ translate(a) cube([r*2,r*2,r*2], center=true); translate(b) cube([r*2,r*2,r*2], center=true); }} }}
    module rounded_box(size=[10,10,10], r=1) {{ cube(size, center=true); }}

function arch_z(x) = deck_t/2 + arch_h * (1 - pow((2*x/span),2));

module arch_side(y=0) {{
    steps=20;
    for(i=[0:steps-1]) {{
        x0=-span/2 + i*span/steps;
        x1=-span/2 + (i+1)*span/steps;
        strut([x0,y,arch_z(x0)], [x1,y,arch_z(x1)], rib);
    }}
    strut([-span/2,y,deck_t/2], [span/2,y,deck_t/2], rib*0.7);
    for(i=[1:posts-1]) {{
        x=-span/2 + i*span/posts;
        strut([x,y,deck_t/2], [x,y,arch_z(x)], rib*0.48);
    }}
}}

module bridge() {{
    translate([0,0,0]) rounded_box([span, width, deck_t], 1.3);
    for(y=[-width/2-rib*2.0, width/2+rib*2.0]) arch_side(y);
    for(i=[0:posts]) {{
        x=-span/2 + i*span/posts;
        strut([x,-width/2-rib*2,arch_z(x)], [x,width/2+rib*2,arch_z(x)], rib*0.42);
    }}
    for(y=[-width/2, width/2]) {{
        strut([-span/2,y,deck_t*1.4], [span/2,y,deck_t*1.4], rib*0.35);
        for(i=[0:posts]) {{
            x=-span/2 + i*span/posts;
            strut([x,y,deck_t/2], [x,y,deck_t*1.75], rib*0.28);
        }}
    }}
    translate([-span*0.38,0,-deck_t*2]) rounded_box([width*0.32,width*0.8,deck_t*4],1.0);
    translate([ span*0.38,0,-deck_t*2]) rounded_box([width*0.32,width*0.8,deck_t*4],1.0);
}}
bridge();
"""


def suspension_bridge(prompt: str) -> str:
        span = _bridge_span(prompt)
        width = round(span * 0.21, 2)
        tower_h = round(span * 0.42, 2)
        deck_t = round(span * 0.045, 2)
        cable_r = round(max(1.0, span * 0.01), 2)
        tower_x = round(span * 0.32, 2)
        hangers = 14

        return f"""// scadforge suspension bridge concept
    $fn=18;
span={span}; width={width}; tower_h={tower_h}; deck_t={deck_t}; cable_r={cable_r}; tower_x={tower_x}; hangers={hangers};

    module strut(a=[0,0,0], b=[1,0,0], r=1) {{ hull() {{ translate(a) cube([r*2,r*2,r*2], center=true); translate(b) cube([r*2,r*2,r*2], center=true); }} }}
module tower(x=0, y=0) {{
    strut([x,y,-deck_t/2], [x,y,tower_h], cable_r*1.4);
    strut([x,y+width*0.18,-deck_t/2], [x,y+width*0.18,tower_h], cable_r*1.4);
    strut([x,y,tower_h*0.55], [x,y+width*0.18,tower_h*0.55], cable_r*1.0);
    strut([x,y,tower_h], [x,y+width*0.18,tower_h], cable_r*1.0);
}}
function cable_z(x) = deck_t*1.8 + tower_h*0.82 - tower_h*0.50 * (1 - pow((2*x/span),2));

module bridge() {{
    translate([0,0,0]) cube([span,width,deck_t], center=true);
    for(y=[-width/2, width/2]) {{
        tower(-tower_x,y); tower(tower_x,y);
        steps=24;
        for(i=[0:steps-1]) {{
            x0=-span/2+i*span/steps; x1=-span/2+(i+1)*span/steps;
            strut([x0,y,cable_z(x0)], [x1,y,cable_z(x1)], cable_r);
        }}
        for(i=[1:hangers-1]) {{
            x=-span/2+i*span/hangers;
            strut([x,y,deck_t/2], [x,y,cable_z(x)], cable_r*0.32);
        }}
        strut([-span/2,y,deck_t*1.4], [span/2,y,deck_t*1.4], cable_r*0.45);
    }}
    for(x=[-tower_x,tower_x]) strut([x,-width/2,tower_h], [x,width/2,tower_h], cable_r*0.8);
}}
bridge();
"""


def from_keywords(prompt: str) -> str:
    p = prompt.lower()
    size = _num(p, 20.0)

    if "bridge" in p or "viaduct" in p or "overpass" in p:
        if "suspension" in p or "cable" in p or "golden gate" in p:
            return suspension_bridge(prompt)
        if "arch" in p or "arched" in p or "stone" in p:
            return arched_bridge(prompt)
        return truss_bridge(prompt)

    if "sphere" in p or "ball" in p:
        return f"$fn=80;\nsphere(r={size/2});\n"

    if "cylinder" in p or "tube" in p or "pipe" in p:
        h = size
        r = max(2.0, size / 3)
        if "tube" in p or "pipe" in p:
            return (f"$fn=64;\ndifference() {{\n"
                    f"  cylinder(h={h}, r={r}, center=true);\n"
                    f"  cylinder(h={h+1}, r={r*0.6}, center=true);\n}}\n")
        return f"$fn=64;\ncylinder(h={h}, r={r}, center=true);\n"

    if "nut" in p or "hex" in p:
        across = size
        hole = across / 2
        return (f"$fn=6;\ndifference() {{\n"
                f"  cylinder(h={across/3}, r={across/2}, center=true);\n"
                f"  $fn=48; cylinder(h={across}, r={hole/2}, center=true);\n}}\n")

    if "ring" in p or "torus" in p or "donut" in p:
        R, r = size / 2, size / 6
        return (f"$fn=80;\nrotate_extrude() translate([{R},0,0]) circle(r={r});\n")

    if "pyramid" in p or "cone" in p:
        return f"$fn=64;\ncylinder(h={size}, r1={size/2}, r2=0);\n"

    if "gear" in p:
        teeth = 12
        return ("$fn=80;\n"
                "module cog(d=30, h=6, t=12){\n"
                "  difference(){\n"
                "    union(){\n"
                "      cylinder(h=h, d=d, center=true);\n"
                "      for(i=[0:t-1])\n"
                "        rotate([0,0,i*360/t])\n"
                "          translate([d/2,0,0])\n"
                "            cube([d/10,d/8,h], center=true);\n"
                "    }\n"
                "    cylinder(h=h+1, d=d/4, center=true);\n"
                "  }\n"
                "}\n"
                f"cog(d={size}, h={max(3, size/5)}, t={teeth});\n")

    # default: a chamfered block
    return (f"$fn=48;\nminkowski() {{\n"
            f"  cube([{size}, {size}, {size/2}], center=true);\n"
            f"  sphere(r={max(1, size/20)});\n}}\n")
