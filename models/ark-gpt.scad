/*
  CALTRANS-INSPIRED STANDARD BRIDGE MODEL
  OpenSCAD decorative concept model

  Inspired by:
  - Caltrans Bridge Standard Details page
  - PC/Pretensioned Bulb-Tee Girder details
  - Slope Paving / Full Slope / No Skew details

  NOT FOR ENGINEERING, FABRICATION, LOAD RATING, OR CONSTRUCTION.
*/

$fn = 48;

// -------------------------
// GLOBAL SCALE / PARAMETERS
// -------------------------

bridge_len = 92;
deck_width = 24;
deck_thick = 1.1;
deck_z = 13;

girder_count = 5;
girder_spacing = 4.5;
girder_len = 84;
girder_height = 5.2;
girder_z = deck_z - girder_height;

road_width = 18;
barrier_height = 1.8;

pier_count = 3;
column_height = 8.4;
column_radius = 0.75;

base_len = 128;
base_width = 52;
base_thick = 0.55;

// -------------------------
// COLORS
// -------------------------

concrete = [0.72, 0.72, 0.68];
fresh_concrete = [0.82, 0.82, 0.78];
shadow_concrete = [0.55, 0.55, 0.52];
asphalt = [0.08, 0.085, 0.09];
stripe_white = [1, 1, 0.92];
stripe_yellow = [1, 0.78, 0.05];
steel = [0.35, 0.37, 0.39];
dark_joint = [0.02, 0.02, 0.02];
soil = [0.45, 0.34, 0.23];
grass = [0.22, 0.46, 0.22];
water_blue = [0.16, 0.40, 0.65, 0.55];

// -------------------------
// HELPERS
// -------------------------

module centered_box(size, loc=[0,0,0]) {
    translate([loc[0] - size[0]/2, loc[1] - size[1]/2, loc[2]])
        cube(size);
}

module x_cylinder(len, r, loc=[0,0,0]) {
    translate(loc)
        rotate([0,90,0])
            cylinder(h=len, r=r, center=true);
}

module z_cylinder(h, r, loc=[0,0,0]) {
    translate(loc)
        cylinder(h=h, r=r, center=false);
}

module trapezoid_prism_x(len, base_w, top_w, h, loc=[0,0,0]) {
    x0 = -len/2;
    x1 = len/2;
    y0b = -base_w/2;
    y1b = base_w/2;
    y0t = -top_w/2;
    y1t = top_w/2;
    z0 = 0;
    z1 = h;

    translate(loc)
        polyhedron(
            points=[
                [x0,y0b,z0], [x0,y1b,z0], [x0,y1t,z1], [x0,y0t,z1],
                [x1,y0b,z0], [x1,y1b,z0], [x1,y1t,z1], [x1,y0t,z1]
            ],
            faces=[
                [0,1,2,3],
                [4,7,6,5],
                [0,4,5,1],
                [1,5,6,2],
                [2,6,7,3],
                [3,7,4,0]
            ]
        );
}

module sloped_slab(x0, x1, z0, z1, width, thick=0.25) {
    polyhedron(
        points=[
            [x0,-width/2,z0], [x0,width/2,z0], [x1,width/2,z1], [x1,-width/2,z1],
            [x0,-width/2,z0-thick], [x0,width/2,z0-thick], [x1,width/2,z1-thick], [x1,-width/2,z1-thick]
        ],
        faces=[
            [0,1,2,3],
            [4,7,6,5],
            [0,4,5,1],
            [1,5,6,2],
            [2,6,7,3],
            [3,7,4,0]
        ]
    );
}

function lerp(a,b,t) = a + (b-a)*t;

// -------------------------
// CIVIL / BRIDGE COMPONENTS
// -------------------------

module bulb_tee_girder(len=girder_len) {
    color(concrete)
    union() {
        // Top flange
        centered_box([len, 2.95, 0.55], [0,0,4.65]);

        // Web
        centered_box([len, 0.62, 3.65], [0,0,1.25]);

        // Bottom foot
        centered_box([len, 1.85, 0.52], [0,0,0.10]);

        // Rounded lower bulb mass
        translate([0,0,0.82])
            scale([1,1.45,0.62])
                rotate([0,90,0])
                    cylinder(h=len, r=0.72, center=true);

        // End diaphragm thickened blocks
        for (x=[-len/2 + 4.0, len/2 - 4.0]) {
            centered_box([1.4, 2.7, 4.2], [x,0,0.45]);
        }

        // Subtle strand lines along side
        color(shadow_concrete)
        for (zline=[1.25,1.75,2.25,2.75,3.25]) {
            translate([0,-0.335,zline])
                rotate([0,90,0])
                    cylinder(h=len+0.05, r=0.035, center=true);
            translate([0,0.335,zline])
                rotate([0,90,0])
                    cylinder(h=len+0.05, r=0.035, center=true);
        }
    }
}

module deck_slab() {
    color(fresh_concrete)
        centered_box([bridge_len, deck_width, deck_thick], [0,0,deck_z]);

    // Slight overhang shadow line
    color(shadow_concrete)
    for (y=[-deck_width/2, deck_width/2]) {
        centered_box([bridge_len, 0.20, 0.22], [0,y,deck_z-0.22]);
    }
}

module asphalt_roadway() {
    color(asphalt)
        centered_box([bridge_len-3, road_width, 0.08], [0,0,deck_z+deck_thick+0.02]);

    // Lane center broken yellow stripes
    color(stripe_yellow)
    for (x=[-36:12:36]) {
        centered_box([5.2, 0.16, 0.04], [x,0,deck_z+deck_thick+0.09]);
    }

    // White shoulder lines
    color(stripe_white)
    for (y=[-road_width/2+1.2, road_width/2-1.2]) {
        centered_box([bridge_len-6, 0.13, 0.04], [0,y,deck_z+deck_thick+0.10]);
    }

    // Expansion joints near abutments
    color(dark_joint)
    for (x=[-bridge_len/2+6, bridge_len/2-6]) {
        centered_box([0.22, road_width+1.2, 0.06], [x,0,deck_z+deck_thick+0.12]);
    }
}

module concrete_barriers() {
    for (y=[-deck_width/2+0.9, deck_width/2-0.9]) {
        color(concrete)
            trapezoid_prism_x(
                bridge_len-2,
                1.20,
                0.58,
                barrier_height,
                [0,y,deck_z+deck_thick]
            );

        // top rail / coping
        color(fresh_concrete)
            centered_box([bridge_len-2, 0.72, 0.18], [0,y,deck_z+deck_thick+barrier_height]);
    }
}

module girder_system() {
    first_y = -((girder_count-1) * girder_spacing)/2;

    for (i=[0:girder_count-1]) {
        y = first_y + i*girder_spacing;
        translate([0,y,girder_z])
            bulb_tee_girder(girder_len);
    }

    // Intermediate diaphragms between girders
    color(concrete)
    for (x=[-24,0,24]) {
        centered_box([0.8, deck_width-4.0, 2.8], [x,0,girder_z+1.0]);
    }
}

module abutment(xpos, side=1) {
    color(concrete) {
        // Main abutment wall
        centered_box([3.0, deck_width+7, 7.0], [xpos,0,5.4]);

        // Bearing seat cap
        centered_box([5.2, deck_width+8.5, 1.0], [xpos,0,12.0]);

        // Backwall rising behind deck
        centered_box([1.2, deck_width+7.5, 2.4], [xpos + side*1.8,0,12.0]);
    }

    // Bearing pads
    first_y = -((girder_count-1) * girder_spacing)/2;
    color(dark_joint)
    for (i=[0:girder_count-1]) {
        y = first_y + i*girder_spacing;
        centered_box([1.2, 1.45, 0.18], [xpos - side*1.05, y, 12.05]);
    }

    // Angled wingwalls
    for (y=[-(deck_width/2+3.5), deck_width/2+3.5]) {
        translate([xpos + side*4.5, y, 5.2])
            rotate([0,0, side * (y > 0 ? -18 : 18)])
                color(concrete)
                    centered_box([12, 0.85, 6.2], [0,0,0]);
    }
}

module pier_bent(xpos=0) {
    color(concrete) {
        // Pier cap
        centered_box([4.2, deck_width-2, 1.2], [xpos,0,11.0]);

        // Columns
        for (y=[-7.0,0,7.0]) {
            z_cylinder(column_height, column_radius, [xpos,y,2.6]);
        }

        // Footings
        for (y=[-7.0,0,7.0]) {
            centered_box([4.2, 3.3, 0.8], [xpos,y,1.85]);
        }
    }

    // bearing pads on cap
    first_y = -((girder_count-1) * girder_spacing)/2;
    color(dark_joint)
    for (i=[0:girder_count-1]) {
        y = first_y + i*girder_spacing;
        centered_box([1.4, 1.45, 0.16], [xpos, y, 12.18]);
    }
}

module slope_paving(side=1) {
    // side = -1 for left end, +1 for right end
    x_abut = side*(bridge_len/2 + 1.6);
    x_far = side*(bridge_len/2 + 24);
    z_top = 8.0;
    z_low = 0.72;
    paving_width = deck_width + 18;

    color([0.68,0.68,0.63])
        sloped_slab(x_far, x_abut, z_low, z_top, paving_width, 0.30);

    // Panel groove lines down slope
    color([0.40,0.40,0.38])
    for (t=[0.18:0.16:0.90]) {
        x = lerp(x_far, x_abut, t);
        z = lerp(z_low, z_top, t) + 0.04;
        centered_box([0.18, paving_width+0.15, 0.06], [x,0,z]);
    }

    // Longitudinal groove lines
    color([0.40,0.40,0.38])
    for (y=[-paving_width/2+6:6:paving_width/2-6]) {
        hull() {
            translate([x_far,y,z_low+0.08])
                sphere(r=0.08);
            translate([x_abut,y,z_top+0.08])
                sphere(r=0.08);
        }
    }

    // Rolled edge curbs along slope paving
    color(concrete)
    for (y=[-paving_width/2, paving_width/2]) {
        hull() {
            translate([x_far,y,z_low+0.22])
                sphere(r=0.22);
            translate([x_abut,y,z_top+0.22])
                sphere(r=0.22);
        }
    }

    // Down drain pipe on one side
    color(steel)
    hull() {
        translate([x_far, paving_width/2-3.2, z_low+0.35])
            sphere(r=0.22);
        translate([x_abut, paving_width/2-3.2, z_top+0.35])
            sphere(r=0.22);
    }
}

module ground_and_site() {
    // Base
    color(grass)
        centered_box([base_len, base_width, base_thick], [0,0,0]);

    // Creek / channel under bridge
    color(water_blue)
        centered_box([base_len*0.82, 10, 0.08], [0,0,base_thick+0.03]);

    // Earth berms
    color(soil)
    for (side=[-1,1]) {
        centered_box([24, base_width, 1.2], [side*(bridge_len/2+22),0,base_thick]);
    }
}

module guardrail_posts() {
    color(steel)
    for (y=[-deck_width/2+1.65, deck_width/2-1.65]) {
        for (x=[-39:6:39]) {
            centered_box([0.20,0.20,1.15], [x,y,deck_z+deck_thick+barrier_height+0.08]);
        }

        // Simple steel rail above concrete barrier
        centered_box([bridge_len-6, 0.16, 0.16], [0,y,deck_z+deck_thick+barrier_height+1.05]);
    }
}

module caltrans_plan_label() {
    color([0.05,0.05,0.05])
    translate([-50,-24,0.62])
        linear_extrude(height=0.05)
            text(
                "CALTRANS-INSPIRED PC/PRETENSIONED BULB-TEE GIRDER BRIDGE",
                size=1.25,
                font="Liberation Sans:style=Bold"
            );

    color([0.05,0.05,0.05])
    translate([-50,-26.2,0.62])
        linear_extrude(height=0.05)
            text(
                "Decorative OpenSCAD concept - not for engineering or construction",
                size=0.85,
                font="Liberation Sans"
            );
}

// -------------------------
// ASSEMBLY
// -------------------------

module caltrans_standard_bridge() {
    ground_and_site();

    slope_paving(-1);
    slope_paving(1);

    abutment(-bridge_len/2+2.5, -1);
    abutment(bridge_len/2-2.5, 1);

    pier_bent(-22);
    pier_bent(22);

    girder_system();

    deck_slab();
    asphalt_roadway();
    concrete_barriers();
    guardrail_posts();

    caltrans_plan_label();
}

caltrans_standard_bridge();