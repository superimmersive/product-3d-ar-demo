"""Generate the demo's generic industrial models as GLB (web, Android) and USDZ (iOS).

Every model is Y-up, in metres, centred on X/Z and resting on y = 0.
"""
import json
import math
import os
import struct
import sys
import tempfile

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models")
SEG = 64

MATERIALS = {
    "accent": {"color": (0.95, 0.66, 0.05), "metallic": 0.1, "roughness": 0.45},
    "paint": {"color": (0.16, 0.2, 0.25), "metallic": 0.2, "roughness": 0.5},
    "steel": {"color": (0.72, 0.73, 0.75), "metallic": 1.0, "roughness": 0.32},
    "chrome": {"color": (0.92, 0.93, 0.95), "metallic": 1.0, "roughness": 0.12},
    "rubber": {"color": (0.07, 0.07, 0.08), "metallic": 0.0, "roughness": 0.85},
}


class Model:
    def __init__(self):
        self.parts = {}

    def add(self, material, positions, normals, indices):
        bucket = self.parts.setdefault(material, [[], [], []])
        base = sum(len(p) for p in bucket[0])
        bucket[0].append(np.asarray(positions, dtype=np.float32))
        bucket[1].append(np.asarray(normals, dtype=np.float32))
        bucket[2].append(np.asarray(indices, dtype=np.uint32) + base)

    def merged(self):
        result = {}
        for name, (p, n, i) in self.parts.items():
            result[name] = (np.concatenate(p), np.concatenate(n), np.concatenate(i))
        return result

    def settle(self):
        """Centre on X/Z and drop onto the floor."""
        allp = np.concatenate([np.concatenate(b[0]) for b in self.parts.values()])
        lo, hi = allp.min(axis=0), allp.max(axis=0)
        shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2], dtype=np.float32)
        for bucket in self.parts.values():
            bucket[0] = [p + shift for p in bucket[0]]


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float32)


AXIS_X = rot_z(-math.pi / 2)
AXIS_Z = rot_x(math.pi / 2)


def place(geom, rot=None, at=(0, 0, 0)):
    p, n, i = geom
    p = np.asarray(p, dtype=np.float32)
    n = np.asarray(n, dtype=np.float32)
    if rot is not None:
        p = p @ rot.T
        n = n @ rot.T
    return p + np.asarray(at, dtype=np.float32), n, i


def lathe(profile, seg=SEG):
    """Revolve (radius, y) points about Y. Each profile segment gets its own hard-edged band."""
    pos, nor, idx = [], [], []
    angles = [2 * math.pi * k / seg for k in range(seg + 1)]
    for (r0, y0), (r1, y1) in zip(profile, profile[1:]):
        dr, dy = r1 - r0, y1 - y0
        length = math.hypot(dr, dy)
        if length < 1e-9:
            continue
        nr, ny = dy / length, -dr / length
        base = len(pos)
        for a in angles:
            c, s = math.cos(a), math.sin(a)
            pos.append((r0 * c, y0, r0 * s))
            pos.append((r1 * c, y1, r1 * s))
            nor.append((nr * c, ny, nr * s))
            nor.append((nr * c, ny, nr * s))
        for k in range(seg):
            a, b = base + 2 * k, base + 2 * k + 1
            c, d = base + 2 * (k + 1), base + 2 * (k + 1) + 1
            idx += [a, b, c, b, d, c]
    return pos, nor, idx


def disc(r, y0, y1, seg=SEG):
    return lathe([(0, y0), (r, y0), (r, y1), (0, y1)], seg)


def ring(ri, ro, y0, y1, seg=SEG):
    return lathe([(ri, y0), (ro, y0), (ro, y1), (ri, y1), (ri, y0)], seg)


def box(sx, sy, sz):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    faces = [
        ((1, 0, 0), [(hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)]),
        ((-1, 0, 0), [(-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz), (-hx, -hy, -hz)]),
        ((0, 1, 0), [(-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz)]),
        ((0, -1, 0), [(-hx, -hy, hz), (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz)]),
        ((0, 0, 1), [(-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]),
        ((0, 0, -1), [(hx, -hy, -hz), (-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz)]),
    ]
    pos, nor, idx = [], [], []
    for normal, corners in faces:
        base = len(pos)
        pos += corners
        nor += [normal] * 4
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nor, idx


def bolt_circle(model, material, count, radius, y0, y1, bolt_r=0.012, rot=None, at=(0, 0, 0), start=0.0):
    for k in range(count):
        a = start + 2 * math.pi * k / count
        offset = np.array([radius * math.cos(a), 0, radius * math.sin(a)], dtype=np.float32)
        geom = place(lathe([(0, y0), (bolt_r, y0), (bolt_r, y1), (0, y1)], 6), at=offset)
        model.add(material, *place(geom, rot, at))


def fix_winding(p, n, i):
    tris = i.reshape(-1, 3).copy()
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    face = np.cross(b - a, c - a)
    avg = n[tris[:, 0]] + n[tris[:, 1]] + n[tris[:, 2]]
    flip = (face * avg).sum(axis=1) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return tris.reshape(-1)


# --- Models -----------------------------------------------------------------


def hydrocyclone():
    m = Model()
    m.add("rubber", *ring(0.035, 0.055, 0.0, 0.1))
    m.add("steel", *ring(0.04, 0.1, 0.1, 0.125))
    m.add("accent", *lathe([(0.055, 0.125), (0.19, 0.86)]))
    m.add("steel", *ring(0.17, 0.25, 0.86, 0.895))
    bolt_circle(m, "steel", 16, 0.225, 0.895, 0.915)
    m.add("accent", *lathe([(0.19, 0.895), (0.19, 1.2)]))
    m.add("steel", *ring(0.17, 0.25, 1.2, 1.235))
    bolt_circle(m, "steel", 16, 0.225, 1.235, 1.255)
    m.add("accent", *lathe([(0.2, 1.235), (0.2, 1.34), (0.09, 1.34)]))
    m.add("steel", *ring(0.06, 0.09, 1.34, 1.52))
    m.add("steel", *ring(0.06, 0.13, 1.52, 1.55))
    bolt_circle(m, "steel", 8, 0.11, 1.55, 1.565)
    inlet = place(box(0.16, 0.14, 0.38), at=(0.11, 1.125, 0.2))
    m.add("accent", *inlet)
    m.add("steel", *place(box(0.22, 0.2, 0.03), at=(0.11, 1.125, 0.39)))
    for dx in (-0.08, 0.08):
        for dy in (-0.07, 0.07):
            m.add("steel", *place(disc(0.011, 0.0, 0.02, 6), AXIS_Z, (0.11 + dx, 1.125 + dy, 0.405)))
    m.settle()
    return m


def slurry_pump():
    m = Model()
    m.add("paint", *place(box(1.1, 0.08, 0.5), at=(0, 0.04, 0)))
    m.add("paint", *place(box(0.4, 0.26, 0.26), at=(-0.18, 0.21, 0)))
    m.add("paint", *place(lathe([(0.12, -0.25), (0.12, 0.25)]), AXIS_X, (-0.18, 0.42, 0)))
    m.add("steel", *place(disc(0.035, -0.5, -0.25), AXIS_X, (-0.18, 0.42, 0)))
    m.add("rubber", *place(disc(0.08, -0.56, -0.5), AXIS_X, (-0.18, 0.42, 0)))
    casing_x = 0.3
    m.add("paint", *place(box(0.2, 0.12, 0.36), at=(casing_x, 0.14, 0)))
    m.add("accent", *place(lathe([(0.12, -0.13), (0.3, -0.1), (0.34, 0.0), (0.3, 0.1), (0.12, 0.13)]), AXIS_X, (casing_x, 0.48, 0)))
    m.add("accent", *place(disc(0.12, -0.13, 0.13), AXIS_X, (casing_x, 0.48, 0)))
    bolt_circle(m, "steel", 16, 0.32, -0.015, 0.015, 0.016, AXIS_X, (casing_x, 0.48, 0))
    m.add("accent", *place(lathe([(0.1, 0.13), (0.1, 0.3)]), AXIS_X, (casing_x, 0.48, 0)))
    m.add("steel", *place(ring(0.08, 0.17, 0.3, 0.34), AXIS_X, (casing_x, 0.48, 0)))
    bolt_circle(m, "steel", 8, 0.145, 0.34, 0.355, 0.011, AXIS_X, (casing_x, 0.48, 0))
    m.add("accent", *place(lathe([(0.085, 0.0), (0.085, 0.2)]), at=(casing_x, 0.73, 0.2)))
    m.add("steel", *place(ring(0.065, 0.15, 0.2, 0.235), at=(casing_x, 0.73, 0.2)))
    bolt_circle(m, "steel", 8, 0.125, 0.235, 0.25, 0.011, at=(casing_x, 0.73, 0.2))
    m.add("accent", *place(box(0.18, 0.2, 0.24), at=(casing_x, 0.72, 0.1)))
    m.settle()
    return m


def hydraulic_cylinder():
    m = Model()
    m.add("paint", *lathe([(0.075, 0.0), (0.075, 0.72)]))
    m.add("steel", *disc(0.09, -0.06, 0.0))
    m.add("steel", *disc(0.09, 0.72, 0.8))
    m.add("chrome", *disc(0.035, 0.8, 1.22))
    m.add("steel", *disc(0.05, 1.22, 1.27))
    for y, sign in ((-0.06, -1), (1.27, 1)):
        m.add("steel", *place(box(0.08, 0.1, 0.08), at=(0, y + sign * 0.05, 0)))
        m.add("steel", *place(ring(0.025, 0.055, -0.04, 0.04), AXIS_Z, (0, y + sign * 0.12, 0)))
    for y in (0.08, 0.64):
        m.add("steel", *place(disc(0.018, 0.0, 0.05, 12), rot_z(math.pi / 2), (-0.065, y, 0)))
    model = Model()
    for name, (p, n, i) in m.merged().items():
        model.add(name, *place((p, n, i), AXIS_X))
    model.settle()
    return model


def idler_roller():
    m = Model()
    m.add("rubber", *ring(0.06, 0.068, 0.0, 0.6))
    m.add("steel", *ring(0.02, 0.06, 0.0, 0.012))
    m.add("steel", *ring(0.02, 0.06, 0.588, 0.6))
    m.add("steel", *disc(0.02, -0.06, 0.66))
    for y in (-0.06, 0.62):
        m.add("steel", *place(box(0.045, 0.04, 0.02), at=(0, y + 0.02, 0)))
    model = Model()
    for name, (p, n, i) in m.merged().items():
        model.add(name, *place((p, n, i), AXIS_X))
    model.settle()
    return model


def wear_liner():
    m = Model()
    m.add("rubber", *place(box(0.62, 0.05, 0.32), at=(0, 0.025, 0)))
    m.add("steel", *place(box(0.62, 0.025, 0.12), at=(0, 0.0625, 0)))
    m.add("rubber", *place(box(0.62, 0.09, 0.1), at=(0, 0.12, 0)))
    for x in (-0.2, 0.2):
        m.add("steel", *place(disc(0.03, 0.165, 0.185, 6), at=(x, 0, 0)))
    m.settle()
    return m


MODELS = {
    "hydrocyclone": hydrocyclone,
    "slurry-pump": slurry_pump,
    "hydraulic-cylinder": hydraulic_cylinder,
    "idler-roller": idler_roller,
    "wear-liner": wear_liner,
}

AR_MODELS = {"hydrocyclone", "slurry-pump"}


# --- Writers ----------------------------------------------------------------


def write_glb(model, path):
    parts = model.merged()
    buffer = bytearray()
    views, accessors, primitives, materials = [], [], [], []

    def add_view(data, target):
        while len(buffer) % 4:
            buffer.append(0)
        views.append({"buffer": 0, "byteOffset": len(buffer), "byteLength": len(data), "target": target})
        buffer.extend(data)
        return len(views) - 1

    for mat_index, (name, (p, n, i)) in enumerate(parts.items()):
        tris = fix_winding(p, n, i)
        pv = add_view(p.astype("<f4").tobytes(), 34962)
        nv = add_view(n.astype("<f4").tobytes(), 34962)
        iv = add_view(tris.astype("<u4").tobytes(), 34963)
        accessors += [
            {"bufferView": pv, "componentType": 5126, "count": len(p), "type": "VEC3",
             "min": p.min(axis=0).tolist(), "max": p.max(axis=0).tolist()},
            {"bufferView": nv, "componentType": 5126, "count": len(n), "type": "VEC3"},
            {"bufferView": iv, "componentType": 5125, "count": len(tris), "type": "SCALAR"},
        ]
        base = len(accessors) - 3
        primitives.append({"attributes": {"POSITION": base, "NORMAL": base + 1}, "indices": base + 2, "material": mat_index})
        spec = MATERIALS[name]
        materials.append({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [*spec["color"], 1.0],
                "metallicFactor": spec["metallic"],
                "roughnessFactor": spec["roughness"],
            },
        })
    while len(buffer) % 4:
        buffer.append(0)

    gltf = {
        "asset": {"version": "2.0", "generator": "Superimmersive demo model"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": os.path.splitext(os.path.basename(path))[0], "mesh": 0}],
        "meshes": [{"primitives": primitives}],
        "materials": materials,
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buffer)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A))
        f.write(js)
        f.write(struct.pack("<II", len(buffer), 0x004E4942))
        f.write(bytes(buffer))


def write_usdz(model, path, name):
    work = tempfile.mkdtemp()
    layer = os.path.join(work, name + ".usdc")
    stage = Usd.Stage.CreateNew(layer)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/root")
    stage.SetDefaultPrim(root.GetPrim())

    for mat_name, (p, n, i) in model.merged().items():
        tris = fix_winding(p, n, i)
        mesh = UsdGeom.Mesh.Define(stage, "/root/" + mat_name)
        mesh.CreatePointsAttr([Gf.Vec3f(*map(float, v)) for v in p])
        mesh.CreateNormalsAttr([Gf.Vec3f(*map(float, v)) for v in n])
        mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
        mesh.CreateFaceVertexCountsAttr([3] * (len(tris) // 3))
        mesh.CreateFaceVertexIndicesAttr([int(v) for v in tris])
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        lo, hi = p.min(axis=0), p.max(axis=0)
        mesh.CreateExtentAttr([Gf.Vec3f(*map(float, lo)), Gf.Vec3f(*map(float, hi))])

        spec = MATERIALS[mat_name]
        material = UsdShade.Material.Define(stage, "/root/Materials/" + mat_name)
        shader = UsdShade.Shader.Define(stage, "/root/Materials/" + mat_name + "/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*spec["color"]))
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(spec["metallic"])
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(spec["roughness"])
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)

    stage.GetRootLayer().Save()
    if os.path.exists(path):
        os.remove(path)
    if not UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(layer), path):
        raise RuntimeError("USDZ packaging failed for " + name)


def main():
    os.makedirs(OUT, exist_ok=True)
    only = set(sys.argv[1:])
    for name, build in MODELS.items():
        if only and name not in only:
            continue
        model = build()
        glb = os.path.join(OUT, name + ".glb")
        write_glb(model, glb)
        line = f"{name}: glb {os.path.getsize(glb) // 1024} KB"
        if name in AR_MODELS:
            usdz = os.path.join(OUT, name + ".usdz")
            write_usdz(model, usdz, name.replace("-", "_"))
            line += f", usdz {os.path.getsize(usdz) // 1024} KB"
        allp = np.concatenate([b[0] for b in model.merged().values()])
        size = allp.max(axis=0) - allp.min(axis=0)
        tris = sum(len(b[2]) for b in model.merged().values()) // 3
        print(line + f", {tris} tris, size {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} m")


if __name__ == "__main__":
    main()
