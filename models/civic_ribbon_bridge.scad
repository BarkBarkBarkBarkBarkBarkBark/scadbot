// Civic Ribbon Bridge — presentation OpenSCAD model
// A philanthropic landmark bridge: resilient structure, public garden, and civic beacon.
$fn = 32;

bridge_length = 190;
deck_width = 26;
deck_z = 10;

module rod(a, b, r=0.45) {
    v = [b[0]-a[0], b[1]-a[1], b[2]-a[2]];
    L = sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]);
    if (L > 0.01) {
        translate(a)
            rotate(a = acos(v[2] / L), v = [-v[1], v[0], 0])
                cylinder(h=L, r=r, center=false);
    }
}

module rounded_block(size=[10,10,10], radius=1.5) {
    hull() {
        for (x=[-1,1], y=[-1,1])
            translate([x*(size[0]/2-radius), y*(size[1]/2-radius), 0])
                cylinder(h=size[2], r=radius, center=true);
    }
}

module tapered_pylon(x, y) {
    color("LightSteelBlue")
    hull() {
        translate([x, y, deck_z]) cube([6, 4.2, 3], center=true);
        translate([x, y*0.72, 54]) cube([3.2, 3.0, 3], center=true);
    }
    color("white") translate([x, y*0.86, 57]) sphere(r=2.6);
    color("gold") translate([x, y*0.86, 61]) cylinder(h=6, r1=1.1, r2=0.25, center=false);
}

function arch_z(x) = deck_z + 6 + 31*(1 - (x*x)/(78*78));
function cable_z(x) = deck_z + 14 + 34*((x*x)/(82*82));

module tower_group(x) {
    tapered_pylon(x, -deck_width/2-5);
    tapered_pylon(x,  deck_width/2+5);
    color("Gainsboro") rod([x,-deck_width/2-5,52], [x,deck_width/2+5,52], 1.1);
    color("Gainsboro") rod([x,-deck_width/2-5,37], [x,deck_width/2+5,37], 0.8);
    color("SlateGray") rod([x,-deck_width/2-5,deck_z+1], [x,deck_width/2+5,deck_z+1], 1.4);
}

module bridge_deck() {
    color("DimGray") translate([0,0,deck_z]) rounded_block([bridge_length, deck_width, 3.2], 2.4);
    color("SlateGray") translate([0,0,deck_z-3.2]) cube([bridge_length, 18, 2.4], center=true);
    color("White") for (x=[-78:12:78]) translate([x,0,deck_z+1.71]) cube([5.5,0.55,0.12], center=true);
    color("Gold") for (y=[-6,6]) translate([0,y,deck_z+1.76]) cube([bridge_length-16,0.26,0.13], center=true);
    color("ForestGreen") for (x=[-72:24:72], y=[-deck_width/2+2.4, deck_width/2-2.4])
        translate([x,y,deck_z+2.5]) cylinder(h=2.0, r1=1.6, r2=0.4, center=false);
}

module railings_and_lights() {
    for (y=[-deck_width/2, deck_width/2]) {
        color("Silver") rod([-bridge_length/2+4,y,deck_z+4.3], [bridge_length/2-4,y,deck_z+4.3], 0.32);
        color("Silver") for (x=[-88:8:88]) rod([x,y,deck_z+1.9], [x,y,deck_z+4.4], 0.22);
        color("LightYellow") for (x=[-84:21:84]) {
            rod([x,y*0.96,deck_z+1.9], [x,y*0.96,deck_z+7.4], 0.18);
            translate([x,y*0.96,deck_z+7.9]) sphere(r=0.8);
        }
    }
}

module truss_sides() {
    for (y=[-deck_width/2-2.8, deck_width/2+2.8]) {
        color("CadetBlue") rod([-88,y,deck_z+2], [88,y,deck_z+2], 0.55);
        color("CadetBlue") rod([-88,y,deck_z+10], [88,y,deck_z+10], 0.48);
        for (x=[-88:16:72]) {
            color("SkyBlue") rod([x,y,deck_z+2], [x+16,y,deck_z+10], 0.38);
            color("SkyBlue") rod([x+16,y,deck_z+2], [x,y,deck_z+10], 0.38);
            color("LightSteelBlue") rod([x,y,deck_z+2], [x,y,deck_z+10], 0.28);
        }
    }
}

module arches() {
    for (y=[-deck_width/2-5, deck_width/2+5]) {
        for (x=[-78:6:72]) color("DeepSkyBlue")
            rod([x,y,arch_z(x)], [x+6,y,arch_z(x+6)], 0.82);
        for (x=[-72:12:72]) color("LightCyan")
            rod([x,y,deck_z+3], [x,y,arch_z(x)], 0.28);
        for (x=[-72:18:54]) color("PaleTurquoise")
            rod([x,y,arch_z(x)], [x+18,y,deck_z+3], 0.28);
    }
}

module suspension_cables() {
    for (y=[-deck_width/2-8, deck_width/2+8]) {
        for (x=[-82:6:76]) color("White")
            rod([x,y,cable_z(x)], [x+6,y,cable_z(x+6)], 0.44);
        for (x=[-78:12:78]) color("WhiteSmoke")
            rod([x,y,deck_z+4.4], [x,y,cable_z(x)], 0.18);
        color("White") rod([-92,y,deck_z+5], [-60,y,54], 0.5);
        color("White") rod([92,y,deck_z+5], [60,y,54], 0.5);
    }
}

module foundations_and_river() {
    color([0.1,0.35,0.65,0.35]) translate([0,0,-4.5]) rounded_block([220,70,2], 4);
    color("DarkSlateGray") for (x=[-82,-60,60,82], y=[-deck_width/2-5,deck_width/2+5])
        hull() {
            translate([x,y,-5]) cylinder(h=1, r=4.2, center=true);
            translate([x,y,deck_z-2]) cylinder(h=1, r=2.4, center=true);
        }
    color("SandyBrown") for (x=[-105,105]) translate([x,0,-5.7]) rounded_block([28,64,2.5], 5);
}

module civic_plaza() {
    color("BurlyWood") translate([0,0,deck_z+2.05]) cube([22, deck_width-5, 0.45], center=true);
    color("DarkGreen") for (x=[-8,8], y=[-7,7]) translate([x,y,deck_z+3.2]) sphere(r=2.1);
    color("MidnightBlue") translate([0,-0.2,deck_z+3.25]) cube([16,2.2,1.1], center=true);
    color("Gold") translate([-10.5,0,deck_z+4.1]) rotate([90,0,90]) linear_extrude(height=0.7)
        text("HOPE SPAN", size=2.4, halign="center", valign="center", font="Liberation Sans:style=Bold");
    color("White") translate([10.8,0,deck_z+4.1]) rotate([90,0,-90]) linear_extrude(height=0.55)
        text("SCIENCE • CARE", size=1.55, halign="center", valign="center", font="Liberation Sans:style=Bold");
}

foundations_and_river();
bridge_deck();
truss_sides();
arches();
suspension_cables();
tower_group(-60);
tower_group(60);
railings_and_lights();
civic_plaza();
