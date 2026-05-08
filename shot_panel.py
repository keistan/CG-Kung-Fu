#!/usr/bin/env python3
"""Dark shot panel with editable table and auto-detected render/comp versions."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox


BASE_SHOTS_PATH = Path(r"E:\PROJECTS\DEED\ARS_MAP\SHOTS")
TABLE_STATE_FILE = Path("shot_panel_state.tsv")

SHOT_RE = re.compile(r"^ARS[_-]\d{2}[-_]\d{2}[-_]\d{4}$", re.IGNORECASE)
VERSION_RE = re.compile(r"(?:^|[_\-.])v(?:er)?[_\-.]?(\d+)(?=[_\-.]|$)", re.IGNORECASE)


@dataclass
class ShotRow:
    number: int
    shot: str
    artist: str = ""
    lookdev: str = ""
    chron: str = ""
    clouds: str = ""
    in_transition: str = ""
    out_transition: str = ""
    render_version: str = ""
    comp_version: str = ""


class ShotPanel(tk.Tk):
    columns = (
        "number",
        "shot",
        "artist",
        "lookdev",
        "chron",
        "clouds",
        "in_transition",
        "out_transition",
        "render_version",
        "comp_version",
    )

    headers = {
        "number": "#",
        "shot": "Шот",
        "artist": "Пролет артист",
        "lookdev": "Лукдев",
        "chron": "Хрон",
        "clouds": "Облака",
        "in_transition": "Влет переход",
        "out_transition": "Вылет переход",
        "render_version": "Рендер версия",
        "comp_version": "Комп версия",
    }

    def __init__(self, base_path: Path = BASE_SHOTS_PATH):
        super().__init__()
        self.base_path = base_path
        self.title("ARS Shot Panel")
        self.geometry("1540x840")
        self.configure(bg="#1e1f24")

        self.rows_by_iid: Dict[str, ShotRow] = {}
        self.editor: Optional[tk.Entry] = None
        self.editor_info: Optional[Tuple[str, str]] = None

        self._setup_style()
        self._build_ui()
        self.refresh_rows()

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        bg = "#1e1f24"
        fg = "#d6d9e0"
        header_bg = "#262a34"
        cell_bg = "#20242c"
        selected_bg = "#2f3f5e"
        border = "#2a303c"

        style.configure("Dark.Treeview",
                        background=cell_bg,
                        fieldbackground=cell_bg,
                        foreground=fg,
                        rowheight=36,
                        bordercolor=border,
                        borderwidth=0,
                        font=("Segoe UI", 10))

        style.configure("Dark.Treeview.Heading",
                        background=header_bg,
                        foreground="#b5c0d7",
                        relief="flat",
                        font=("Segoe UI", 10, "bold"))
        style.map("Dark.Treeview",
                  background=[("selected", selected_bg)],
                  foreground=[("selected", "#eef3ff")])
        style.map("Dark.Treeview.Heading",
                  background=[("active", "#2e3442")])

        style.configure("Dark.TButton",
                        background="#2b3447",
                        foreground="#dce5ff",
                        padding=(12, 7),
                        borderwidth=0,
                        relief="flat")
        style.map("Dark.TButton",
                  background=[("active", "#3b4863")])

        self.option_add("*TCombobox*Listbox.background", bg)
        self.option_add("*TCombobox*Listbox.foreground", fg)

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg="#1e1f24")
        top.pack(fill="x", padx=14, pady=(12, 8))

        ttk.Button(top, text="Обновить", style="Dark.TButton", command=self.refresh_rows).pack(side="left")
        ttk.Button(top, text="Сохранить", style="Dark.TButton", command=self.save_state).pack(side="left", padx=8)

        self.path_lbl = tk.Label(top,
                                 text=f"Путь шотов: {self.base_path}",
                                 bg="#1e1f24",
                                 fg="#9dadca",
                                 anchor="w")
        self.path_lbl.pack(side="left", padx=12)

        container = tk.Frame(self, bg="#1e1f24")
        container.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.tree = ttk.Treeview(container, columns=self.columns, show="headings", style="Dark.Treeview")

        widths = {
            "number": 60,
            "shot": 190,
            "artist": 200,
            "lookdev": 120,
            "chron": 110,
            "clouds": 110,
            "in_transition": 140,
            "out_transition": 140,
            "render_version": 220,
            "comp_version": 220,
        }

        for col in self.columns:
            self.tree.heading(col, text=self.headers[col])
            self.tree.column(col, width=widths[col], anchor="w", minwidth=60)

        y_scroll = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-1>", self.on_single_click)

    def discover_shot_dirs(self) -> List[Path]:
        if not self.base_path.exists():
            return []

        dirs = [p for p in self.base_path.iterdir() if p.is_dir() and SHOT_RE.match(p.name)]
        dirs.sort(key=lambda p: p.name)
        return dirs

    def refresh_rows(self) -> None:
        self.close_editor()

        current = self.load_state()
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.rows_by_iid.clear()

        shot_dirs = self.discover_shot_dirs()
        for idx, shot_dir in enumerate(shot_dirs, start=1):
            shot_name = shot_dir.name
            base_values = current.get(shot_name, {})
            render_file, comp_file = self.detect_latest_versions(shot_dir)

            row = ShotRow(
                number=idx,
                shot=shot_name,
                artist=base_values.get("artist", ""),
                lookdev=base_values.get("lookdev", ""),
                chron=base_values.get("chron", ""),
                clouds=base_values.get("clouds", ""),
                in_transition=base_values.get("in_transition", ""),
                out_transition=base_values.get("out_transition", ""),
                render_version=render_file.name if render_file else "",
                comp_version=comp_file.name if comp_file else "",
            )

            iid = self.tree.insert("", "end", values=[getattr(row, c) for c in self.columns])
            self.rows_by_iid[iid] = row

        if not shot_dirs:
            messagebox.showwarning("Нет шотов", f"Не найдено папок шотов по пути:\n{self.base_path}")

    def detect_latest_versions(self, shot_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
        out_dir = shot_dir / "OUT"
        if not out_dir.exists() or not out_dir.is_dir():
            return None, None

        mp4_files = [f for f in out_dir.iterdir() if f.is_file() and f.suffix.lower() == ".mp4"]
        render_files = [f for f in mp4_files if "_render_" in f.name.lower()]
        comp_files = [f for f in mp4_files if "_comped_" in f.name.lower()]

        return self.pick_latest(render_files), self.pick_latest(comp_files)

    @staticmethod
    def pick_latest(files: List[Path]) -> Optional[Path]:
        if not files:
            return None

        def key(path: Path):
            ver_match = VERSION_RE.search(path.stem)
            ver = int(ver_match.group(1)) if ver_match else -1
            mtime = path.stat().st_mtime
            return ver, mtime, path.name.lower()

        return sorted(files, key=key)[-1]

    def on_single_click(self, event: tk.Event) -> None:
        self.close_editor()
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return

        col = self.columns[int(col_id[1:]) - 1]
        row = self.rows_by_iid.get(row_id)
        if not row:
            return

        if col == "shot":
            self.open_path(self.base_path / row.shot)
        elif col in {"render_version", "comp_version"}:
            filename = getattr(row, col)
            if filename:
                self.open_path(self.base_path / row.shot / "OUT" / filename)

    def on_double_click(self, event: tk.Event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return

        col_name = self.columns[int(col_id[1:]) - 1]
        if col_name in {"number", "shot", "render_version", "comp_version"}:
            return

        bbox = self.tree.bbox(row_id, col_id)
        if not bbox:
            return

        x, y, w, h = bbox
        value = self.tree.set(row_id, col_name)
        self.editor = tk.Entry(self.tree, bg="#2a3040", fg="#f0f4ff", relief="flat")
        self.editor.insert(0, value)
        self.editor.select_range(0, tk.END)
        self.editor.focus_set()
        self.editor.place(x=x, y=y, width=w, height=h)
        self.editor.bind("<Return>", lambda _e: self.save_editor(row_id, col_name))
        self.editor.bind("<Escape>", lambda _e: self.close_editor())
        self.editor.bind("<FocusOut>", lambda _e: self.save_editor(row_id, col_name))
        self.editor_info = (row_id, col_name)

    def save_editor(self, row_id: str, col_name: str) -> None:
        if not self.editor:
            return
        new_value = self.editor.get().strip()
        self.tree.set(row_id, col_name, new_value)
        row = self.rows_by_iid.get(row_id)
        if row:
            setattr(row, col_name, new_value)
        self.close_editor()

    def close_editor(self) -> None:
        if self.editor is not None:
            self.editor.destroy()
            self.editor = None
            self.editor_info = None

    def save_state(self) -> None:
        lines = ["\t".join(self.columns)]
        for row in self.rows_by_iid.values():
            data = asdict(row)
            lines.append("\t".join(str(data[c]).replace("\t", " ") for c in self.columns))

        TABLE_STATE_FILE.write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Сохранено", f"Таблица сохранена в {TABLE_STATE_FILE}")

    def load_state(self) -> Dict[str, Dict[str, str]]:
        if not TABLE_STATE_FILE.exists():
            return {}

        lines = TABLE_STATE_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            return {}

        header = lines[0].split("\t")
        result: Dict[str, Dict[str, str]] = {}
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != len(header):
                continue
            row = dict(zip(header, parts))
            shot = row.get("shot", "")
            if shot:
                result[shot] = row
        return result

    @staticmethod
    def open_path(path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Ошибка открытия", f"Не удалось открыть:\n{path}\n\n{exc}")


if __name__ == "__main__":
    app = ShotPanel()
    app.mainloop()
