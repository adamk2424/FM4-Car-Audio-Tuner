"""
FM4 Car Audio Tuner
Forza Motorsport 4 Engine Tuning XML Editor
"""

import json
import os
import re
import struct
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import xml.etree.ElementTree as ET

# --- Paths (relative to script/exe location) ---
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ET_DIR = os.path.join(BASE_DIR, "enginetuning_extracted")
HT_DIR = os.path.join(BASE_DIR, "harmonictuning_extracted")
QUICKBMS_EXE = os.path.join(BASE_DIR, "quickbms", "quickbms.exe")
ZIP_BMS = os.path.join(BASE_DIR, "zip.bms")
BACKUP_ZIP = os.path.join(BASE_DIR, "enginetuning_backup.zip")
OUTPUT_ZIP = os.path.join(BASE_DIR, "enginetuning.zip")
DLC_ET_DIR = os.path.join(BASE_DIR, "dlc_enginetuning")
DLC_HT_DIR = os.path.join(BASE_DIR, "dlc_harmonictuning")
FILE_MAPPING_PATH = os.path.join(BASE_DIR, "file_mapping.json")
DEFAULT_SCAN_ROOT = r"C:\Emulators"

CYLINDER_GROUPS = {
    "2": ["2", "4", "8", "16"], "4": ["2", "4", "8", "16"],
    "8": ["2", "4", "8", "16"], "16": ["2", "4", "8", "16"],
    "3": ["3", "6", "12"], "6": ["3", "6", "12"], "12": ["3", "6", "12"],
    "5": ["5", "10"], "10": ["5", "10"],
    "Rotary": ["2R"],
}
CYLINDER_OPTIONS = ["4", "5", "6", "8", "10", "12", "Rotary"]


# ============================================================
# Reusable Widgets
# ============================================================

class PhysCoefEditor(ttk.Frame):
    """4 sliders for RPM, Throttle, PosTorque, NegTorque constrained to sum <= 1.0."""
    LABELS = ["RPM", "Thr", "Pos", "Neg"]

    def __init__(self, parent, on_change=None, **kw):
        super().__init__(parent, **kw)
        self._vars = []
        self._scales = []
        self._entries = []
        self._updating = False
        self._on_change = on_change

        for i, label in enumerate(self.LABELS):
            ttk.Label(self, text=label, width=4, font=("Segoe UI", 8)).grid(row=i, column=0, sticky="w")
            var = tk.DoubleVar(value=0.0)
            self._vars.append(var)
            s = ttk.Scale(self, from_=0.0, to=1.0, orient=tk.HORIZONTAL, length=100,
                          variable=var, command=lambda val, idx=i: self._on_slider(idx))
            s.grid(row=i, column=1, padx=2)
            self._scales.append(s)
            e = ttk.Entry(self, width=5, font=("Segoe UI", 8))
            e.grid(row=i, column=2, padx=(0, 2))
            e.bind("<Return>", lambda ev, idx=i: self._on_entry(idx))
            e.bind("<FocusOut>", lambda ev, idx=i: self._on_entry(idx))
            self._entries.append(e)

    def _on_slider(self, changed_idx):
        if self._updating:
            return
        self._updating = True
        vals = [v.get() for v in self._vars]
        total = sum(vals)
        if total > 1.0:
            excess = total - 1.0
            others_sum = sum(vals[i] for i in range(4) if i != changed_idx)
            if others_sum > 0:
                for i in range(4):
                    if i != changed_idx:
                        self._vars[i].set(max(0, vals[i] - excess * (vals[i] / others_sum)))
            else:
                self._vars[changed_idx].set(1.0)
        self._sync_entries()
        self._updating = False
        if self._on_change:
            self._on_change()

    def is_all_zero(self):
        return all(v.get() < 0.0001 for v in self._vars)

    def _on_entry(self, idx):
        try:
            val = float(self._entries[idx].get())
            val = max(0.0, min(1.0, val))
            self._vars[idx].set(val)
            self._on_slider(idx)
        except ValueError:
            pass

    def _sync_entries(self):
        for i, e in enumerate(self._entries):
            e.delete(0, tk.END)
            e.insert(0, f"{self._vars[i].get():.3f}")

    def set_values(self, rpm, throttle, pos, neg):
        self._updating = True
        for var, val in zip(self._vars, [rpm, throttle, pos, neg]):
            var.set(float(val))
        self._sync_entries()
        self._updating = False

    def get_values(self):
        return {
            "RPM": f"{self._vars[0].get():.6f}",
            "Throttle": f"{self._vars[1].get():.6f}",
            "PosTorque": f"{self._vars[2].get():.6f}",
            "NegTorque": f"{self._vars[3].get():.6f}",
        }


class CurveEditor(ttk.Frame):
    """Canvas with 3 draggable points + entry fields for a ThreePointCurve."""
    W, H = 220, 130
    PAD = 20
    POINT_R = 5
    COLORS = ["#e74c3c", "#2ecc71", "#3498db"]

    def __init__(self, parent, y_limit=None, **kw):
        super().__init__(parent, **kw)
        self._points = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
        self._y_max = 1.0
        self._y_limit = y_limit
        self._dragging = None
        self._flat_mode = False

        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg="#1e1e1e",
                                highlightthickness=1, highlightbackground="#555")
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Entry fields
        ef = ttk.Frame(self)
        ef.pack(fill=tk.X, pady=(2, 0))
        self._entries = []
        for i, (lbl, col) in enumerate([
            ("x0", 0), ("y0", 1), ("x1", 2), ("y1", 3), ("x2", 4), ("y2", 5)
        ]):
            ttk.Label(ef, text=lbl, font=("Segoe UI", 8), foreground=self.COLORS[i // 2]).grid(row=0, column=col * 2)
            e = ttk.Entry(ef, width=6, font=("Segoe UI", 8))
            e.grid(row=0, column=col * 2 + 1, padx=1)
            e.bind("<Return>", lambda ev: self._on_entries_changed())
            e.bind("<FocusOut>", lambda ev: self._on_entries_changed())
            self._entries.append(e)

    def set_flat_mode(self, flat):
        self._flat_mode = flat
        self._redraw()

    def _val_to_canvas(self, x, y):
        cx = self.PAD + x * (self.W - 2 * self.PAD)
        cy = (self.H - self.PAD) - (y / self._y_max * (self.H - 2 * self.PAD)) if self._y_max > 0 else self.H - self.PAD
        return cx, cy

    def _canvas_to_val(self, cx, cy):
        x = (cx - self.PAD) / (self.W - 2 * self.PAD)
        y = (self.H - self.PAD - cy) / (self.H - 2 * self.PAD) * self._y_max if self._y_max > 0 else 0
        return max(0, x), max(0, y)

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        # Grid
        for i in range(5):
            frac = i / 4
            x = self.PAD + frac * (self.W - 2 * self.PAD)
            y = (self.H - self.PAD) - frac * (self.H - 2 * self.PAD)
            c.create_line(x, self.PAD, x, self.H - self.PAD, fill="#333", dash=(2, 2))
            c.create_line(self.PAD, y, self.W - self.PAD, y, fill="#333", dash=(2, 2))
        # Axes
        c.create_line(self.PAD, self.H - self.PAD, self.W - self.PAD, self.H - self.PAD, fill="#666")
        c.create_line(self.PAD, self.PAD, self.PAD, self.H - self.PAD, fill="#666")
        # Y max label
        c.create_text(self.PAD - 2, self.PAD, text=f"{self._y_max:.0f}", anchor="e",
                       fill="#888", font=("Segoe UI", 6))
        c.create_text(self.PAD - 2, self.H - self.PAD, text="0", anchor="e",
                       fill="#888", font=("Segoe UI", 6))
        # Lines and Points
        coords = [self._val_to_canvas(p[0], p[1]) for p in self._points]
        if self._flat_mode:
            # Flat value - draw horizontal dashed line at y0 across full width
            _, cy0 = coords[0]
            c.create_line(self.PAD, cy0, self.W - self.PAD, cy0, fill="#aaa", width=1, dash=(4, 4))
            r = self.POINT_R
            cx0, _ = coords[0]
            c.create_oval(cx0 - r, cy0 - r, cx0 + r, cy0 + r, fill=self.COLORS[0],
                          outline="white", width=1, tags="pt0")
        else:
            for i in range(len(coords) - 1):
                c.create_line(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1],
                              fill="#aaa", width=2)
            for i, (cx, cy) in enumerate(coords):
                r = self.POINT_R
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=self.COLORS[i],
                              outline="white", width=1, tags=f"pt{i}")

    def _on_press(self, event):
        for i, pt in enumerate(self._points):
            if self._flat_mode and i > 0:
                continue
            cx, cy = self._val_to_canvas(pt[0], pt[1])
            if abs(event.x - cx) < 10 and abs(event.y - cy) < 10:
                self._dragging = i
                return

    def _on_drag(self, event):
        if self._dragging is None:
            return
        x, y = self._canvas_to_val(event.x, event.y)
        x = max(0, min(1.0, x))
        y = max(0, y)
        if self._y_limit is not None:
            y = min(y, self._y_limit)
        # Allow Y to exceed current max - rescale
        if y > self._y_max:
            self._y_max = y * 1.2
        self._points[self._dragging] = (x, y)
        self._redraw()
        self._sync_entries()

    def _on_release(self, event):
        self._dragging = None

    def _sync_entries(self):
        vals = []
        for p in self._points:
            vals.extend(p)
        for i, e in enumerate(self._entries):
            e.delete(0, tk.END)
            e.insert(0, f"{vals[i]:.6f}")

    def _on_entries_changed(self):
        try:
            vals = [float(e.get()) for e in self._entries]
            if self._y_limit is not None:
                for i in (1, 3, 5):  # y0, y1, y2
                    vals[i] = min(vals[i], self._y_limit)
            self._points = [(vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])]
            max_y = max(v for i, v in enumerate(vals) if i % 2 == 1)
            self._y_max = max(1.0, max_y * 1.2) if max_y > 0 else 1.0
            self._redraw()
            self._sync_entries()
        except ValueError:
            pass

    def set_values(self, x0, y0, x1, y1, x2, y2):
        self._points = [(float(x0), float(y0)), (float(x1), float(y1)), (float(x2), float(y2))]
        max_y = max(float(y0), float(y1), float(y2))
        self._y_max = max(1.0, max_y * 1.2) if max_y > 0 else 1.0
        self._redraw()
        self._sync_entries()

    def get_values(self):
        return {
            "x0": f"{self._points[0][0]:.6f}", "y0": f"{self._points[0][1]:.6f}",
            "x1": f"{self._points[1][0]:.6f}", "y1": f"{self._points[1][1]:.6f}",
            "x2": f"{self._points[2][0]:.6f}", "y2": f"{self._points[2][1]:.6f}",
        }


PARAM_Y_LIMITS = {
    "Gain": 2.0,
    "CenterFrequency": 18000.0,
    "CutoffFrequency": 18000.0,
}


class ParamBlock(ttk.LabelFrame):
    """A labeled block with PhysCoefEditor + CurveEditor for one XML parameter."""

    def __init__(self, parent, title="Parameter", **kw):
        super().__init__(parent, text=title, padding=4, **kw)
        self.physcoef = PhysCoefEditor(self, on_change=self._update_flat_mode)
        self.physcoef.pack(side=tk.LEFT, padx=(0, 8))
        self.curve = CurveEditor(self, y_limit=PARAM_Y_LIMITS.get(title))
        self.curve.pack(side=tk.LEFT)

    def _update_flat_mode(self):
        self.curve.set_flat_mode(self.physcoef.is_all_zero())

    def load_from_xml(self, element):
        """Load from an XML element that has PhysicsCoeff and ThreePointCurve children."""
        if element is None:
            return
        pc = element.find("PhysicsCoeff")
        if pc is not None:
            self.physcoef.set_values(
                pc.get("RPM", "0"), pc.get("Throttle", "0"),
                pc.get("PosTorque", "0"), pc.get("NegTorque", "0"))
        tc = element.find("ThreePointCurve")
        if tc is not None:
            self.curve.set_values(
                tc.get("x0", "0"), tc.get("y0", "0"),
                tc.get("x1", "0.5"), tc.get("y1", "0.5"),
                tc.get("x2", "1"), tc.get("y2", "1"))
        self._update_flat_mode()

    def save_to_xml(self, element):
        """Write values back to an XML element's PhysicsCoeff and ThreePointCurve."""
        if element is None:
            return
        pc = element.find("PhysicsCoeff")
        if pc is not None:
            for k, v in self.physcoef.get_values().items():
                pc.set(k, v)
        tc = element.find("ThreePointCurve")
        if tc is not None:
            for k, v in self.curve.get_values().items():
                tc.set(k, v)


class ScrollableFrame(ttk.Frame):
    """A frame inside a canvas with scrollbar for long content."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interior = ttk.Frame(self.canvas)

        self.interior.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        # Mouse wheel scrolling
        self.interior.bind("<Enter>", self._bind_mousewheel)
        self.interior.bind("<Leave>", self._unbind_mousewheel)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ============================================================
# HT file parsing (unchanged)
# ============================================================

def parse_ht_filename(filename):
    if filename.endswith("_HT.xml.xml"):
        base = filename[:-len("_HT.xml.xml")]
    elif filename.endswith("_HT.xml"):
        base = filename[:-len("_HT.xml")]
    else:
        return None
    if "EngAmb" in base:
        comp_type = "Engine"
        idx = base.index("EngAmb")
        base_no_comp = base[:idx].rstrip("_")
    elif "_Int" in base:
        comp_type = "Intake"
        base_no_comp = base.rsplit("_Int", 1)[0]
    elif "_Exh" in base:
        comp_type = "Exhaust"
        base_no_comp = base.rsplit("_Exh", 1)[0]
    else:
        return None
    m = re.match(r'^(\d+R?[A-Z]{1,2}\d?)', base_no_comp)
    if m:
        prefix = m.group(1)
        name_part = base_no_comp[len(prefix):].lstrip("_")
    elif base_no_comp == "NA":
        prefix = "NA"
        name_part = "NA"
    else:
        return None
    rm = re.match(r'^(\d+)(R?)([A-Z]{1,2})(\d?)', prefix)
    if rm:
        cyl_key = "2R" if rm.group(2) == "R" else rm.group(1)
    elif prefix == "NA":
        cyl_key = "NA"
    else:
        cyl_key = None
    display = f"{prefix} {name_part}" if name_part else prefix
    return (prefix, display, comp_type, cyl_key, filename)


def load_ht_files():
    engine_files, intake_files, exhaust_files = [], [], []
    seen = set()
    for d in [HT_DIR, DLC_HT_DIR]:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn in seen:
                continue
            seen.add(fn)
            parsed = parse_ht_filename(fn)
            if not parsed:
                continue
            prefix, display, comp_type, cyl_key, filename = parsed
            entry = {"filename": filename, "display": display, "cyl_key": cyl_key}
            if comp_type == "Engine":
                engine_files.append(entry)
            elif comp_type == "Intake":
                intake_files.append(entry)
            elif comp_type == "Exhaust":
                exhaust_files.append(entry)
    return engine_files, intake_files, exhaust_files


def load_car_list():
    files = set()
    for d in [ET_DIR, DLC_ET_DIR]:
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith("_ET.xml"):
                    files.add(f)
    return sorted(files)


def resolve_et_path(car_file):
    """Return the full path to an ET XML, checking ET_DIR first then DLC_ET_DIR."""
    p = os.path.join(ET_DIR, car_file)
    if os.path.isfile(p):
        return p
    p = os.path.join(DLC_ET_DIR, car_file)
    if os.path.isfile(p):
        return p
    return None


def ht_display_name(filename):
    if not filename or filename in ("NA.xml", ""):
        return filename or "(none)"
    parsed = parse_ht_filename(filename)
    if parsed:
        return parsed[1]
    return filename.replace("_HT.xml", "")


# ============================================================
# ZIP functions (unchanged)
# ============================================================

def rebuild_zip_central_directory(zip_path):
    with open(zip_path, "rb") as f:
        data = bytearray(f.read())
    local_entries = []
    offset = 0
    while offset < len(data) - 30:
        sig = struct.unpack_from("<I", data, offset)[0]
        if sig == 0x04034B50:
            fields = struct.unpack_from("<HHHHHIIIHH", data, offset + 4)
            ver, flags, method, modtime, moddate, crc, comp_sz, uncomp_sz, fn_len, extra_len = fields
            fn = data[offset + 30:offset + 30 + fn_len].decode("ascii", errors="replace")
            local_entries.append({
                "local_header_offset": offset, "name": fn, "ver": ver, "flags": flags,
                "method": method, "modtime": modtime, "moddate": moddate,
                "crc": crc, "comp_sz": comp_sz, "uncomp_sz": uncomp_sz,
                "fn_len": fn_len, "extra_len": extra_len,
            })
            offset += 30 + fn_len + extra_len + comp_sz
        elif sig == 0x02014B50:
            break
        else:
            offset += 1
    local_data_end = offset
    cd_entries = bytearray()
    for e in local_entries:
        fn_bytes = e["name"].encode("ascii")
        entry = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50,
                            e["ver"], e["ver"], e["flags"], e["method"],
                            e["modtime"], e["moddate"], e["crc"], e["comp_sz"], e["uncomp_sz"],
                            e["fn_len"], 0, 0, 0, 0, 0, e["local_header_offset"])
        cd_entries += entry + fn_bytes
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0,
                       len(local_entries), len(local_entries), len(cd_entries), local_data_end, 0)
    new_zip = bytes(data[:local_data_end]) + bytes(cd_entries) + bytes(eocd)
    with open(zip_path, "wb") as f:
        f.write(new_zip)
    return len(local_entries)


def verify_zip(zip_path):
    with open(zip_path, "rb") as f:
        data = f.read()
    eocd_pos = data.rfind(b"PK\x05\x06")
    if eocd_pos < 0:
        return False, "No EOCD record found"
    cd_offset = struct.unpack_from("<I", data, eocd_pos + 16)[0]
    if cd_offset >= len(data):
        return False, f"CD offset 0x{cd_offset:08x} beyond file size"
    if data[cd_offset:cd_offset + 4] != b"PK\x01\x02":
        return False, f"Invalid CD signature at 0x{cd_offset:08x}"
    entry_count = struct.unpack_from("<H", data, eocd_pos + 10)[0]
    local_count = 0
    offset = 0
    while offset < cd_offset:
        sig = struct.unpack_from("<I", data, offset)[0]
        if sig == 0x04034B50:
            local_count += 1
            fields = struct.unpack_from("<HHHHHIIIHH", data, offset + 4)
            offset += 30 + fields[8] + fields[9] + fields[6]
        else:
            offset += 1
    if local_count != entry_count:
        return False, f"Local headers ({local_count}) != CD entries ({entry_count})"
    return True, f"Valid: {entry_count} files, CD at 0x{cd_offset:08x}"


# ============================================================
# XML write helper
# ============================================================

def write_xml_file(tree, path):
    """Write an ElementTree to file with 2-space indentation."""
    _indent_xml(tree.getroot())
    tree.write(path, encoding="unicode", xml_declaration=False)
    # Ensure trailing newline
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n")


def _indent_xml(elem, level=0):
    """Add pretty-print indentation to an ElementTree."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
    if level == 0:
        elem.tail = "\n"


# ============================================================
# Main Application
# ============================================================

class FM4CarAudioTuner:
    def __init__(self, root):
        self.root = root
        self.root.title("FM4 Car Audio Tuner")
        self.root.geometry("1658x900")
        self.root.minsize(1422, 700)

        self.file_mapping = {}
        self.mapping_loaded = False
        self._load_file_mapping()

        self.car_files = load_car_list()
        self.car_display = [f.replace("_ET.xml", "") for f in self.car_files]
        self.engine_ht, self.intake_ht, self.exhaust_ht = load_ht_files()
        self.current_car_file = None
        self.current_tree = None

        self.clone_enabled = tk.IntVar(value=0)
        self.clone_car_file = None       # Currently selected clone source
        self.clone_car_display = None    # Display name of clone source

        self._undo_stack = []
        self._redo_stack = []
        self._last_state = None
        self._restoring = False
        self._edit_timer = None

        self._build_ui()
        self._update_mapping_indicator()

        self.root.bind_all("<Control-z>", self._on_undo)
        self.root.bind_all("<Control-y>", self._on_redo)
        self.root.bind_all("<ButtonRelease-1>", self._on_possible_edit)
        self.root.bind_all("<Return>", self._on_possible_edit)
        self.root.bind_all("<FocusOut>", self._on_possible_edit)

    # ---- Top selector panel ----

    def _build_ui(self):
        style = ttk.Style()
        style.configure("H.TLabel", font=("Segoe UI", 9, "bold"))

        main = ttk.Frame(self.root, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        # === Top: Car search + list ===
        top = ttk.Frame(main)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Car:", style="H.TLabel").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        ttk.Entry(top, textvariable=self.search_var, width=28).pack(side=tk.LEFT, padx=4)

        ttk.Label(top, text="Cyl:", style="H.TLabel").pack(side=tk.LEFT, padx=(12, 0))
        self.cyl_var = tk.StringVar(value="8")
        cyl_cb = ttk.Combobox(top, textvariable=self.cyl_var, values=CYLINDER_OPTIONS, state="readonly", width=7)
        cyl_cb.pack(side=tk.LEFT, padx=4)
        cyl_cb.bind("<<ComboboxSelected>>", self._on_cylinder_changed)

        ttk.Label(top, text="Redline:", style="H.TLabel").pack(side=tk.LEFT, padx=(12, 0))
        self.redline_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.redline_var, width=8).pack(side=tk.LEFT, padx=4)

        # Output override path (packed from right)
        ttk.Button(top, text="...", width=3, command=self._browse_output).pack(side=tk.RIGHT)
        self.output_var = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.output_var, width=40).pack(side=tk.RIGHT, padx=2)
        ttk.Label(top, text="Output Location Override:", style="H.TLabel").pack(side=tk.RIGHT)

        # Mapping indicator
        indicator_frame = ttk.Frame(top)
        indicator_frame.pack(side=tk.RIGHT, padx=(8, 12))
        self.mapping_indicator = tk.Label(indicator_frame, text="\u25CF", font=("Segoe UI", 10))
        self.mapping_indicator.pack(side=tk.LEFT)
        self.mapping_label = ttk.Label(indicator_frame, text="Output Matched", font=("Segoe UI", 8))
        self.mapping_label.pack(side=tk.LEFT, padx=(2, 0))

        # Find Files button
        ttk.Button(top, text="Find Files", command=self._on_find_files).pack(side=tk.RIGHT, padx=(4, 0))

        # === Car list + Clone Audio split area ===
        list_area = ttk.Frame(main)
        list_area.pack(fill=tk.X, pady=(4, 2))
        list_area.columnconfigure(0, weight=1)  # left half
        list_area.columnconfigure(1, weight=1)  # right half

        # Left: Car list
        left_frame = ttk.Frame(list_area)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self.car_listbox = tk.Listbox(left_frame, height=10, exportselection=False, font=("Consolas", 9))
        self.car_listbox.pack(fill=tk.BOTH, expand=True)
        self.car_listbox.bind("<<ListboxSelect>>", self._on_car_selected)
        self._populate_car_list("")

        # Right: Clone Audio panel
        self._build_clone_panel(list_area)

        # === Component selectors row ===
        comp_row = ttk.Frame(main)
        comp_row.pack(fill=tk.X, pady=(0, 4))

        for label_text, attr_name in [("Engine:", "engine"), ("Intake:", "intake"), ("Exhaust:", "exhaust")]:
            ttk.Label(comp_row, text=label_text, style="H.TLabel").pack(side=tk.LEFT, padx=(8, 0))
            var = tk.StringVar()
            combo = ttk.Combobox(comp_row, textvariable=var, state="readonly", width=28)
            combo.pack(side=tk.LEFT, padx=4)
            setattr(self, f"{attr_name}_var", var)
            setattr(self, f"{attr_name}_combo", combo)

        self._update_ht_dropdowns()

        # === Tabs ===
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(4, 4))

        self.intake_tab = self._build_component_tab("Intake", has_exhaust_extras=False)
        self.engine_tab = self._build_component_tab("Engine", has_exhaust_extras=False)
        self.exhaust_tab = self._build_component_tab("Exhaust", has_exhaust_extras=True)
        self.global_tab = self._build_global_tab()

        self.notebook.add(self.intake_tab["frame"], text="Intake")
        self.notebook.add(self.engine_tab["frame"], text="Engine")
        self.notebook.add(self.exhaust_tab["frame"], text="Exhaust")
        self.notebook.add(self.global_tab["frame"], text="Global Effects")

        # === Bottom buttons ===
        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Save", command=self._on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bottom, text="Export", command=self._on_export).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bottom, text="Backup", command=self._on_backup).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bottom, text="Restore Backup", command=self._on_restore_backup).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self.status_var, foreground="gray").pack(side=tk.RIGHT)

    # ---- Component tab builder ----

    def _build_component_tab(self, name, has_exhaust_extras=False):
        sf = ScrollableFrame(self.notebook)
        interior = sf.interior
        widgets = {"frame": sf}

        # Volume
        vol_lf = ttk.LabelFrame(interior, text="Volume", padding=4)
        vol_lf.pack(fill=tk.X, padx=4, pady=2)
        widgets["vol_active"] = tk.IntVar(value=1)
        ttk.Checkbutton(vol_lf, text="Active", variable=widgets["vol_active"]).pack(anchor=tk.W)
        widgets["vol_gain"] = ParamBlock(vol_lf, "Gain")
        widgets["vol_gain"].pack(side=tk.LEFT, padx=2)

        # PEQ - Gain, CenterFrequency, Bandwidth side by side
        peq_lf = ttk.LabelFrame(interior, text="PEQ", padding=4)
        peq_lf.pack(fill=tk.X, padx=4, pady=2)
        widgets["peq_active"] = tk.IntVar(value=0)
        ttk.Checkbutton(peq_lf, text="Active", variable=widgets["peq_active"]).pack(anchor=tk.W)
        peq_row = ttk.Frame(peq_lf)
        peq_row.pack(fill=tk.X)
        widgets["peq_gain"] = ParamBlock(peq_row, "Gain")
        widgets["peq_gain"].pack(side=tk.LEFT, padx=2)
        widgets["peq_freq"] = ParamBlock(peq_row, "CenterFrequency")
        widgets["peq_freq"].pack(side=tk.LEFT, padx=2)
        widgets["peq_bw"] = ParamBlock(peq_row, "Bandwidth")
        widgets["peq_bw"].pack(side=tk.LEFT, padx=2)

        # Lowpass - CutoffFrequency, Resonance side by side
        lp_lf = ttk.LabelFrame(interior, text="Lowpass", padding=4)
        lp_lf.pack(fill=tk.X, padx=4, pady=2)
        widgets["lp_active"] = tk.IntVar(value=0)
        ttk.Checkbutton(lp_lf, text="Active", variable=widgets["lp_active"]).pack(anchor=tk.W)
        lp_row = ttk.Frame(lp_lf)
        lp_row.pack(fill=tk.X)
        widgets["lp_cutoff"] = ParamBlock(lp_row, "CutoffFrequency")
        widgets["lp_cutoff"].pack(side=tk.LEFT, padx=2)
        widgets["lp_res"] = ParamBlock(lp_row, "Resonance")
        widgets["lp_res"].pack(side=tk.LEFT, padx=2)

        if has_exhaust_extras:
            # Expander
            exp_lf = ttk.LabelFrame(interior, text="Expander", padding=4)
            exp_lf.pack(fill=tk.X, padx=4, pady=2)
            widgets["exp_maxgain"] = ParamBlock(exp_lf, "MaxGain")
            widgets["exp_maxgain"].pack(side=tk.LEFT, padx=2)

            exp_settings = ttk.Frame(exp_lf)
            exp_settings.pack(side=tk.LEFT, padx=(12, 0))
            for attr in ["AttackTime", "HoldTime", "ReleaseTime"]:
                ttk.Label(exp_settings, text=attr + ":", font=("Segoe UI", 8)).pack(side=tk.LEFT)
                var = tk.StringVar(value="0.0")
                ttk.Entry(exp_settings, textvariable=var, width=8).pack(side=tk.LEFT, padx=(2, 8))
                widgets[f"exp_{attr.lower()}"] = var

            # LoadPEQ - PosLoad - Gain, CenterFrequency, Bandwidth side by side
            lpeq_lf = ttk.LabelFrame(interior, text="Load PEQ - Positive Load", padding=4)
            lpeq_lf.pack(fill=tk.X, padx=4, pady=2)
            widgets["posload_active"] = tk.IntVar(value=0)
            ttk.Checkbutton(lpeq_lf, text="Active", variable=widgets["posload_active"]).pack(anchor=tk.W)
            posload_row = ttk.Frame(lpeq_lf)
            posload_row.pack(fill=tk.X)
            widgets["posload_gain"] = ParamBlock(posload_row, "Gain")
            widgets["posload_gain"].pack(side=tk.LEFT, padx=2)
            widgets["posload_freq"] = ParamBlock(posload_row, "CenterFrequency")
            widgets["posload_freq"].pack(side=tk.LEFT, padx=2)
            widgets["posload_bw"] = ParamBlock(posload_row, "Bandwidth")
            widgets["posload_bw"].pack(side=tk.LEFT, padx=2)

            # LoadPEQ - NegLoad - Gain, CenterFrequency, Bandwidth side by side
            npeq_lf = ttk.LabelFrame(interior, text="Load PEQ - Negative Load", padding=4)
            npeq_lf.pack(fill=tk.X, padx=4, pady=2)
            widgets["negload_active"] = tk.IntVar(value=0)
            ttk.Checkbutton(npeq_lf, text="Active", variable=widgets["negload_active"]).pack(anchor=tk.W)
            negload_row = ttk.Frame(npeq_lf)
            negload_row.pack(fill=tk.X)
            widgets["negload_gain"] = ParamBlock(negload_row, "Gain")
            widgets["negload_gain"].pack(side=tk.LEFT, padx=2)
            widgets["negload_freq"] = ParamBlock(negload_row, "CenterFrequency")
            widgets["negload_freq"].pack(side=tk.LEFT, padx=2)
            widgets["negload_bw"] = ParamBlock(negload_row, "Bandwidth")
            widgets["negload_bw"].pack(side=tk.LEFT, padx=2)

        return widgets

    # ---- Global effects tab ----

    def _build_global_tab(self):
        sf = ScrollableFrame(self.notebook)
        interior = sf.interior
        w = {"frame": sf}

        # FocusPEQ - Gain, CenterFrequency, Bandwidth side by side
        fpeq_lf = ttk.LabelFrame(interior, text="FocusPEQ", padding=4)
        fpeq_lf.pack(fill=tk.X, padx=4, pady=2)
        w["fpeq_active"] = tk.IntVar(value=0)
        ttk.Checkbutton(fpeq_lf, text="Active", variable=w["fpeq_active"]).pack(anchor=tk.W)
        fpeq_row = ttk.Frame(fpeq_lf)
        fpeq_row.pack(fill=tk.X)
        w["fpeq_gain"] = ParamBlock(fpeq_row, "Gain")
        w["fpeq_gain"].pack(side=tk.LEFT, padx=2)
        w["fpeq_freq"] = ParamBlock(fpeq_row, "CenterFrequency")
        w["fpeq_freq"].pack(side=tk.LEFT, padx=2)
        w["fpeq_bw"] = ParamBlock(fpeq_row, "Bandwidth")
        w["fpeq_bw"].pack(side=tk.LEFT, padx=2)

        # Distortion
        dist_lf = ttk.LabelFrame(interior, text="Distortion", padding=4)
        dist_lf.pack(fill=tk.X, padx=4, pady=2)
        dist_top = ttk.Frame(dist_lf)
        dist_top.pack(fill=tk.X)
        w["dist_active"] = tk.IntVar(value=0)
        ttk.Checkbutton(dist_top, text="Active", variable=w["dist_active"]).pack(side=tk.LEFT)
        ttk.Label(dist_top, text="VolComp:").pack(side=tk.LEFT, padx=(12, 0))
        w["dist_volcomp"] = tk.StringVar(value="0.0")
        ttk.Entry(dist_top, textvariable=w["dist_volcomp"], width=8).pack(side=tk.LEFT, padx=2)
        w["dist_level"] = ParamBlock(dist_lf, "Level")
        w["dist_level"].pack(side=tk.LEFT, padx=2)

        # Compressor
        comp_lf = ttk.LabelFrame(interior, text="Compressor", padding=4)
        comp_lf.pack(fill=tk.X, padx=4, pady=2)
        comp_row = ttk.Frame(comp_lf)
        comp_row.pack(fill=tk.X)
        w["comp_active"] = tk.IntVar(value=0)
        ttk.Checkbutton(comp_row, text="Active", variable=w["comp_active"]).pack(side=tk.LEFT)
        for attr in ["Threshold", "Attack", "Release", "GainMakeup"]:
            ttk.Label(comp_row, text=attr + ":").pack(side=tk.LEFT, padx=(8, 0))
            var = tk.StringVar(value="0.0")
            ttk.Entry(comp_row, textvariable=var, width=7).pack(side=tk.LEFT, padx=2)
            w[f"comp_{attr.lower()}"] = var

        # ShiftVolumeScalar
        svs_lf = ttk.LabelFrame(interior, text="ShiftVolumeScalar", padding=4)
        svs_lf.pack(fill=tk.X, padx=4, pady=2)
        svs_row = ttk.Frame(svs_lf)
        svs_row.pack(fill=tk.X)
        for attr in ["ShiftVolBoostUpPct", "ShiftVolBoostUpTime", "ShiftVolBoostDownPct", "ShiftVolBoostDownTime"]:
            short = attr.replace("ShiftVolBoost", "")
            ttk.Label(svs_row, text=short + ":").pack(side=tk.LEFT, padx=(4, 0))
            var = tk.StringVar(value="0.0")
            ttk.Entry(svs_row, textvariable=var, width=8).pack(side=tk.LEFT, padx=2)
            w[f"svs_{attr.lower()}"] = var

        # TrashDSP
        trash_lf = ttk.LabelFrame(interior, text="TrashDSP", padding=4)
        trash_lf.pack(fill=tk.X, padx=4, pady=2)

        trash_top = ttk.Frame(trash_lf)
        trash_top.pack(fill=tk.X, pady=(0, 4))
        w["trash_active"] = tk.IntVar(value=0)
        ttk.Checkbutton(trash_top, text="Active", variable=w["trash_active"]).pack(side=tk.LEFT)
        w["trash_usecurves"] = tk.IntVar(value=0)
        ttk.Checkbutton(trash_top, text="UseCurves", variable=w["trash_usecurves"]).pack(side=tk.LEFT, padx=8)
        ttk.Label(trash_top, text="VolComp:").pack(side=tk.LEFT, padx=(8, 0))
        w["trash_volcomp"] = tk.StringVar(value="0.0")
        ttk.Entry(trash_top, textvariable=w["trash_volcomp"], width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(trash_top, text="Cutoff1:").pack(side=tk.LEFT, padx=(8, 0))
        w["trash_cutoff1"] = tk.StringVar(value="0")
        ttk.Entry(trash_top, textvariable=w["trash_cutoff1"], width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(trash_top, text="Cutoff2:").pack(side=tk.LEFT, padx=(8, 0))
        w["trash_cutoff2"] = tk.StringVar(value="0")
        ttk.Entry(trash_top, textvariable=w["trash_cutoff2"], width=6).pack(side=tk.LEFT, padx=2)

        for band_num in range(1, 4):
            band_lf = ttk.LabelFrame(trash_lf, text=f"Band {band_num}", padding=4)
            band_lf.pack(fill=tk.X, pady=2)

            band_top = ttk.Frame(band_lf)
            band_top.pack(fill=tk.X, pady=(0, 2))
            ttk.Label(band_top, text="Effect Type:").pack(side=tk.LEFT)
            et_var = tk.StringVar(value="1.000000")
            et_combo = ttk.Combobox(band_top, textvariable=et_var,
                                    values=["1.000000", "2.000000", "3.000000"], state="readonly", width=10)
            et_combo.pack(side=tk.LEFT, padx=4)
            w[f"trash_b{band_num}_effecttype"] = et_var

            # Scalar attrs shown inline
            for scalar_attr in ["inputgain", "overdrive", "mix", "outputgain"]:
                ttk.Label(band_top, text=scalar_attr + ":").pack(side=tk.LEFT, padx=(6, 0))
                svar = tk.StringVar(value="0.0")
                ttk.Entry(band_top, textvariable=svar, width=6).pack(side=tk.LEFT, padx=2)
                w[f"trash_b{band_num}_{scalar_attr}_attr"] = svar

            # Curve params - 2x2 grid: inputgain+overdrive on top, mix+outputgain below
            band_row1 = ttk.Frame(band_lf)
            band_row1.pack(fill=tk.X, pady=1)
            band_row2 = ttk.Frame(band_lf)
            band_row2.pack(fill=tk.X, pady=1)
            for i, param in enumerate(["inputgain", "overdrive", "mix", "outputgain"]):
                row = band_row1 if i < 2 else band_row2
                pb = ParamBlock(row, param)
                pb.pack(side=tk.LEFT, padx=2)
                w[f"trash_b{band_num}_{param}"] = pb

        return w

    def _browse_output(self):
        path = filedialog.askdirectory(initialdir=self.output_var.get() or BASE_DIR,
                                       title="Select output override folder")
        if path:
            self.output_var.set(path)

    # ---- File mapping / Find Files ----

    def _load_file_mapping(self):
        if os.path.isfile(FILE_MAPPING_PATH):
            try:
                with open(FILE_MAPPING_PATH, "r") as f:
                    self.file_mapping = json.load(f)
                self.mapping_loaded = True
            except (json.JSONDecodeError, OSError):
                self.file_mapping = {}
                self.mapping_loaded = False
        else:
            self.file_mapping = {}
            self.mapping_loaded = False

    def _save_file_mapping(self):
        with open(FILE_MAPPING_PATH, "w") as f:
            json.dump(self.file_mapping, f, indent=2)

    def _update_mapping_indicator(self):
        if self.mapping_loaded and self.file_mapping:
            self.mapping_indicator.configure(fg="green")
        else:
            self.mapping_indicator.configure(fg="gray")

    def _on_find_files(self):
        scan_root = filedialog.askdirectory(
            initialdir=DEFAULT_SCAN_ROOT,
            title="Select root directory to scan for tuning files")
        if not scan_root:
            return

        self.status_var.set("Scanning for files...")
        self.root.update()

        found_et = {}  # filename -> source_path
        found_ht = {}  # filename -> source_path
        main_et_zip = None
        main_ht_zip = None

        norm_et = os.path.normpath(ET_DIR)
        norm_dlc_et = os.path.normpath(DLC_ET_DIR)
        norm_ht = os.path.normpath(HT_DIR)
        norm_dlc_ht = os.path.normpath(DLC_HT_DIR)

        for dirpath, dirnames, filenames in os.walk(scan_root):
            norm_dir = os.path.normpath(dirpath)
            for fn in filenames:
                if fn == "enginetuning.zip":
                    full = os.path.join(dirpath, fn)
                    if main_et_zip is None or "DVD1" in dirpath:
                        main_et_zip = full
                elif fn == "harmonictuning.zip":
                    full = os.path.join(dirpath, fn)
                    if main_ht_zip is None or "DVD1" in dirpath:
                        main_ht_zip = full
                elif fn.endswith("_ET.xml"):
                    if norm_dir in (norm_et, norm_dlc_et):
                        continue
                    if fn not in found_et:
                        found_et[fn] = os.path.join(dirpath, fn)
                elif fn.endswith("_HT.xml"):
                    if norm_dir in (norm_ht, norm_dlc_ht):
                        continue
                    if fn not in found_ht:
                        found_ht[fn] = os.path.join(dirpath, fn)

        # Separate new DLC files from files already in ET_DIR
        existing_et = set(os.listdir(ET_DIR)) if os.path.isdir(ET_DIR) else set()
        new_et = {fn: p for fn, p in found_et.items() if fn not in existing_et}

        existing_ht = set(os.listdir(HT_DIR)) if os.path.isdir(HT_DIR) else set()
        new_ht = {fn: p for fn, p in found_ht.items() if fn not in existing_ht}

        # Create DLC working directories and copy files
        os.makedirs(DLC_ET_DIR, exist_ok=True)
        os.makedirs(DLC_HT_DIR, exist_ok=True)

        et_copied = 0
        for fn, source in new_et.items():
            dest = os.path.join(DLC_ET_DIR, fn)
            shutil.copy2(source, dest)
            et_copied += 1

        ht_copied = 0
        for fn, source in new_ht.items():
            dest = os.path.join(DLC_HT_DIR, fn)
            shutil.copy2(source, dest)
            ht_copied += 1

        # Build mapping
        mapping = {
            "version": 1,
            "scan_root": scan_root,
            "main_et_zip": main_et_zip,
            "main_ht_zip": main_ht_zip,
            "et_files": {},
            "ht_files": {},
        }

        # Map DLC ET files
        for fn, source in new_et.items():
            mapping["et_files"][fn] = {
                "source_path": source,
                "output_dir": os.path.dirname(source),
            }

        # Map loose override ET files (exist in both ET_DIR and found locations)
        for fn, source in found_et.items():
            if fn in existing_et and fn not in new_et:
                mapping["et_files"][fn] = {
                    "source_path": source,
                    "output_dir": os.path.dirname(source),
                }

        # Map DLC HT files
        for fn, source in new_ht.items():
            mapping["ht_files"][fn] = {
                "source_path": source,
                "output_dir": os.path.dirname(source),
            }

        self.file_mapping = mapping
        self.mapping_loaded = True
        self._save_file_mapping()

        # Refresh car list and HT dropdowns
        self.car_files = load_car_list()
        self.car_display = [f.replace("_ET.xml", "") for f in self.car_files]
        self.engine_ht, self.intake_ht, self.exhaust_ht = load_ht_files()
        self._populate_car_list(self.search_var.get())
        self._update_ht_dropdowns()

        self._update_mapping_indicator()

        self.status_var.set(
            f"Found {et_copied} new cars, {ht_copied} new HT files. "
            f"Total: {len(self.car_files)} cars.")
        messagebox.showinfo("Find Files Complete",
            f"Scanned: {scan_root}\n"
            f"New ET files: {et_copied}\n"
            f"New HT files: {ht_copied}\n"
            f"Total cars: {len(self.car_files)}\n"
            f"Main ZIP: {main_et_zip or 'not found'}")

    # ---- Car list ----

    def _populate_car_list(self, filter_text):
        self.car_listbox.delete(0, tk.END)
        ft = filter_text.lower()
        self._filtered_indices = []
        for i, name in enumerate(self.car_display):
            if ft in name.lower():
                self.car_listbox.insert(tk.END, name)
                self._filtered_indices.append(i)

    def _on_search_changed(self, *args):
        self._populate_car_list(self.search_var.get())

    # ---- Clone Audio panel ----

    def _build_clone_panel(self, parent):
        right_frame = ttk.LabelFrame(parent, text="Clone Audio", padding=4)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # Enable checkbox
        cb = ttk.Checkbutton(right_frame, text="Enable Clone",
                             variable=self.clone_enabled,
                             command=self._on_clone_checkbox_changed)
        cb.pack(anchor=tk.W)

        # Clone search
        self.clone_search_var = tk.StringVar()
        self.clone_search_var.trace_add("write", self._on_clone_search_changed)
        ttk.Entry(right_frame, textvariable=self.clone_search_var).pack(fill=tk.X, pady=(2, 2))

        # Clone listbox
        self.clone_listbox = tk.Listbox(right_frame, height=10, exportselection=False, font=("Consolas", 9))
        self.clone_listbox.pack(fill=tk.BOTH, expand=True)
        self.clone_listbox.bind("<<ListboxSelect>>", self._on_clone_car_selected)
        self._populate_clone_list("")

        # Override message
        self.clone_msg_var = tk.StringVar(value="")
        self.clone_msg_label = ttk.Label(right_frame, textvariable=self.clone_msg_var,
                                         wraplength=300, foreground="orange",
                                         font=("Segoe UI", 8))
        self.clone_msg_label.pack(anchor=tk.W, pady=(2, 0))

    def _populate_clone_list(self, filter_text):
        self.clone_listbox.delete(0, tk.END)
        ft = filter_text.lower()
        self._clone_filtered_indices = []
        for i, name in enumerate(self.car_display):
            if ft in name.lower():
                self.clone_listbox.insert(tk.END, name)
                self._clone_filtered_indices.append(i)

    def _on_clone_search_changed(self, *args):
        self._populate_clone_list(self.clone_search_var.get())

    def _on_clone_checkbox_changed(self):
        if not self.clone_enabled.get():
            # Unchecked - reload original car data if we had a clone active
            if self.clone_car_file and self.current_car_file and self.current_tree is not None:
                root = self.current_tree.getroot()
                self._load_emission_group(root, "EmissionGroup0", self.intake_tab)
                self._load_emission_group(root, "EmissionGroup1", self.engine_tab)
                self._load_emission_group(root, "EmissionGroup2", self.exhaust_tab)
                self._load_vol_sidecar(self.current_car_file)
                self._load_global_effects(root)

                # Restore redline and component selectors from current car
                settings = root.find("EngineSettings")
                self.redline_var.set(settings.get("audio_rpm_redline", "") if settings is not None else "")
                el = root.find("EngineAmbient/Upgrade")
                self._select_ht_combo(self.engine_combo, self.engine_var,
                                      el.get("L0", "") if el is not None else "", self.engine_ht)
                el = root.find("EngineIntake/Upgrade")
                self._select_ht_combo(self.intake_combo, self.intake_var,
                                      el.get("L3", "") if el is not None else "", self.intake_ht)
                el = root.find("Exhaust/Upgrade")
                self._select_ht_combo(self.exhaust_combo, self.exhaust_var,
                                      el.get("L3", "") if el is not None else "", self.exhaust_ht)

                self.status_var.set(f"Clone disabled - restored: {self.current_car_file.replace('_ET.xml', '')}")

            self.clone_car_file = None
            self.clone_car_display = None
            self.clone_msg_var.set("")

    def _on_clone_car_selected(self, event):
        if not self.clone_enabled.get():
            return
        sel = self.clone_listbox.curselection()
        if not sel:
            return
        idx = self._clone_filtered_indices[sel[0]]
        clone_file = self.car_files[idx]
        clone_display = self.car_display[idx]

        # Don't clone from the same car
        if clone_file == self.current_car_file:
            return

        # Parse clone car's XML into a temporary tree
        try:
            clone_path = resolve_et_path(clone_file)
            if clone_path is None:
                messagebox.showerror("Error", f"Cannot find clone source: {clone_file}")
                return
            clone_tree = ET.parse(clone_path)
            clone_root = clone_tree.getroot()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse clone source {clone_file}:\n{e}")
            return

        self.clone_car_file = clone_file
        self.clone_car_display = clone_display

        # Load clone car's data into UI widgets (without changing current_tree)
        self._load_emission_group(clone_root, "EmissionGroup0", self.intake_tab)
        self._load_emission_group(clone_root, "EmissionGroup1", self.engine_tab)
        self._load_emission_group(clone_root, "EmissionGroup2", self.exhaust_tab)
        self._load_global_effects(clone_root)

        # Update redline from clone
        settings = clone_root.find("EngineSettings")
        self.redline_var.set(settings.get("audio_rpm_redline", "") if settings is not None else "")

        # Update component selectors from clone
        el = clone_root.find("EngineAmbient/Upgrade")
        self._select_ht_combo(self.engine_combo, self.engine_var,
                              el.get("L0", "") if el is not None else "", self.engine_ht)
        el = clone_root.find("EngineIntake/Upgrade")
        self._select_ht_combo(self.intake_combo, self.intake_var,
                              el.get("L3", "") if el is not None else "", self.intake_ht)
        el = clone_root.find("Exhaust/Upgrade")
        self._select_ht_combo(self.exhaust_combo, self.exhaust_var,
                              el.get("L3", "") if el is not None else "", self.exhaust_ht)

        # Show override message
        self.clone_msg_var.set(
            f"Vehicle Settings Overridden.\n"
            f"To adjust cloned settings go to:\n{clone_display}")

        self.status_var.set(f"Cloned audio from: {clone_display}")

    # ---- HT dropdown management ----

    def _auto_detect_cylinders(self, exh_filename):
        """Set the Cyl dropdown based on the exhaust HT filename's cylinder key."""
        if not exh_filename:
            return
        parsed = parse_ht_filename(exh_filename)
        if not parsed:
            return
        cyl_key = parsed[3]  # e.g. "4", "8", "2R", "NA"
        if cyl_key == "2R":
            option = "Rotary"
        elif cyl_key in CYLINDER_OPTIONS:
            option = cyl_key
        else:
            # Map keys like "2", "3", "16" to their group's canonical option
            for opt in CYLINDER_OPTIONS:
                group = CYLINDER_GROUPS.get(opt, [])
                if cyl_key in group:
                    option = opt
                    break
            else:
                return
        if self.cyl_var.get() != option:
            self.cyl_var.set(option)
            self._update_ht_dropdowns()

    def _on_cylinder_changed(self, event=None):
        self._update_ht_dropdowns()

    def _update_ht_dropdowns(self):
        cyl_sel = self.cyl_var.get()
        allowed = CYLINDER_GROUPS.get(cyl_sel, [])

        def matches(entry):
            return entry["cyl_key"] in allowed or entry["cyl_key"] == "NA"

        for attr, ht_list in [("engine", self.engine_ht), ("intake", self.intake_ht), ("exhaust", self.exhaust_ht)]:
            filtered = [e["display"] for e in ht_list if matches(e)]
            getattr(self, f"{attr}_combo")["values"] = filtered

    def _select_ht_combo(self, combo, var, filename, ht_list):
        display = ht_display_name(filename)
        values = list(combo["values"])
        if display not in values:
            values.insert(0, display)
            combo["values"] = values
        var.set(display)

    def _get_filename_from_display(self, display, ht_list):
        for entry in ht_list:
            if entry["display"] == display:
                return entry["filename"]
        return None

    # ---- Car selection / data load ----

    def _on_car_selected(self, event):
        sel = self.car_listbox.curselection()
        if not sel:
            return
        idx = self._filtered_indices[sel[0]]
        car_file = self.car_files[idx]
        self.current_car_file = car_file

        try:
            path = resolve_et_path(car_file)
            if path is None:
                messagebox.showerror("Error", f"Cannot find file: {car_file}")
                return
            self.current_tree = ET.parse(path)
            root = self.current_tree.getroot()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse {car_file}:\n{e}")
            return

        # Redline
        settings = root.find("EngineSettings")
        self.redline_var.set(settings.get("audio_rpm_redline", "") if settings is not None else "")

        # Component selectors
        el = root.find("EngineAmbient/Upgrade")
        self._select_ht_combo(self.engine_combo, self.engine_var, el.get("L0", "") if el is not None else "", self.engine_ht)
        el = root.find("EngineIntake/Upgrade")
        self._select_ht_combo(self.intake_combo, self.intake_var, el.get("L3", "") if el is not None else "", self.intake_ht)
        el = root.find("Exhaust/Upgrade")
        exh_filename = el.get("L3", "") if el is not None else ""
        self._select_ht_combo(self.exhaust_combo, self.exhaust_var, exh_filename, self.exhaust_ht)

        # Auto-detect cylinder type from exhaust HT filename
        self._auto_detect_cylinders(exh_filename)

        # Load emission groups
        self._load_emission_group(root, "EmissionGroup0", self.intake_tab)
        self._load_emission_group(root, "EmissionGroup1", self.engine_tab)
        self._load_emission_group(root, "EmissionGroup2", self.exhaust_tab)

        # Restore preserved volume data from sidecar (overrides XML zeros)
        self._load_vol_sidecar(car_file)

        # Load global effects
        self._load_global_effects(root)

        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_state = self._capture_state()
        self.status_var.set(f"Loaded: {self.car_display[idx]}")

    def _load_emission_group(self, root, group_name, tab):
        eg = root.find(f"HarmonicTunings/{group_name}")
        if eg is None:
            return

        # Volume
        tab["vol_gain"].load_from_xml(eg.find("Volume/Gain"))

        # PEQ
        peq = eg.find("PEQ")
        if peq is not None:
            tab["peq_active"].set(int(peq.get("Active", "0")))
            tab["peq_gain"].load_from_xml(peq.find("Gain"))
            tab["peq_freq"].load_from_xml(peq.find("CenterFrequency"))
            tab["peq_bw"].load_from_xml(peq.find("Bandwidth"))

        # Lowpass
        lp = eg.find("Lowpass")
        if lp is not None:
            tab["lp_active"].set(int(lp.get("Active", "0")))
            tab["lp_cutoff"].load_from_xml(lp.find("CutoffFrequency"))
            tab["lp_res"].load_from_xml(lp.find("Resonance"))

        # Exhaust extras
        if "exp_maxgain" in tab:
            exp = eg.find("Expander")
            if exp is not None:
                tab["exp_maxgain"].load_from_xml(exp.find("MaxGain"))
                settings = exp.find("Settings")
                if settings is not None:
                    for attr in ["AttackTime", "HoldTime", "ReleaseTime"]:
                        tab[f"exp_{attr.lower()}"].set(settings.get(attr, "0.0"))

            lpeq = eg.find("LoadPEQ")
            if lpeq is not None:
                pos = lpeq.find("PosLoad")
                if pos is not None:
                    tab["posload_active"].set(int(pos.get("Active", "0")))
                    tab["posload_gain"].load_from_xml(pos.find("Gain"))
                    tab["posload_freq"].load_from_xml(pos.find("CenterFrequency"))
                    tab["posload_bw"].load_from_xml(pos.find("Bandwidth"))
                neg = lpeq.find("NegLoad")
                if neg is not None:
                    tab["negload_active"].set(int(neg.get("Active", "0")))
                    tab["negload_gain"].load_from_xml(neg.find("Gain"))
                    tab["negload_freq"].load_from_xml(neg.find("CenterFrequency"))
                    tab["negload_bw"].load_from_xml(neg.find("Bandwidth"))

    def _load_global_effects(self, root):
        w = self.global_tab

        # FocusPEQ
        fpeq = root.find("FocusPEQ")
        if fpeq is not None:
            w["fpeq_active"].set(int(fpeq.get("Active", "0")))
            w["fpeq_gain"].load_from_xml(fpeq.find("Gain"))
            w["fpeq_freq"].load_from_xml(fpeq.find("CenterFrequency"))
            w["fpeq_bw"].load_from_xml(fpeq.find("Bandwidth"))

        # Distortion
        dist = root.find("Distortion")
        if dist is not None:
            w["dist_active"].set(int(dist.get("Active", "0")))
            w["dist_volcomp"].set(dist.get("VolumeCompensate", "0.0"))
            w["dist_level"].load_from_xml(dist.find("Level"))

        # Compressor
        comp = root.find("Compressor")
        if comp is not None:
            w["comp_active"].set(int(comp.get("Active", "0")))
            for attr in ["Threshold", "Attack", "Release", "GainMakeup"]:
                w[f"comp_{attr.lower()}"].set(comp.get(attr, "0.0"))

        # ShiftVolumeScalar
        svs = root.find("ShiftVolumeScalar")
        if svs is not None:
            for attr in ["ShiftVolBoostUpPct", "ShiftVolBoostUpTime", "ShiftVolBoostDownPct", "ShiftVolBoostDownTime"]:
                w[f"svs_{attr.lower()}"].set(svs.get(attr, "0.0"))

        # TrashDSP
        trash = root.find("TrashDSP")
        if trash is not None:
            w["trash_active"].set(int(trash.get("Active", "0")))
            w["trash_usecurves"].set(int(trash.get("UseCurves", "0")))
            w["trash_volcomp"].set(trash.get("VolumeCompensate", "0.0"))
            w["trash_cutoff1"].set(trash.get("Cutoff1", "0"))
            w["trash_cutoff2"].set(trash.get("Cutoff2", "0"))

            for band_num in range(1, 4):
                band = trash.find(f"Band{band_num}")
                if band is None:
                    continue
                w[f"trash_b{band_num}_effecttype"].set(band.get("effecttype", "1.000000"))
                for scalar in ["inputgain", "overdrive", "mix", "outputgain"]:
                    w[f"trash_b{band_num}_{scalar}_attr"].set(band.get(scalar, "0.0"))
                    child = band.find(scalar)
                    if child is not None:
                        w[f"trash_b{band_num}_{scalar}"].load_from_xml(child)

    # ---- Save emission group back to XML ----

    def _save_emission_group(self, root, group_name, tab):
        eg = root.find(f"HarmonicTunings/{group_name}")
        if eg is None:
            return

        tab["vol_gain"].save_to_xml(eg.find("Volume/Gain"))

        # If volume muted, zero out the curve Y values in XML
        if not tab["vol_active"].get():
            vol_tc = eg.find("Volume/Gain/ThreePointCurve")
            if vol_tc is not None:
                for attr in ("y0", "y1", "y2"):
                    vol_tc.set(attr, "0.000000")

        peq = eg.find("PEQ")
        if peq is not None:
            peq.set("Active", str(tab["peq_active"].get()))
            tab["peq_gain"].save_to_xml(peq.find("Gain"))
            tab["peq_freq"].save_to_xml(peq.find("CenterFrequency"))
            tab["peq_bw"].save_to_xml(peq.find("Bandwidth"))

        lp = eg.find("Lowpass")
        if lp is not None:
            lp.set("Active", str(tab["lp_active"].get()))
            tab["lp_cutoff"].save_to_xml(lp.find("CutoffFrequency"))
            tab["lp_res"].save_to_xml(lp.find("Resonance"))

        if "exp_maxgain" in tab:
            exp = eg.find("Expander")
            if exp is not None:
                tab["exp_maxgain"].save_to_xml(exp.find("MaxGain"))
                settings = exp.find("Settings")
                if settings is not None:
                    for attr in ["AttackTime", "HoldTime", "ReleaseTime"]:
                        settings.set(attr, tab[f"exp_{attr.lower()}"].get())

            lpeq = eg.find("LoadPEQ")
            if lpeq is not None:
                pos = lpeq.find("PosLoad")
                if pos is not None:
                    pos.set("Active", str(tab["posload_active"].get()))
                    tab["posload_gain"].save_to_xml(pos.find("Gain"))
                    tab["posload_freq"].save_to_xml(pos.find("CenterFrequency"))
                    tab["posload_bw"].save_to_xml(pos.find("Bandwidth"))
                neg = lpeq.find("NegLoad")
                if neg is not None:
                    neg.set("Active", str(tab["negload_active"].get()))
                    tab["negload_gain"].save_to_xml(neg.find("Gain"))
                    tab["negload_freq"].save_to_xml(neg.find("CenterFrequency"))
                    tab["negload_bw"].save_to_xml(neg.find("Bandwidth"))

    def _save_global_effects(self, root):
        w = self.global_tab

        fpeq = root.find("FocusPEQ")
        if fpeq is not None:
            fpeq.set("Active", str(w["fpeq_active"].get()))
            w["fpeq_gain"].save_to_xml(fpeq.find("Gain"))
            w["fpeq_freq"].save_to_xml(fpeq.find("CenterFrequency"))
            w["fpeq_bw"].save_to_xml(fpeq.find("Bandwidth"))

        dist = root.find("Distortion")
        if dist is not None:
            dist.set("Active", str(w["dist_active"].get()))
            dist.set("VolumeCompensate", w["dist_volcomp"].get())
            w["dist_level"].save_to_xml(dist.find("Level"))

        comp = root.find("Compressor")
        if comp is not None:
            comp.set("Active", str(w["comp_active"].get()))
            for attr in ["Threshold", "Attack", "Release", "GainMakeup"]:
                comp.set(attr, w[f"comp_{attr.lower()}"].get())

        svs = root.find("ShiftVolumeScalar")
        if svs is not None:
            for attr in ["ShiftVolBoostUpPct", "ShiftVolBoostUpTime", "ShiftVolBoostDownPct", "ShiftVolBoostDownTime"]:
                svs.set(attr, w[f"svs_{attr.lower()}"].get())

        trash = root.find("TrashDSP")
        if trash is not None:
            trash.set("Active", str(w["trash_active"].get()))
            trash.set("UseCurves", str(w["trash_usecurves"].get()))
            trash.set("VolumeCompensate", w["trash_volcomp"].get())
            trash.set("Cutoff1", w["trash_cutoff1"].get())
            trash.set("Cutoff2", w["trash_cutoff2"].get())

            for band_num in range(1, 4):
                band = trash.find(f"Band{band_num}")
                if band is None:
                    continue
                band.set("effecttype", w[f"trash_b{band_num}_effecttype"].get())
                for scalar in ["inputgain", "overdrive", "mix", "outputgain"]:
                    band.set(scalar, w[f"trash_b{band_num}_{scalar}_attr"].get())
                    child = band.find(scalar)
                    if child is not None:
                        w[f"trash_b{band_num}_{scalar}"].save_to_xml(child)

    # ---- Volume sidecar (preserve values when muted) ----

    def _vol_sidecar_path(self, car_file):
        if os.path.isfile(os.path.join(DLC_ET_DIR, car_file)):
            return os.path.join(DLC_ET_DIR, car_file + ".volstate.json")
        return os.path.join(ET_DIR, car_file + ".volstate.json")

    def _save_vol_sidecar(self, car_file):
        """Save/update sidecar for muted volumes, remove entries for active ones."""
        sidecar_path = self._vol_sidecar_path(car_file)
        data = {}
        for group_name, tab in [("EmissionGroup0", self.intake_tab),
                                 ("EmissionGroup1", self.engine_tab),
                                 ("EmissionGroup2", self.exhaust_tab)]:
            if not tab["vol_active"].get():
                # Muted - preserve the real UI values
                data[group_name] = {
                    "pc": tab["vol_gain"].physcoef.get_values(),
                    "curve": tab["vol_gain"].curve.get_values(),
                }
        if data:
            with open(sidecar_path, "w") as f:
                json.dump(data, f, indent=2)
        else:
            # All active - remove sidecar if it exists
            if os.path.isfile(sidecar_path):
                os.remove(sidecar_path)

    def _load_vol_sidecar(self, car_file):
        """Restore preserved volume values and set Active toggles."""
        sidecar_path = self._vol_sidecar_path(car_file)
        if not os.path.isfile(sidecar_path):
            # No sidecar - all volumes active
            self.intake_tab["vol_active"].set(1)
            self.engine_tab["vol_active"].set(1)
            self.exhaust_tab["vol_active"].set(1)
            return

        try:
            with open(sidecar_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for group_name, tab in [("EmissionGroup0", self.intake_tab),
                                 ("EmissionGroup1", self.engine_tab),
                                 ("EmissionGroup2", self.exhaust_tab)]:
            if group_name in data:
                # This volume was muted - restore real values and mark inactive
                preserved = data[group_name]
                pc = preserved["pc"]
                tab["vol_gain"].physcoef.set_values(
                    pc["RPM"], pc["Throttle"], pc["PosTorque"], pc["NegTorque"])
                cv = preserved["curve"]
                tab["vol_gain"].curve.set_values(
                    cv["x0"], cv["y0"], cv["x1"], cv["y1"], cv["x2"], cv["y2"])
                tab["vol_gain"]._update_flat_mode()
                tab["vol_active"].set(0)
            else:
                tab["vol_active"].set(1)

    # ---- Undo / Redo ----

    def _capture_state(self):
        """Snapshot all widget values into a comparable tuple."""
        state = {}
        state["redline"] = self.redline_var.get()
        state["engine"] = self.engine_var.get()
        state["intake_sel"] = self.intake_var.get()
        state["exhaust_sel"] = self.exhaust_var.get()

        for tab_name, tab in [("int", self.intake_tab), ("eng", self.engine_tab), ("exh", self.exhaust_tab)]:
            for key, widget in tab.items():
                if key == "frame":
                    continue
                if isinstance(widget, ParamBlock):
                    pc = widget.physcoef.get_values()
                    cv = widget.curve.get_values()
                    state[f"{tab_name}.{key}.pc"] = (pc["RPM"], pc["Throttle"], pc["PosTorque"], pc["NegTorque"])
                    state[f"{tab_name}.{key}.cv"] = (cv["x0"], cv["y0"], cv["x1"], cv["y1"], cv["x2"], cv["y2"])
                elif isinstance(widget, (tk.IntVar, tk.StringVar)):
                    state[f"{tab_name}.{key}"] = str(widget.get())

        for key, widget in self.global_tab.items():
            if key == "frame":
                continue
            if isinstance(widget, ParamBlock):
                pc = widget.physcoef.get_values()
                cv = widget.curve.get_values()
                state[f"g.{key}.pc"] = (pc["RPM"], pc["Throttle"], pc["PosTorque"], pc["NegTorque"])
                state[f"g.{key}.cv"] = (cv["x0"], cv["y0"], cv["x1"], cv["y1"], cv["x2"], cv["y2"])
            elif isinstance(widget, (tk.IntVar, tk.StringVar)):
                state[f"g.{key}"] = str(widget.get())

        return tuple(sorted(state.items()))

    def _restore_state(self, state):
        """Write a snapshot back to all widgets."""
        self._restoring = True
        d = dict(state)

        self.redline_var.set(d.get("redline", ""))
        self.engine_var.set(d.get("engine", ""))
        self.intake_var.set(d.get("intake_sel", ""))
        self.exhaust_var.set(d.get("exhaust_sel", ""))

        for tab_name, tab in [("int", self.intake_tab), ("eng", self.engine_tab), ("exh", self.exhaust_tab)]:
            for key, widget in tab.items():
                if key == "frame":
                    continue
                if isinstance(widget, ParamBlock):
                    pc_key = f"{tab_name}.{key}.pc"
                    cv_key = f"{tab_name}.{key}.cv"
                    if pc_key in d:
                        widget.physcoef.set_values(*d[pc_key])
                    if cv_key in d:
                        widget.curve.set_values(*d[cv_key])
                    widget._update_flat_mode()
                elif isinstance(widget, tk.IntVar):
                    val = d.get(f"{tab_name}.{key}")
                    if val is not None:
                        widget.set(int(val))
                elif isinstance(widget, tk.StringVar):
                    val = d.get(f"{tab_name}.{key}")
                    if val is not None:
                        widget.set(val)

        for key, widget in self.global_tab.items():
            if key == "frame":
                continue
            if isinstance(widget, ParamBlock):
                pc_key = f"g.{key}.pc"
                cv_key = f"g.{key}.cv"
                if pc_key in d:
                    widget.physcoef.set_values(*d[pc_key])
                if cv_key in d:
                    widget.curve.set_values(*d[cv_key])
                widget._update_flat_mode()
            elif isinstance(widget, tk.IntVar):
                val = d.get(f"g.{key}")
                if val is not None:
                    widget.set(int(val))
            elif isinstance(widget, tk.StringVar):
                val = d.get(f"g.{key}")
                if val is not None:
                    widget.set(val)

        self._restoring = False

    def _on_possible_edit(self, event=None):
        if self.current_tree is None or self._restoring:
            return
        if self._edit_timer:
            self.root.after_cancel(self._edit_timer)
        self._edit_timer = self.root.after(150, self._check_and_push_undo)

    def _check_and_push_undo(self):
        self._edit_timer = None
        current = self._capture_state()
        if self._last_state is not None and current != self._last_state:
            self._undo_stack.append(self._last_state)
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
        self._last_state = current

    def _on_undo(self, event=None):
        if not self._undo_stack or self.current_tree is None:
            return "break"
        current = self._capture_state()
        self._redo_stack.append(current)
        state = self._undo_stack.pop()
        self._restore_state(state)
        self._last_state = state
        self.status_var.set("Undo")
        return "break"

    def _on_redo(self, event=None):
        if not self._redo_stack or self.current_tree is None:
            return "break"
        current = self._capture_state()
        self._undo_stack.append(current)
        state = self._redo_stack.pop()
        self._restore_state(state)
        self._last_state = state
        self.status_var.set("Redo")
        return "break"

    # ---- Save / Export ----

    def _on_save(self):
        if not self.current_car_file or self.current_tree is None:
            messagebox.showwarning("No Car", "Please select a car first.")
            return

        redline = self.redline_var.get().strip()
        if not redline.isdigit():
            messagebox.showerror("Invalid Redline", "Redline RPM must be a number.")
            return

        root = self.current_tree.getroot()

        # Update top-level fields
        settings = root.find("EngineSettings")
        if settings is not None:
            settings.set("audio_rpm_redline", redline)

        # Component selectors
        eng_file = self._get_filename_from_display(self.engine_var.get(), self.engine_ht)
        int_file = self._get_filename_from_display(self.intake_var.get(), self.intake_ht)
        exh_file = self._get_filename_from_display(self.exhaust_var.get(), self.exhaust_ht)

        el = root.find("EngineAmbient/Upgrade")
        if el is not None and eng_file:
            el.set("L0", eng_file)
        el = root.find("EngineIntake/Upgrade")
        if el is not None and int_file:
            for attr in ["L0", "L1", "L2", "L3"]:
                el.set(attr, int_file)
        el = root.find("Exhaust/Upgrade")
        if el is not None and exh_file:
            for attr in ["L0", "L1", "L2", "L3"]:
                el.set(attr, exh_file)

        # Save all emission groups
        self._save_emission_group(root, "EmissionGroup0", self.intake_tab)
        self._save_emission_group(root, "EmissionGroup1", self.engine_tab)
        self._save_emission_group(root, "EmissionGroup2", self.exhaust_tab)

        # Save global effects
        self._save_global_effects(root)

        # Update volume sidecar
        self._save_vol_sidecar(self.current_car_file)

        # Write file to working directory
        path = resolve_et_path(self.current_car_file)
        if path is None:
            os.makedirs(DLC_ET_DIR, exist_ok=True)
            path = os.path.join(DLC_ET_DIR, self.current_car_file)
        write_xml_file(self.current_tree, path)
        self.status_var.set(f"Saved: {self.current_car_file}")

    def _on_export(self):
        """Repackage main game ZIP + copy DLC loose files to mapped or override paths."""
        if not os.path.isfile(BACKUP_ZIP):
            messagebox.showerror("Missing Backup", f"Cannot find:\n{BACKUP_ZIP}")
            return
        if not os.path.isfile(QUICKBMS_EXE):
            messagebox.showerror("Missing QuickBMS", f"Cannot find:\n{QUICKBMS_EXE}")
            return

        output_override = self.output_var.get().strip()
        has_override = bool(output_override) and os.path.isdir(output_override)

        if output_override and not has_override:
            messagebox.showerror("Invalid Override",
                                 f"Override folder does not exist:\n{output_override}")
            return

        if not has_override and not self.mapping_loaded:
            # Backward compatible: no mapping, no override -> use BASE_DIR
            output_override = BASE_DIR
            has_override = True

        self.status_var.set("Exporting: packaging main ZIP...")
        self.root.update()

        try:
            # --- Step 1: Repackage main game enginetuning.zip ---
            shutil.copy2(BACKUP_ZIP, OUTPUT_ZIP)
            self.status_var.set("Exporting: QuickBMS reimport...")
            self.root.update()

            subprocess.run(
                [QUICKBMS_EXE, "-w", "-r", "-r", "-r", ZIP_BMS, OUTPUT_ZIP, ET_DIR],
                capture_output=True, text=True, timeout=120)

            self.status_var.set("Exporting: rebuilding CD...")
            self.root.update()
            file_count = rebuild_zip_central_directory(OUTPUT_ZIP)

            self.status_var.set("Exporting: verifying...")
            self.root.update()
            valid, msg = verify_zip(OUTPUT_ZIP)
            if not valid:
                raise RuntimeError(f"ZIP verification failed: {msg}")

            # Determine ZIP destination
            if has_override:
                dest_zip = os.path.join(output_override, "enginetuning.zip")
            elif self.file_mapping.get("main_et_zip"):
                dest_zip = self.file_mapping["main_et_zip"]
            else:
                dest_zip = os.path.join(BASE_DIR, "enginetuning.zip")

            if os.path.normpath(dest_zip) != os.path.normpath(OUTPUT_ZIP):
                os.makedirs(os.path.dirname(dest_zip), exist_ok=True)
                shutil.copy2(OUTPUT_ZIP, dest_zip)

            # --- Step 2: Copy DLC loose ET files ---
            dlc_copied = 0
            if os.path.isdir(DLC_ET_DIR):
                et_mapping = self.file_mapping.get("et_files", {})
                for fn in os.listdir(DLC_ET_DIR):
                    if not fn.endswith("_ET.xml"):
                        continue
                    src = os.path.join(DLC_ET_DIR, fn)
                    if has_override:
                        dest = os.path.join(output_override, fn)
                    elif fn in et_mapping:
                        dest = os.path.join(et_mapping[fn]["output_dir"], fn)
                    else:
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
                    dlc_copied += 1

            # --- Step 3: Copy loose override ET files ---
            override_copied = 0
            if not has_override:
                et_mapping = self.file_mapping.get("et_files", {})
                for fn, info in et_mapping.items():
                    src = os.path.join(ET_DIR, fn)
                    if os.path.isfile(src):
                        dest = os.path.join(info["output_dir"], fn)
                        if os.path.normpath(src) != os.path.normpath(dest):
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            shutil.copy2(src, dest)
                            override_copied += 1

            total_loose = dlc_copied + override_copied
            self.status_var.set(f"Export complete: {file_count} ZIP files, {total_loose} loose files")
            messagebox.showinfo("Export Complete",
                                f"Main ZIP: {dest_zip}\n{msg}\n"
                                f"DLC files copied: {dlc_copied}\n"
                                f"Override files copied: {override_copied}")

        except subprocess.TimeoutExpired:
            messagebox.showerror("Timeout", "QuickBMS timed out.")
            self.status_var.set("Export failed")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))
            self.status_var.set("Export failed")

    # ---- Backup / Restore ----

    def _on_backup(self):
        if not self.mapping_loaded or not self.file_mapping:
            messagebox.showerror("No Mapping", "Run Find Files first to locate game files.")
            return

        scan_root = self.file_mapping.get("scan_root", "")
        if not scan_root or not os.path.isdir(scan_root):
            messagebox.showerror("Invalid Path", f"Scan root not found: {scan_root}")
            return

        backup_root = os.path.join(scan_root, "backups")
        default_dir = os.path.join(backup_root, "default")

        # Determine backup name
        backup_name = "default"
        if os.path.isdir(default_dir):
            # Default exists - ask user what to do
            choice_win = tk.Toplevel(self.root)
            choice_win.title("Backup Exists")
            win_w, win_h = 350, 130
            root_x = self.root.winfo_x() + (self.root.winfo_width() - win_w) // 2
            root_y = self.root.winfo_y() + (self.root.winfo_height() - win_h) // 2
            choice_win.geometry(f"{win_w}x{win_h}+{root_x}+{root_y}")
            choice_win.resizable(False, False)
            choice_win.transient(self.root)
            choice_win.grab_set()

            ttk.Label(choice_win, text="A default backup already exists.\nWhat would you like to do?",
                      wraplength=320).pack(pady=(10, 8))

            result = {"value": None}
            btn_frame = ttk.Frame(choice_win)
            btn_frame.pack(pady=4)

            def _choose(val):
                result["value"] = val
                choice_win.destroy()

            ttk.Button(btn_frame, text="Overwrite Default", command=lambda: _choose("overwrite")).pack(side=tk.LEFT, padx=4)
            ttk.Button(btn_frame, text="Create New Backup", command=lambda: _choose("new")).pack(side=tk.LEFT, padx=4)
            ttk.Button(btn_frame, text="Cancel", command=lambda: _choose("cancel")).pack(side=tk.LEFT, padx=4)

            self.root.wait_window(choice_win)

            if result["value"] == "cancel" or result["value"] is None:
                return
            elif result["value"] == "new":
                name = simpledialog.askstring("Backup Name", "Enter a name for the backup:",
                                              parent=self.root)
                if not name:
                    return
                backup_name = name.strip().replace(" ", "_")
            # else overwrite default

        backup_dir = os.path.join(backup_root, backup_name)
        os.makedirs(backup_dir, exist_ok=True)

        self.status_var.set("Backing up...")
        self.root.update()

        file_count = 0
        try:
            # Copy main game ZIPs
            main_et_zip = self.file_mapping.get("main_et_zip")
            if main_et_zip and os.path.isfile(main_et_zip):
                shutil.copy2(main_et_zip, os.path.join(backup_dir, "enginetuning.zip"))
                file_count += 1

            main_ht_zip = self.file_mapping.get("main_ht_zip")
            if main_ht_zip and os.path.isfile(main_ht_zip):
                shutil.copy2(main_ht_zip, os.path.join(backup_dir, "harmonictuning.zip"))
                file_count += 1

            # Copy DLC ET files
            et_files = self.file_mapping.get("et_files", {})
            if et_files:
                dlc_et_backup = os.path.join(backup_dir, "dlc_et")
                os.makedirs(dlc_et_backup, exist_ok=True)
                for fn, info in et_files.items():
                    source = info.get("source_path", "")
                    if source and os.path.isfile(source):
                        shutil.copy2(source, os.path.join(dlc_et_backup, fn))
                        file_count += 1

            # Copy DLC HT files
            ht_files = self.file_mapping.get("ht_files", {})
            if ht_files:
                dlc_ht_backup = os.path.join(backup_dir, "dlc_ht")
                os.makedirs(dlc_ht_backup, exist_ok=True)
                for fn, info in ht_files.items():
                    source = info.get("source_path", "")
                    if source and os.path.isfile(source):
                        shutil.copy2(source, os.path.join(dlc_ht_backup, fn))
                        file_count += 1

            # Copy mapping
            shutil.copy2(FILE_MAPPING_PATH, os.path.join(backup_dir, "mapping.json"))

            self.status_var.set(f"Backup complete: {file_count} files to {backup_name}/")
            messagebox.showinfo("Backup Complete",
                                f"Backup saved to:\n{backup_dir}\n\nFiles: {file_count}")

        except Exception as e:
            messagebox.showerror("Backup Failed", str(e))
            self.status_var.set("Backup failed")

    def _on_restore_backup(self):
        if not self.mapping_loaded or not self.file_mapping:
            messagebox.showerror("No Mapping", "Run Find Files first to locate game files.")
            return

        scan_root = self.file_mapping.get("scan_root", "")
        if not scan_root or not os.path.isdir(scan_root):
            messagebox.showerror("Invalid Path", f"Scan root not found: {scan_root}")
            return

        backup_root = os.path.join(scan_root, "backups")
        if not os.path.isdir(backup_root):
            messagebox.showerror("No Backups", f"No backups directory found at:\n{backup_root}")
            return

        # List available backups
        backups = [d for d in os.listdir(backup_root)
                   if os.path.isdir(os.path.join(backup_root, d))]
        if not backups:
            messagebox.showerror("No Backups", "No backup folders found.")
            return

        # Select backup
        if len(backups) == 1:
            selected = backups[0]
        else:
            # Show selection dialog
            sel_win = tk.Toplevel(self.root)
            sel_win.title("Select Backup")
            sel_win.geometry("300x250")
            sel_win.resizable(False, False)
            sel_win.transient(self.root)
            sel_win.grab_set()

            ttk.Label(sel_win, text="Select a backup to restore:").pack(pady=(8, 4))
            lb = tk.Listbox(sel_win, height=8, font=("Consolas", 9))
            lb.pack(fill=tk.BOTH, expand=True, padx=8)
            for b in sorted(backups):
                lb.insert(tk.END, b)

            result = {"value": None}

            def _select():
                s = lb.curselection()
                if s:
                    result["value"] = lb.get(s[0])
                sel_win.destroy()

            ttk.Button(sel_win, text="Restore", command=_select).pack(pady=8)

            self.root.wait_window(sel_win)
            selected = result["value"]
            if not selected:
                return

        backup_dir = os.path.join(backup_root, selected)
        mapping_path = os.path.join(backup_dir, "mapping.json")

        # Read backup mapping
        if os.path.isfile(mapping_path):
            with open(mapping_path, "r") as f:
                backup_mapping = json.load(f)
        else:
            backup_mapping = self.file_mapping

        self.status_var.set("Restoring backup...")
        self.root.update()

        file_count = 0
        try:
            # Restore main ET ZIP
            et_zip_backup = os.path.join(backup_dir, "enginetuning.zip")
            main_et_dest = backup_mapping.get("main_et_zip")
            if os.path.isfile(et_zip_backup) and main_et_dest:
                os.makedirs(os.path.dirname(main_et_dest), exist_ok=True)
                shutil.copy2(et_zip_backup, main_et_dest)
                file_count += 1

            # Restore main HT ZIP
            ht_zip_backup = os.path.join(backup_dir, "harmonictuning.zip")
            main_ht_dest = backup_mapping.get("main_ht_zip")
            if os.path.isfile(ht_zip_backup) and main_ht_dest:
                os.makedirs(os.path.dirname(main_ht_dest), exist_ok=True)
                shutil.copy2(ht_zip_backup, main_ht_dest)
                file_count += 1

            # Restore DLC ET files
            dlc_et_backup = os.path.join(backup_dir, "dlc_et")
            if os.path.isdir(dlc_et_backup):
                et_mapping = backup_mapping.get("et_files", {})
                for fn in os.listdir(dlc_et_backup):
                    src = os.path.join(dlc_et_backup, fn)
                    # Copy to mapped output_dir (game location)
                    if fn in et_mapping:
                        dest = os.path.join(et_mapping[fn]["output_dir"], fn)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.copy2(src, dest)
                        file_count += 1
                    # Also copy to working DLC_ET_DIR
                    os.makedirs(DLC_ET_DIR, exist_ok=True)
                    shutil.copy2(src, os.path.join(DLC_ET_DIR, fn))

            # Restore DLC HT files
            dlc_ht_backup = os.path.join(backup_dir, "dlc_ht")
            if os.path.isdir(dlc_ht_backup):
                ht_mapping = backup_mapping.get("ht_files", {})
                for fn in os.listdir(dlc_ht_backup):
                    src = os.path.join(dlc_ht_backup, fn)
                    # Copy to mapped output_dir (game location)
                    if fn in ht_mapping:
                        dest = os.path.join(ht_mapping[fn]["output_dir"], fn)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.copy2(src, dest)
                        file_count += 1
                    # Also copy to working DLC_HT_DIR
                    os.makedirs(DLC_HT_DIR, exist_ok=True)
                    shutil.copy2(src, os.path.join(DLC_HT_DIR, fn))

            self.status_var.set(f"Restore complete: {file_count} files from {selected}/")
            messagebox.showinfo("Restore Complete",
                                f"Restored from:\n{backup_dir}\n\nFiles: {file_count}\n\n"
                                f"If a car is currently loaded, please re-select it to reload.")

        except Exception as e:
            messagebox.showerror("Restore Failed", str(e))
            self.status_var.set("Restore failed")


def _check_first_run():
    """Check if setup is needed and run it if so. Returns True if app should proceed."""
    import io
    import urllib.request
    import zipfile as zf_mod

    QUICKBMS_URL = "https://aluigi.altervista.org/papers/quickbms.zip"
    quickbms_dir = os.path.join(BASE_DIR, "quickbms")

    quickbms_ok = os.path.isfile(QUICKBMS_EXE)
    zipbms_ok = os.path.isfile(ZIP_BMS)
    et_ok = os.path.isdir(ET_DIR) and any(f.endswith(".xml") for f in os.listdir(ET_DIR)) if os.path.isdir(ET_DIR) else False

    if quickbms_ok and zipbms_ok and et_ok:
        return True  # All good, skip setup

    # Build missing items description
    missing = []
    if not quickbms_ok:
        missing.append("QuickBMS (Xbox 360 ZIP handler)")
    if not zipbms_ok:
        missing.append("zip.bms extraction script")
    if not et_ok:
        missing.append("Extracted game tuning files")

    root = tk.Tk()
    root.withdraw()

    msg = (
        "First-run setup is needed.\n\n"
        "Missing components:\n" +
        "\n".join(f"  - {m}" for m in missing) +
        "\n\nThe tool will now:\n"
        "  1. Download QuickBMS (if needed)\n"
        "  2. Create the zip.bms script (if needed)\n"
        "  3. Ask you to locate your FM4 game files\n\n"
        "Continue with setup?"
    )

    if not messagebox.askyesno("FM4 Car Audio Tuner - Setup Required", msg):
        root.destroy()
        return False

    # Step 1: Download QuickBMS
    if not quickbms_ok:
        try:
            messagebox.showinfo("Downloading", "Downloading QuickBMS...\nThis may take a moment.")
            req = urllib.request.Request(QUICKBMS_URL, headers={
                "User-Agent": "FM4CarAudioTuner-Setup/1.0"
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            os.makedirs(quickbms_dir, exist_ok=True)
            with zf_mod.ZipFile(io.BytesIO(data)) as zfh:
                zfh.extractall(quickbms_dir)
        except Exception as e:
            messagebox.showerror("Download Failed",
                f"Could not download QuickBMS:\n{e}\n\n"
                f"Please manually download from:\n"
                f"https://aluigi.altervista.org/quickbms.htm\n\n"
                f"Extract quickbms.exe into:\n{quickbms_dir}")
            root.destroy()
            return False

    # Step 2: Create zip.bms if missing
    if not zipbms_ok:
        try:
            from setup_fm4tuner import ZIP_BMS_CONTENT
            with open(ZIP_BMS, "w", newline="\n") as f:
                f.write(ZIP_BMS_CONTENT)
        except ImportError:
            # Frozen exe - zip.bms must be shipped alongside or setup_fm4tuner.py run first
            messagebox.showerror("Missing File",
                f"zip.bms not found at:\n{ZIP_BMS}\n\n"
                f"Please place zip.bms in the tool folder.\n"
                f"It is included in the GitHub repository.")
            root.destroy()
            return False

    # Step 3: Locate and extract game ZIPs
    if not et_ok:
        game_root = filedialog.askdirectory(
            title="Select FM4 game root directory (folder containing game files)")
        if not game_root:
            messagebox.showinfo("Skipped",
                "Game file extraction skipped.\n"
                "You can use Find Files in the tuner later.")
            root.destroy()
            return True

        # Search for ZIPs
        et_zip = None
        ht_zip = None
        for dirpath, dirnames, filenames in os.walk(game_root):
            for fn in filenames:
                if fn == "enginetuning.zip":
                    full = os.path.join(dirpath, fn)
                    if et_zip is None or "DVD1" in dirpath:
                        et_zip = full
                elif fn == "harmonictuning.zip":
                    full = os.path.join(dirpath, fn)
                    if ht_zip is None or "DVD1" in dirpath:
                        ht_zip = full

        if et_zip:
            backup_path = os.path.join(BASE_DIR, "enginetuning_backup.zip")
            if not os.path.isfile(backup_path):
                shutil.copy2(et_zip, backup_path)
            os.makedirs(ET_DIR, exist_ok=True)
            subprocess.run([QUICKBMS_EXE, ZIP_BMS, et_zip, ET_DIR],
                           capture_output=True, timeout=300)

        if ht_zip:
            os.makedirs(HT_DIR, exist_ok=True)
            subprocess.run([QUICKBMS_EXE, ZIP_BMS, ht_zip, HT_DIR],
                           capture_output=True, timeout=300)

        # Step 4: Deploy audioengineconfig.xml to game audio folder
        audio_config_src = os.path.join(BASE_DIR, "audioengineconfig.xml")
        if os.path.isfile(audio_config_src):
            # Find the game's Media\audio directory
            audio_dir = None
            for dirpath, dirnames, filenames in os.walk(game_root):
                if "audioengineconfig.xml" in filenames:
                    audio_dir = dirpath
                    break
            if audio_dir:
                shutil.copy2(audio_config_src, os.path.join(audio_dir, "audioengineconfig.xml"))

        et_count = len([f for f in os.listdir(ET_DIR) if f.endswith(".xml")]) if os.path.isdir(ET_DIR) else 0
        ht_count = len([f for f in os.listdir(HT_DIR) if f.endswith(".xml")]) if os.path.isdir(HT_DIR) else 0
        messagebox.showinfo("Setup Complete",
            f"Extraction finished!\n\n"
            f"Engine Tuning files: {et_count}\n"
            f"Harmonic Tuning files: {ht_count}\n"
            f"Audio engine config: installed")

    root.destroy()
    return True


def main():
    if not _check_first_run():
        return
    root = tk.Tk()
    FM4CarAudioTuner(root)
    root.mainloop()


if __name__ == "__main__":
    main()
