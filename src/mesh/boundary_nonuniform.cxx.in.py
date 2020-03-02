#!/usr/bin/env python3

from jinja2 import Environment
import stencils_sympy as sten

header="""\
#include <boundary_standard.hxx>
#include <bout/constants.hxx>
#include <boutexception.hxx>
#include <derivs.hxx>
#include <fft.hxx>
#include <globals.hxx>
#include <invert_laplace.hxx>
#include <msg_stack.hxx>
#include <output.hxx>
#include <utils.hxx>

#include "boundary_nonuniform.hxx"

static void update_stagger_offsets(int& x_boundary_offset, int& y_boundary_offset, int& stagger, CELL_LOC loc){
  // NB: bx is going outwards
  // NB: XLOW means shifted in -x direction
  // `stagger` stagger direction with respect to direction of boundary
  //   0 : no stagger or orthogonal to boundary direction
  //   1 : staggerd in direction of boundary
  //  -1 : staggerd in oposite direction of boundary
  // Also note that all offsets are basically half a cell
  if (loc == CELL_XLOW) {
    if (x_boundary_offset == 0) {
      x_boundary_offset = -1;
    } else if (x_boundary_offset < 0) {
      stagger = -1;
    } else {
      stagger = 1;
    }
  }
  if (loc == CELL_YLOW) {
    if (y_boundary_offset == 0) {
      y_boundary_offset = -1;
    } else if (y_boundary_offset < 0) {
      stagger = -1;
    } else {
      stagger = 1;
    }
  }
}
"""

env=Environment(trim_blocks=True);

apply_str="""
void Boundary{{type}}NonUniform_O{{order}}::apply(Field3D &f, BoutReal t) {
  bndry->first();

  // Decide which generator to use
  std::shared_ptr<FieldGenerator> fg = gen;
  if (!fg)
    fg = f.getBndryGenerator(bndry->location);

  BoutReal val = 0.0;

  Mesh *mesh = f.getMesh();
  CELL_LOC loc = f.getLocation();

  BoutReal vals[mesh->LocalNz];
  int x_boundary_offset = bndry->bx;
  int y_boundary_offset = bndry->by;
  int stagger = 0;
  update_stagger_offsets(x_boundary_offset, y_boundary_offset, stagger, loc);
{% if type == "Dirichlet" %}
  int istart = (stagger == -1) ? -1 : 0;
{% endif %}

  for (; !bndry->isDone(); bndry->next1d()) {
    if (fg) {
      for (int zk = 0; zk < mesh->LocalNz; zk++) {
        // Calculate the X and Y normalised values half-way between the guard cell and
        // grid cell
        BoutReal xnorm = 0.5 * (mesh->GlobalX(bndry->x)          // In the guard cell
                                + mesh->GlobalX(bndry->x - x_boundary_offset)); // the grid cell

        BoutReal ynorm = 0.5 * (mesh->GlobalY(bndry->y)          // In the guard cell
                                + mesh->GlobalY(bndry->y - y_boundary_offset)); // the grid cell

        vals[zk] = fg->generate(xnorm, TWOPI * ynorm, TWOPI * zk / (mesh->LocalNz), t);
      }
    }

    vec{{order}} spacing;
    vec{{order}} facs;

    const Field2D &coords_field =
        bndry->by != 0 ? mesh->getCoordinates()->dy : mesh->getCoordinates()->dx;
{% if type != "Free" %}
{% for i in range(1,order) %}
    Indices i{{i}}{bndry->x - {{i}} * bndry->bx, bndry->y - {{i}} * bndry->by, 0};
{% endfor %}
    BoutReal t;
    if (stagger == 0) {
      spacing.f0 = 0;
      BoutReal st=0;
{% for i in range(1,order) %}
      t = coords_field(i{{i}}.x, i{{i}}.y);
      spacing.f{{i}} = st + t / 2;
      st += t;
{% endfor %}
    } else {
      spacing.f0 = 0;
{% for i in range(1,order) %}
      spacing.f{{i}} = spacing.f{{i-1}} + coords_field(i{{i}}.x, i{{i}}.y);
{% endfor %}
    }
{% if type == "Dirichlet" %}
    if (stagger == -1) {
{% for i in range(1,order) %}
      i{{i}} = {bndry->x - {{i+1}} * bndry->bx, bndry->y - {{i+1}} * bndry->by, 0};
{% endfor %}
    }
{% endif %}
{% else %}
{% for i in range(order) %}
    Indices i{{i}}{bndry->x - {{i+1}} * bndry->bx, bndry->y - {{i+1}} * bndry->by, 0};
{% endfor %}
    if (stagger == 0) {
      BoutReal st=0;
{% for i in range(order) %}
      t = coords_field(i{{i}}.x, i{{i}}.y);
      spacing.f{{i}} = st + t / 2;
      st += t;
{% endfor %}
    } else {
      spacing.f0 = 0;
{% for i in range(1,order) %}
      spacing.f{{i}} = spacing.f{{i-1}} + coords_field(i{{i}}.x, i{{i}}.y);
{% endfor %}
    }

{% endif %}
{% if type == "Dirichlet" %}
    for (int i = istart; i < bndry->width; i++) {
{% else %}
    for (int i = 0; i < bndry->width; i++) {
{% endif %}
      Indices ic{bndry->x + i * bndry->bx, bndry->y + i * bndry->by, 0};
      if (stagger == 0) {
        t = coords_field(ic.x, ic.y) / 2;
{% for i in range(order) %}
        spacing.f{{i}} += t;
{% endfor %}
        facs = calc_interp_to_stencil(spacing);
        spacing += t;
      } else {
        t = coords_field(ic.x, ic.y);
        if (stagger == -1
{% if type == "Dirichlet" %}
              && i != -1
{% endif %}
                     ) {
          spacing += t;
        }
        facs = calc_interp_to_stencil(spacing);
        if (stagger == 1) {
          spacing += t;
        }
      }
      for (ic.z = 0; ic.z < mesh->LocalNz; ic.z++) {
{% for i in range(1,order) %}
        i{{i}}.z = ic.z;
{% endfor %}
{% if type != "Free" %}
        val = (fg) ? vals[ic.z] : 0.0;
        t = facs.f0 * val 
{% else %}
        t = facs.f0 * f(i0.x, i0.y, i0.z)
{% endif %}
{% for i in range(1,order) %}
           + facs.f{{i}} *f(i{{i}}.x, i{{i}}.y, i{{i}}.z)
{% endfor %}
        ;
        
        f(ic.x, ic.y, ic.z) = t;
      }
    }
  }
}
"""
clone_str="""
BoundaryOp * {{class}}::clone(BoundaryRegion *region,
   const std::list<std::string> &args) {

  std::shared_ptr<FieldGenerator> newgen;
  if (!args.empty()) {
    // First argument should be an expression
    newgen = FieldFactory::get()->parse(args.front());
  }
  return new {{class}}(region, newgen);
}
"""
stencil_str="""
vec{{order}} {{class}}::calc_interp_to_stencil(const vec{{order}} & spacing) const {
vec{{order}} facs;
// Stencil Code
{{stencil_code}}
return facs;
}
"""

orders=range(2,5)
boundaries=["Dirichlet","Neumann","Free"]

if __name__ == "__main__":
    print(header)

    for order in orders:
        for boundary in boundaries:
            if boundary == "Neumann":
                mat=sten.neumann
            else:
                mat=sten.dirichlet
            try:
                code=sten.gen_code(order,mat)
            except:
                import sys
                print("Order:",order,"boundary:",boundary,file=sys.stderr)
                raise
            args={
                'order':order,
                'type':boundary,
                'class':"Boundary%sNonUniform_O%d"%(boundary,order),
                'stencil_code': code,
            }

            print(env.from_string(apply_str).render(**args))
            print(env.from_string(clone_str).render(**args))
            print(env.from_string(stencil_str).render(**args))