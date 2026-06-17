#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Професійна десктопна програма для трансформації траєкторій .waypoints
Windows 11 | Tkinter GUI з 2D/3D переглядом

Можливості:
- Парсинг / збереження файлів .waypoints (формат QGC WPL 110)
- Обертання та масштабування траєкторії (від центру або від кінцевої точки)
- Інтерактивне редагування точок прямо у вікні перегляду:
    додавання (подвійний клік по вільному місцю в 2D),
    переміщення (затиснути та перетягнути точку),
    видалення (вибрати точку кліком + кнопка "Видалити" або клавіша Delete)
- Швидкі ракурси перегляду фігури в 3D (зверху / спереду / збоку / ззаду / ізометрія)
- Окреме вікно введення параметрів трансформації (кут, масштаб)
- Повне масштабування інтерфейсу відповідно до розміру екрана та зміни розміру вікна
"""

import math
import copy
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, Canvas


# ──────────────────────────────────────────────────────────────────────────
#  МОДЕЛЬ ДАНИХ
# ──────────────────────────────────────────────────────────────────────────
class WaypointTransformer:
    """Клас для зберігання, трансформації та редагування waypoints."""

    def __init__(self):
        self.waypoints: List[Dict] = []
        self.header = "QGC WPL 110"
        self.original_waypoints: List[Dict] = []

    # ---------- Завантаження / збереження ----------------------------------
    def parse_waypoints(self, file_path: str) -> bool:
        """Парсить файл .waypoints."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if not lines or "QGC WPL 110" not in lines[0]:
                return False

            self.header = lines[0].strip()
            self.waypoints = []

            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue

                parts = line.split('\t') if '\t' in line else line.split()
                if len(parts) >= 11:
                    try:
                        waypoint = {
                            'raw_parts': parts,
                            'id': parts[0],
                            'lat': float(parts[8]),
                            'lon': float(parts[9]),
                            'alt': float(parts[10]) if len(parts) > 10 else 0.0,
                        }
                        self.waypoints.append(waypoint)
                    except (ValueError, IndexError):
                        continue

            self._snapshot_as_baseline()
            return len(self.waypoints) > 0

        except Exception as e:
            print(f"Помилка читання файлу: {e}")
            return False

    def save_waypoints(self, file_path: str) -> bool:
        """Зберігає waypoints у файл."""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.header + '\n')
                for wp in self.waypoints:
                    f.write('\t'.join(wp['raw_parts']) + '\n')
            return True
        except Exception as e:
            print(f"Помилка збереження: {e}")
            return False

    # ---------- Базова лінія (для трансформацій) ---------------------------
    def _snapshot_as_baseline(self):
        """Фіксує поточний стан точок як 'оригінал' для майбутніх трансформацій."""
        self.original_waypoints = [
            {'lat': wp['lat'], 'lon': wp['lon'], 'alt': wp['alt']}
            for wp in self.waypoints
        ]

    def restore_original(self):
        """Відновлює точки до зафіксованого оригіналу (перед застосуванням нової трансформації)."""
        for i, wp in enumerate(self.waypoints):
            if i < len(self.original_waypoints):
                base = self.original_waypoints[i]
                wp['lat'] = base['lat']
                wp['lon'] = base['lon']
                wp['alt'] = base['alt']
                wp['raw_parts'][8] = f"{wp['lat']:.14f}"
                wp['raw_parts'][9] = f"{wp['lon']:.14f}"

    # ---------- Розрахунки ---------------------------------------------------
    def _valid(self) -> List[Dict]:
        return [wp for wp in self.waypoints if wp['lat'] != 0 or wp['lon'] != 0]

    def calculate_center(self) -> Optional[Dict]:
        valid_wps = self._valid()
        if not valid_wps:
            return None
        return {
            'lat': sum(wp['lat'] for wp in valid_wps) / len(valid_wps),
            'lon': sum(wp['lon'] for wp in valid_wps) / len(valid_wps),
        }

    def calculate_end_point(self) -> Optional[Dict]:
        valid_wps = self._valid()
        if not valid_wps:
            return None
        return {'lat': valid_wps[-1]['lat'], 'lon': valid_wps[-1]['lon']}

    def calculate_distance(self) -> float:
        valid_wps = self._valid()
        if len(valid_wps) < 2:
            return 0.0

        total_distance = 0.0
        R = 6371.0

        for i in range(len(valid_wps) - 1):
            lat1, lon1 = math.radians(valid_wps[i]['lat']), math.radians(valid_wps[i]['lon'])
            lat2, lon2 = math.radians(valid_wps[i + 1]['lat']), math.radians(valid_wps[i + 1]['lon'])
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            total_distance += R * 2 * math.asin(math.sqrt(a))

        return total_distance

    # ---------- Трансформації --------------------------------------------
    def rotate_point(self, lat, lon, center_lat, center_lon, angle_degrees):
        lat_to_m = 111000.0
        lon_to_m = 111000.0 * math.cos(math.radians(center_lat))

        dx = (lon - center_lon) * lon_to_m
        dy = (lat - center_lat) * lat_to_m

        angle_rad = math.radians(-angle_degrees)
        cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

        new_dx = dx * cos_a - dy * sin_a
        new_dy = dx * sin_a + dy * cos_a

        return center_lat + new_dy / lat_to_m, center_lon + new_dx / lon_to_m

    def rotate_waypoints(self, angle_degrees: float, rotate_from_end: bool = False) -> bool:
        center = self.calculate_end_point() if rotate_from_end else self.calculate_center()
        if not center or angle_degrees == 0:
            return False

        for wp in self.waypoints:
            if wp['lat'] == 0 and wp['lon'] == 0:
                continue
            new_lat, new_lon = self.rotate_point(wp['lat'], wp['lon'], center['lat'], center['lon'], angle_degrees)
            wp['lat'], wp['lon'] = new_lat, new_lon
            wp['raw_parts'][8] = f"{new_lat:.14f}"
            wp['raw_parts'][9] = f"{new_lon:.14f}"
        return True

    def scale_waypoints(self, scale_factor: float, scale_from_end: bool = False) -> bool:
        if scale_factor <= 0 or scale_factor == 1.0:
            return False

        center = self.calculate_end_point() if scale_from_end else self.calculate_center()
        if not center:
            return False

        lat_to_m = 111000.0
        lon_to_m = 111000.0 * math.cos(math.radians(center['lat']))

        for wp in self.waypoints:
            if wp['lat'] == 0 and wp['lon'] == 0:
                continue
            dx = (wp['lon'] - center['lon']) * lon_to_m
            dy = (wp['lat'] - center['lat']) * lat_to_m

            new_lon = center['lon'] + (dx * scale_factor) / lon_to_m
            new_lat = center['lat'] + (dy * scale_factor) / lat_to_m

            wp['lat'], wp['lon'] = new_lat, new_lon
            wp['raw_parts'][8] = f"{new_lat:.14f}"
            wp['raw_parts'][9] = f"{new_lon:.14f}"
        return True

    # ---------- Редагування точок (додати / перемістити / видалити) -------
    def add_waypoint(self, lat: float, lon: float, alt: Optional[float] = None) -> int:
        """Додає нову точку в кінець маршруту. Повертає її індекс у self.waypoints."""
        if alt is None:
            alt = self.waypoints[-1]['alt'] if self.waypoints else 50.0

        new_id = len(self.waypoints)
        raw_parts = [
            str(new_id), '0', '3', '16',
            '0', '0', '0', '0',
            f"{lat:.14f}", f"{lon:.14f}", f"{alt:.6f}", '1',
        ]
        waypoint = {'raw_parts': raw_parts, 'id': str(new_id), 'lat': lat, 'lon': lon, 'alt': alt}
        self.waypoints.append(waypoint)
        self._renumber()
        self._snapshot_as_baseline()
        return len(self.waypoints) - 1

    def move_waypoint(self, index: int, lat: float, lon: float):
        """Переміщує існуючу точку (миттєво стає новою базовою позицією)."""
        if not (0 <= index < len(self.waypoints)):
            return
        wp = self.waypoints[index]
        wp['lat'], wp['lon'] = lat, lon
        wp['raw_parts'][8] = f"{lat:.14f}"
        wp['raw_parts'][9] = f"{lon:.14f}"
        if index < len(self.original_waypoints):
            self.original_waypoints[index]['lat'] = lat
            self.original_waypoints[index]['lon'] = lon

    def delete_waypoint(self, index: int) -> bool:
        if not (0 <= index < len(self.waypoints)):
            return False
        del self.waypoints[index]
        self._renumber()
        self._snapshot_as_baseline()
        return True

    def _renumber(self):
        for i, wp in enumerate(self.waypoints):
            wp['id'] = str(i)
            wp['raw_parts'][0] = str(i)

    def flatten_to_baseline(self):
        """Фіксує поточний (можливо трансформований) стан як новий оригінал — викликається
        перед входом у режим редагування, щоб слайдери кута/масштабу знову відповідали 0 / 1.0."""
        self._snapshot_as_baseline()

    # ---------- Дані для відображення --------------------------------------
    def get_trajectory_coords(self) -> Tuple[List[float], List[float], List[float], List[int]]:
        """Повертає (lons, lats, alts, indices), де indices — позиція кожної точки в self.waypoints."""
        lons, lats, alts, indices = [], [], [], []
        for i, wp in enumerate(self.waypoints):
            if wp['lat'] != 0 or wp['lon'] != 0:
                lons.append(wp['lon'])
                lats.append(wp['lat'])
                alts.append(wp['alt'])
                indices.append(i)
        return lons, lats, alts, indices


# ──────────────────────────────────────────────────────────────────────────
#  ВІДОБРАЖЕННЯ ТА ІНТЕРАКТИВНІСТЬ (2D / 3D)
# ──────────────────────────────────────────────────────────────────────────
class TrajectoryView:
    """Малює траєкторію на Canvas та обробляє взаємодію мишею (огляд + редагування)."""

    HIT_RADIUS = 10  # px — радіус "захоплення" точки мишею

    def __init__(self, canvas: Canvas, on_change=None):
        self.canvas = canvas
        self.w = max(int(canvas.winfo_width()), 400)
        self.h = max(int(canvas.winfo_height()), 400)

        self.view_3d = False
        self.rotation_x = 30.0
        self.rotation_z = 45.0

        self.on_change_callback = on_change

        # Зворотні викли́ки для редагування (призначаються власником, MainWindow)
        self.on_add_point = None      # fn(lon, lat)
        self.on_move_point = None     # fn(index, lon, lat)
        self.on_delete_point = None   # fn(index)
        self.on_select_point = None   # fn(index_or_None)

        self.edit_mode = False
        self.selected_index: Optional[int] = None
        self._drag_index: Optional[int] = None
        self._dragging_view = False

        # Навігація (спільна для 2D/3D)
        self.pan_offset_x = 0.0
        self.pan_offset_y = 0.0
        self.zoom_scale = 1.0
        self._mouse_start_x = 0
        self._mouse_start_y = 0

        # Кеш для влучення в точку / зворотного перетворення піксель→координата (тільки 2D)
        self._screen_points: List[Tuple[int, int, float]] = []  # (orig_index, x, y)
        self._bounds_2d = None  # dict із межами для pixel_to_coord

        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)   # Windows
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)     # Linux вгору
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)     # Linux вниз
        self.canvas.bind("<Button-3>", self._on_right_click)     # ПКМ — скидання виду
        self.canvas.bind("<Delete>", self._on_delete_key)
        self.canvas.bind("<BackSpace>", self._on_delete_key)
        self.canvas.bind("<Configure>", self._on_resize)

    # ---------- Налаштування режиму -----------------------------------------
    def set_edit_mode(self, enabled: bool):
        self.edit_mode = enabled
        if not enabled:
            self.selected_index = None
        self._notify()

    def set_view_preset(self, rotation_x: float, rotation_z: float):
        self.rotation_x = rotation_x
        self.rotation_z = rotation_z
        self._notify()

    def reset_navigation(self):
        self.pan_offset_x = 0.0
        self.pan_offset_y = 0.0
        self.zoom_scale = 1.0
        self.rotation_x = 30.0
        self.rotation_z = 45.0

    # ---------- Обробники миші ----------------------------------------------
    def _notify(self):
        if self.on_change_callback:
            self.on_change_callback()

    def _on_resize(self, event):
        if event.width > 10 and event.height > 10:
            self.w, self.h = event.width, event.height
            self._notify()

    def _hit_test(self, x, y) -> Optional[int]:
        best_idx, best_dist = None, self.HIT_RADIUS
        for idx, px, py in self._screen_points:
            d = math.hypot(px - x, py - y)
            if d <= best_dist:
                best_dist, best_idx = d, idx
        return best_idx

    def _on_mouse_down(self, event):
        self.canvas.focus_set()
        self._mouse_start_x, self._mouse_start_y = event.x, event.y

        if self.edit_mode and not self.view_3d:
            hit = self._hit_test(event.x, event.y)
            if hit is not None:
                self._drag_index = hit
                self.selected_index = hit
                if self.on_select_point:
                    self.on_select_point(hit)
                self._notify()
                return
            else:
                self.selected_index = None
                if self.on_select_point:
                    self.on_select_point(None)
                self._notify()
                return

        self._dragging_view = True

    def _on_mouse_move(self, event):
        if self.edit_mode and self._drag_index is not None and not self.view_3d:
            lon, lat = self._pixel_to_coord(event.x, event.y)
            if lon is not None and self.on_move_point:
                self.on_move_point(self._drag_index, lon, lat)
            return

        if not self._dragging_view:
            return

        dx = event.x - self._mouse_start_x
        dy = event.y - self._mouse_start_y

        if self.view_3d:
            self.rotation_z = (self.rotation_z + dx) % 360
            self.rotation_x = max(-90, min(90, self.rotation_x + dy))
        else:
            self.pan_offset_x += dx
            self.pan_offset_y += dy

        self._mouse_start_x, self._mouse_start_y = event.x, event.y
        self._notify()

    def _on_mouse_up(self, event):
        self._drag_index = None
        self._dragging_view = False

    def _on_double_click(self, event):
        if self.edit_mode and not self.view_3d and self._hit_test(event.x, event.y) is None:
            lon, lat = self._pixel_to_coord(event.x, event.y)
            if lon is not None and self.on_add_point:
                self.on_add_point(lon, lat)

    def _on_mouse_wheel(self, event):
        if getattr(event, 'num', None) == 5 or getattr(event, 'delta', 0) < 0:
            self.zoom_scale *= 0.9
        else:
            self.zoom_scale *= 1.1
        self.zoom_scale = max(0.3, min(4.0, self.zoom_scale))
        self._notify()

    def _on_right_click(self, event):
        self.reset_navigation()
        self._notify()

    def _on_delete_key(self, event):
        if self.edit_mode and self.selected_index is not None and self.on_delete_point:
            self.on_delete_point(self.selected_index)
            self.selected_index = None

    # ---------- Перетворення координат (тільки для 2D) ----------------------
    def _pixel_to_coord(self, x, y) -> Tuple[Optional[float], Optional[float]]:
        b = self._bounds_2d
        if not b:
            return None, None
        sx = (x - self.w / 2 - self.pan_offset_x) / self.zoom_scale + self.w / 2
        sy = (y - self.h / 2 - self.pan_offset_y) / self.zoom_scale + self.h / 2
        if b['plot_w'] == 0 or b['plot_h'] == 0:
            return None, None
        lon = b['min_lon'] + (sx - b['margin']) / b['plot_w'] * (b['max_lon'] - b['min_lon'])
        lat = b['min_lat'] + (self.h - b['margin'] - sy) / b['plot_h'] * (b['max_lat'] - b['min_lat'])
        return lon, lat

    # ---------- Малювання: 2D -------------------------------------------------
    def draw_2d(self, lons, lats, alts, indices):
        self.canvas.delete("all")
        self._screen_points = []
        self._bounds_2d = None

        if not lons or not lats:
            self.canvas.create_text(self.w // 2, self.h // 2, text="Немає даних",
                                     fill="#888", font=("Arial", 12))
            return

        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        lon_range = (max_lon - min_lon) or 1.0
        lat_range = (max_lat - min_lat) or 1.0
        padding = 0.12

        min_lon -= lon_range * padding
        max_lon += lon_range * padding
        min_lat -= lat_range * padding
        max_lat += lat_range * padding

        margin = 50
        plot_w = self.w - 2 * margin
        plot_h = self.h - 2 * margin
        self._bounds_2d = {
            'min_lon': min_lon, 'max_lon': max_lon,
            'min_lat': min_lat, 'max_lat': max_lat,
            'margin': margin, 'plot_w': plot_w, 'plot_h': plot_h,
        }

        def to_px(lon, lat):
            x = margin + (lon - min_lon) / (max_lon - min_lon) * plot_w
            y = self.h - margin - (lat - min_lat) / (max_lat - min_lat) * plot_h
            x = (x - self.w / 2) * self.zoom_scale + self.w / 2 + self.pan_offset_x
            y = (y - self.h / 2) * self.zoom_scale + self.h / 2 + self.pan_offset_y
            return x, y

        self.canvas.create_rectangle(0, 0, self.w, self.h, fill='#222', outline='')

        for i in range(0, self.w, 60):
            self.canvas.create_line(i, 0, i, self.h, fill='#3a3a3a', dash=(2, 2))
        for i in range(0, self.h, 60):
            self.canvas.create_line(0, i, self.w, i, fill='#3a3a3a', dash=(2, 2))

        for i in range(len(lons) - 1):
            x1, y1 = to_px(lons[i], lats[i])
            x2, y2 = to_px(lons[i + 1], lats[i + 1])
            self.canvas.create_line(x1, y1, x2, y2, fill='#2196f3', width=2.5)

        for i, (lon, lat) in enumerate(zip(lons, lats)):
            x, y = to_px(lon, lat)
            orig_idx = indices[i]
            is_selected = (self.edit_mode and self.selected_index == orig_idx)

            if i == 0:
                self.canvas.create_rectangle(x - 7, y - 7, x + 7, y + 7,
                                              fill='#4caf50', outline='#fff', width=2)
                self.canvas.create_text(x, y - 20, text='START', fill='#4caf50', font=("Arial", 9, "bold"))
            elif i == len(lons) - 1:
                self.canvas.create_polygon(x, y - 8, x - 8, y + 8, x + 8, y + 8,
                                            fill='#f44336', outline='#fff')
                self.canvas.create_text(x, y + 20, text='END', fill='#f44336', font=("Arial", 9, "bold"))
            else:
                self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5,
                                         fill='#4caf50', outline='white', width=1.5)

            if is_selected:
                self.canvas.create_oval(x - 12, y - 12, x + 12, y + 12,
                                         outline='#ffeb3b', width=2)

            if self.edit_mode:
                self.canvas.create_text(x, y - (28 if i in (0, len(lons) - 1) else 14),
                                         text=str(orig_idx), fill='#ffeb3b', font=("Arial", 8, "bold"))

            self._screen_points.append((orig_idx, x, y))

        self.canvas.create_line(margin, margin, margin, self.h - margin, fill='#fff', width=2)
        self.canvas.create_line(margin, self.h - margin, self.w - margin, self.h - margin, fill='#fff', width=2)

        self.canvas.create_text(margin - 30, margin - 10, text=f'{max_lat:.3f}°', fill='#ccc', font=("Arial", 8))
        self.canvas.create_text(margin - 30, self.h - margin + 10, text=f'{min_lat:.3f}°', fill='#ccc', font=("Arial", 8))
        self.canvas.create_text(margin - 10, self.h - margin + 20, text=f'{min_lon:.3f}°', fill='#ccc', font=("Arial", 8))
        self.canvas.create_text(self.w - margin + 10, self.h - margin + 20, text=f'{max_lon:.3f}°', fill='#ccc', font=("Arial", 8))

        self.canvas.create_text(self.w // 2, 18, text='📊 2D Траєкторія (вигляд зверху)',
                                 fill='#fff', font=("Arial", 11, "bold"))

        hint = ('🖱️ Клік — вибрати/перетягнути точку | Подвійний клік — додати | Delete — видалити'
                if self.edit_mode else
                '🖱️ Drag — рух | Колесо — масштаб | ПКМ — скидання')
        self.canvas.create_text(self.w // 2, 38, text=hint, fill='#888', font=("Arial", 8))

    # ---------- Малювання: 3D --------------------------------------------------
    def draw_3d(self, lons, lats, alts, indices):
        self.canvas.delete("all")
        self._screen_points = []
        self._bounds_2d = None

        if not lons or not lats or not alts:
            self.canvas.create_text(self.w // 2, self.h // 2, text="Немає даних",
                                     fill="#888", font=("Arial", 12))
            return

        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        min_alt, max_alt = min(alts), max(alts)

        lon_range = (max_lon - min_lon) or 1.0
        lat_range = (max_lat - min_lat) or 1.0
        alt_range = (max_alt - min_alt) or 1.0

        def to_3d(lon, lat, alt):
            x = (lon - min_lon) / lon_range - 0.5
            y = (lat - min_lat) / lat_range - 0.5
            z = ((alt - min_alt) / alt_range - 0.5) if max_alt != min_alt else 0.0

            rot_x = math.radians(self.rotation_x)
            y_rot = y * math.cos(rot_x) - z * math.sin(rot_x)
            z_rot = y * math.sin(rot_x) + z * math.cos(rot_x)
            y, z = y_rot, z_rot

            rot_z = math.radians(self.rotation_z)
            x_rot = x * math.cos(rot_z) - y * math.sin(rot_z)
            y_rot = x * math.sin(rot_z) + y * math.cos(rot_z)
            x, y = x_rot, y_rot

            screen_x = (x - y) * 150 + self.w / 2
            screen_y = (x + y) * 80 + self.h / 2 - z * 100

            screen_x = (screen_x - self.w / 2) * self.zoom_scale + self.w / 2 + self.pan_offset_x
            screen_y = (screen_y - self.h / 2) * self.zoom_scale + self.h / 2 + self.pan_offset_y
            return screen_x, screen_y

        self.canvas.create_rectangle(0, 0, self.w, self.h, fill='#1a1a1a', outline='')

        origin = to_3d(min_lon, min_lat, min_alt)
        end_x = to_3d(max_lon, min_lat, min_alt)
        end_y = to_3d(min_lon, max_lat, min_alt)
        end_z = to_3d(min_lon, min_lat, max_alt)

        self.canvas.create_line(*origin, *end_x, fill='#f44336', width=2)
        self.canvas.create_text(end_x[0] + 10, end_x[1], text='LON', fill='#f44336', font=("Arial", 9, "bold"))

        self.canvas.create_line(*origin, *end_y, fill='#4caf50', width=2)
        self.canvas.create_text(end_y[0] - 30, end_y[1], text='LAT', fill='#4caf50', font=("Arial", 9, "bold"))

        self.canvas.create_line(*origin, *end_z, fill='#2196f3', width=2)
        self.canvas.create_text(end_z[0], end_z[1] - 10, text='ALT', fill='#2196f3', font=("Arial", 9, "bold"))

        points_3d = [to_3d(lon, lat, alt) for lon, lat, alt in zip(lons, lats, alts)]

        for i in range(len(points_3d) - 1):
            self.canvas.create_line(*points_3d[i], *points_3d[i + 1], fill='#64b5f6', width=2.5)

        for i, (x, y) in enumerate(points_3d):
            if i == 0:
                self.canvas.create_rectangle(x - 7, y - 7, x + 7, y + 7, fill='#4caf50', outline='#fff', width=2)
            elif i == len(points_3d) - 1:
                self.canvas.create_polygon(x, y - 8, x - 8, y + 8, x + 8, y + 8, fill='#f44336', outline='#fff')
            else:
                self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill='#64b5f6', outline='#fff')
            self._screen_points.append((indices[i], x, y))

        self.canvas.create_text(self.w // 2, 18, text='🎯 3D Траєкторія (висота + координати)',
                                 fill='#fff', font=("Arial", 11, "bold"))
        self.canvas.create_text(self.w // 2, 38, text='🖱️ Drag — обертання | Колесо — масштаб | ПКМ — скидання',
                                 fill='#888', font=("Arial", 8))


# ──────────────────────────────────────────────────────────────────────────
#  ОКРЕМЕ ВІКНО ПАРАМЕТРІВ ТРАНСФОРМАЦІЇ (КУТ / МАСШТАБ)
# ──────────────────────────────────────────────────────────────────────────
class TransformDialog(tk.Toplevel):
    """Незалежне вікно для введення кута обертання та коефіцієнта масштабування."""

    def __init__(self, master, angle_var: tk.DoubleVar, scale_var: tk.DoubleVar,
                 rotate_from_var: tk.StringVar, scale_from_var: tk.StringVar,
                 on_change, on_close=None):
        super().__init__(master)
        self.title("⚙️ Параметри трансформації")
        self.configure(bg='#1f1f1f')
        self.resizable(False, False)
        self.transient(master)

        self.angle_var = angle_var
        self.scale_var = scale_var
        self.rotate_from_var = rotate_from_var
        self.scale_from_var = scale_from_var
        self.on_change = on_change
        self.on_close = on_close

        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._build_ui()

        # Розміщення поряд із головним вікном
        master.update_idletasks()
        x = master.winfo_x() + master.winfo_width() // 2 - 190
        y = master.winfo_y() + 80
        self.geometry(f"380x430+{max(x, 0)}+{max(y, 0)}")

    def _build_ui(self):
        pad = dict(padx=12, pady=6)

        # ── Обертання ──────────────────────────────────────────────
        rot_frame = tk.LabelFrame(self, text="🔄 ОБЕРТАННЯ", bg='#2a2a2a', fg='#0078d4',
                                   font=("Arial", 10, "bold"), padx=10, pady=8)
        rot_frame.pack(fill=tk.X, **pad)

        tk.Radiobutton(rot_frame, text="Від центру фігури", variable=self.rotate_from_var,
                        value="center", bg='#2a2a2a', fg='#ccc', selectcolor='#0078d4',
                        activebackground='#2a2a2a', command=self.on_change).pack(anchor=tk.W, pady=2)
        tk.Radiobutton(rot_frame, text="Від кінцевої точки", variable=self.rotate_from_var,
                        value="end", bg='#2a2a2a', fg='#ccc', selectcolor='#0078d4',
                        activebackground='#2a2a2a', command=self.on_change).pack(anchor=tk.W, pady=2)

        angle_row = tk.Frame(rot_frame, bg='#2a2a2a')
        angle_row.pack(fill=tk.X, pady=(8, 2))
        tk.Label(angle_row, text="Кут (°):", bg='#2a2a2a', fg='#ccc', width=9, anchor=tk.W).pack(side=tk.LEFT)
        angle_spin = tk.Spinbox(angle_row, from_=-360, to=360, increment=1,
                                 textvariable=self.angle_var, width=7, bg='#3a3a3a', fg='#fff',
                                 insertbackground='#fff', relief=tk.FLAT,
                                 command=self.on_change)
        angle_spin.pack(side=tk.RIGHT)
        angle_spin.bind("<Return>", lambda e: self.on_change())
        angle_spin.bind("<FocusOut>", lambda e: self.on_change())

        self.angle_scale = tk.Scale(rot_frame, from_=-360, to=360, orient=tk.HORIZONTAL,
                                     variable=self.angle_var, bg='#3a3a3a', fg='#0078d4',
                                     troughcolor='#1a1a1a', highlightthickness=0,
                                     command=lambda v: self.on_change())
        self.angle_scale.pack(fill=tk.X, pady=4)

        # ── Масштабування ──────────────────────────────────────────
        scale_frame = tk.LabelFrame(self, text="📏 МАСШТАБУВАННЯ", bg='#2a2a2a', fg='#0078d4',
                                     font=("Arial", 10, "bold"), padx=10, pady=8)
        scale_frame.pack(fill=tk.X, **pad)

        tk.Radiobutton(scale_frame, text="Від центру фігури", variable=self.scale_from_var,
                        value="center", bg='#2a2a2a', fg='#ccc', selectcolor='#0078d4',
                        activebackground='#2a2a2a', command=self.on_change).pack(anchor=tk.W, pady=2)
        tk.Radiobutton(scale_frame, text="Від кінцевої точки", variable=self.scale_from_var,
                        value="end", bg='#2a2a2a', fg='#ccc', selectcolor='#0078d4',
                        activebackground='#2a2a2a', command=self.on_change).pack(anchor=tk.W, pady=2)

        scale_row = tk.Frame(scale_frame, bg='#2a2a2a')
        scale_row.pack(fill=tk.X, pady=(8, 2))
        tk.Label(scale_row, text="Коеф.:", bg='#2a2a2a', fg='#ccc', width=9, anchor=tk.W).pack(side=tk.LEFT)
        scale_spin = tk.Spinbox(scale_row, from_=0.1, to=5.0, increment=0.1,
                                 textvariable=self.scale_var, width=7, bg='#3a3a3a', fg='#fff',
                                 insertbackground='#fff', relief=tk.FLAT,
                                 command=self.on_change)
        scale_spin.pack(side=tk.RIGHT)
        scale_spin.bind("<Return>", lambda e: self.on_change())
        scale_spin.bind("<FocusOut>", lambda e: self.on_change())

        self.scale_scale = tk.Scale(scale_frame, from_=0.1, to=3.0, resolution=0.1, orient=tk.HORIZONTAL,
                                     variable=self.scale_var, bg='#3a3a3a', fg='#0078d4',
                                     troughcolor='#1a1a1a', highlightthickness=0,
                                     command=lambda v: self.on_change())
        self.scale_scale.pack(fill=tk.X, pady=4)

        # ── Кнопки ─────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg='#1f1f1f')
        btn_frame.pack(fill=tk.X, **pad)

        tk.Button(btn_frame, text="↺ Скинути трансформацію", command=self._reset,
                  bg='#ff9800', fg='white', relief=tk.FLAT, padx=10, pady=8,
                  font=("Arial", 10, "bold"), cursor="hand2").pack(fill=tk.X, pady=3)
        tk.Button(btn_frame, text="Закрити", command=self._handle_close,
                  bg='#3a3a3a', fg='white', relief=tk.FLAT, padx=10, pady=6,
                  font=("Arial", 9)).pack(fill=tk.X, pady=3)

    def _reset(self):
        self.angle_var.set(0)
        self.scale_var.set(1.0)
        self.on_change()

    def _handle_close(self):
        if self.on_close:
            self.on_close()
        self.destroy()


# ──────────────────────────────────────────────────────────────────────────
#  ГОЛОВНЕ ВІКНО
# ──────────────────────────────────────────────────────────────────────────
class MainWindow:

    VIEW_PRESETS = {
        'iso':   ("Ізометрія", 30, 45),
        'top':   ("Зверху", 90, 0),
        'front': ("Спереду", 0, 0),
        'side':  ("Збоку", 0, 90),
        'back':  ("Ззаду", 0, 180),
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🛩️ Waypoints Professional Transformer | Windows 11")

        # ---- Масштабування вікна відповідно до розміру екрана ----
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{int(screen_w * 0.85)}x{int(screen_h * 0.85)}")
        self.root.minsize(960, 600)
        self.root.configure(bg='#1a1a1a')

        self.left_panel_width = max(300, min(380, int(screen_w * 0.22)))

        self.transformer = WaypointTransformer()
        self.file_path: Optional[str] = None
        self.current_view = "2d"
        self.transform_dialog: Optional[TransformDialog] = None

        # Спільні зі службовим вікном трансформацій змінні
        self.angle_var = tk.DoubleVar(value=0)
        self.scale_var = tk.DoubleVar(value=1.0)
        self.rotate_from_var = tk.StringVar(value="center")
        self.scale_from_var = tk.StringVar(value="center")

        self.status_var = tk.StringVar(value="Завантажте файл .waypoints, щоб почати роботу")

        self._build_layout()

    # ─────────────────────────────── ЛЕЙАУТ ────────────────────────────────
    def _build_layout(self):
        main_frame = tk.Frame(self.root, bg='#1a1a1a')
        main_frame.pack(fill=tk.BOTH, expand=True)

        body = tk.Frame(main_frame, bg='#1a1a1a')
        body.pack(fill=tk.BOTH, expand=True)

        left_panel = self._build_left_panel(body)
        left_panel.pack(side=tk.LEFT, fill=tk.Y)
        left_panel.pack_propagate(False)
        left_panel.configure(width=self.left_panel_width)

        right_panel = self._build_right_panel(body)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        status_bar = tk.Label(main_frame, textvariable=self.status_var, bg='#0078d4', fg='white',
                               anchor=tk.W, font=("Arial", 9), padx=10, pady=4)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _section(self, parent, title) -> tk.LabelFrame:
        frame = tk.LabelFrame(parent, text=title, bg='#2a2a2a', fg='#0078d4',
                               font=("Arial", 10, "bold"), padx=10, pady=8)
        frame.pack(fill=tk.X, padx=8, pady=6)
        return frame

    # ---------- Лівий панель -------------------------------------------------
    def _build_left_panel(self, parent) -> tk.Frame:
        panel = tk.Frame(parent, bg='#2a2a2a', relief=tk.RAISED, bd=1)

        title = tk.Label(panel, text="⚙️ ПАНЕЛЬ КЕРУВАННЯ", bg='#0078d4', fg='white',
                          font=("Arial", 12, "bold"), pady=10)
        title.pack(fill=tk.X)

        # Скролована область, бо секцій багато
        scroll_canvas = Canvas(panel, bg='#2a2a2a', highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=scroll_canvas.yview)
        content = tk.Frame(scroll_canvas, bg='#2a2a2a')

        content.bind("<Configure>", lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.create_window((0, 0), window=content, anchor="nw")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _wheel(event):
            delta = -1 if (getattr(event, 'delta', 0) > 0 or getattr(event, 'num', 0) == 4) else 1
            scroll_canvas.yview_scroll(delta, "units")
        scroll_canvas.bind_all("<MouseWheel>", _wheel, add="+")

        self._build_file_section(self._section(content, "📂 ФАЙЛ"))
        self._build_info_section(self._section(content, "📊 ІНФОРМАЦІЯ"))
        self._build_transform_launcher_section(self._section(content, "🔄 ТРАНСФОРМАЦІЯ"))
        self._build_edit_section(self._section(content, "✏️ РЕДАГУВАННЯ ТОЧОК"))
        self._build_table_section(self._section(content, "📋 WAYPOINTS"))
        self._build_action_buttons(content)

        return panel

    def _build_file_section(self, frame):
        self.file_label = tk.Label(frame, text="Виберіть файл", bg='#2a2a2a',
                                    fg='#888', font=("Arial", 9))
        self.file_label.pack(fill=tk.X, pady=5)

        tk.Button(frame, text="📁 Вибрати файл .waypoints", command=self.browse_file,
                  bg='#0078d4', fg='white', relief=tk.FLAT, padx=15, pady=6,
                  font=("Arial", 10, "bold"), cursor="hand2").pack(fill=tk.X, pady=3)

    def _build_info_section(self, frame):
        self.info_text = tk.Label(frame, text="Завантажте файл", bg='#2a2a2a',
                                   fg='#aaa', justify=tk.LEFT, font=("Arial", 9))
        self.info_text.pack(fill=tk.BOTH, expand=True)

    def _build_transform_launcher_section(self, frame):
        tk.Label(frame, text="Кут і масштаб задаються в окремому вікні,\nщоб не захаращувати основний екран.",
                 bg='#2a2a2a', fg='#999', justify=tk.LEFT, font=("Arial", 8)).pack(fill=tk.X, pady=(0, 6))

        tk.Button(frame, text="⚙️ Відкрити параметри трансформації", command=self.open_transform_dialog,
                  bg='#0078d4', fg='white', relief=tk.FLAT, padx=10, pady=8,
                  font=("Arial", 10, "bold"), cursor="hand2").pack(fill=tk.X, pady=3)

        self.transform_summary = tk.Label(frame, text="Кут: 0°   Масштаб: 1.0x",
                                           bg='#2a2a2a', fg='#0078d4', font=("Arial", 9, "bold"))
        self.transform_summary.pack(fill=tk.X, pady=(6, 0))

    def _build_edit_section(self, frame):
        mode_row = tk.Frame(frame, bg='#2a2a2a')
        mode_row.pack(fill=tk.X, pady=(0, 8))

        self.btn_view_mode = tk.Button(mode_row, text="👁️ Перегляд", command=lambda: self.set_edit_mode(False),
                                        relief=tk.SUNKEN, bg='#0078d4', fg='white', padx=8, pady=6,
                                        font=("Arial", 9, "bold"))
        self.btn_view_mode.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        self.btn_edit_mode = tk.Button(mode_row, text="✏️ Редагування", command=lambda: self.set_edit_mode(True),
                                        relief=tk.RAISED, bg='#3a3a3a', fg='#ccc', padx=8, pady=6,
                                        font=("Arial", 9, "bold"))
        self.btn_edit_mode.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        tk.Label(frame,
                 text="У режимі редагування (тільки 2D):\n"
                      "• подвійний клік по вільному місцю — додати точку\n"
                      "• затиснути й тягнути точку — перемістити\n"
                      "• клік по точці + кнопка нижче або Delete — видалити",
                 bg='#2a2a2a', fg='#999', justify=tk.LEFT, font=("Arial", 8)).pack(fill=tk.X, pady=(0, 8))

        self.btn_delete_point = tk.Button(frame, text="🗑️ Видалити вибрану точку",
                                           command=self.delete_selected_point,
                                           bg='#f44336', fg='white', relief=tk.FLAT, padx=8, pady=6,
                                           font=("Arial", 9, "bold"), state=tk.DISABLED, cursor="hand2")
        self.btn_delete_point.pack(fill=tk.X)

    def _build_table_section(self, frame):
        table_frame = tk.Frame(frame, bg='#2a2a2a')
        table_frame.pack(fill=tk.BOTH, expand=True)

        self.table = ttk.Treeview(table_frame, columns=('ID', 'Lat', 'Lon', 'Alt'),
                                   height=8, show='headings')
        for col, w in (('ID', 30), ('Lat', 80), ('Lon', 80), ('Alt', 50)):
            self.table.column(col, width=w, anchor=tk.CENTER)
            self.table.heading(col, text=col)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=vsb.set)

        style = ttk.Style()
        style.configure('Treeview', background='#3a3a3a', foreground='#ccc', fieldbackground='#3a3a3a')
        style.configure('Treeview.Heading', background='#0078d4', foreground='white')

        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.table.bind('<<TreeviewSelect>>', self._on_table_select)

    def _build_action_buttons(self, parent):
        frame = tk.Frame(parent, bg='#2a2a2a')
        frame.pack(fill=tk.X, padx=8, pady=15)

        tk.Button(frame, text="💾 ЗБЕРЕГТИ ЗМІНИ", command=self.save_changes,
                  bg='#4caf50', fg='white', relief=tk.FLAT, padx=10, pady=8,
                  font=("Arial", 10, "bold"), cursor="hand2").pack(fill=tk.X, pady=3)

        tk.Button(frame, text="↺ СКИНУТИ ВСЕ", command=self.reset_all,
                  bg='#ff9800', fg='white', relief=tk.FLAT, padx=10, pady=8,
                  font=("Arial", 10, "bold"), cursor="hand2").pack(fill=tk.X, pady=3)

    # ---------- Права панель (перегляд) --------------------------------------
    def _build_right_panel(self, parent) -> tk.Frame:
        panel = tk.Frame(parent, bg='#2a2a2a', relief=tk.RAISED, bd=1)

        header = tk.Frame(panel, bg='#0078d4')
        header.pack(fill=tk.X)

        tk.Label(header, text="📈 ПЕРЕГЛЯД ТРАЄКТОРІЇ", bg='#0078d4', fg='white',
                 font=("Arial", 11, "bold")).pack(side=tk.LEFT, padx=15, pady=8)

        toggle_frame = tk.Frame(header, bg='#0078d4')
        toggle_frame.pack(side=tk.RIGHT, padx=10, pady=4)

        self.btn_3d = tk.Button(toggle_frame, text="3D", command=lambda: self.toggle_view("3d"),
                                 bg='#3a3a3a', fg='white', relief=tk.FLAT, padx=15, pady=4,
                                 font=("Arial", 9, "bold"))
        self.btn_3d.pack(side=tk.RIGHT, padx=2)

        self.btn_2d = tk.Button(toggle_frame, text="2D", command=lambda: self.toggle_view("2d"),
                                 bg='#2196f3', fg='white', relief=tk.FLAT, padx=15, pady=4,
                                 font=("Arial", 9, "bold"))
        self.btn_2d.pack(side=tk.RIGHT, padx=2)

        # Швидкі ракурси (діють у 3D)
        quick_view_bar = tk.Frame(panel, bg='#222')
        quick_view_bar.pack(fill=tk.X)
        tk.Label(quick_view_bar, text="Швидкий ракурс:", bg='#222', fg='#888',
                 font=("Arial", 8)).pack(side=tk.LEFT, padx=(10, 6), pady=4)
        for key, (label, rx, rz) in self.VIEW_PRESETS.items():
            tk.Button(quick_view_bar, text=label, command=lambda k=key: self.apply_view_preset(k),
                      bg='#3a3a3a', fg='#ccc', relief=tk.FLAT, padx=8, pady=3,
                      font=("Arial", 8, "bold"), cursor="hand2").pack(side=tk.LEFT, padx=2, pady=4)

        canvas_frame = tk.Frame(panel, bg='#2a2a2a')
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = Canvas(canvas_frame, bg='#1a1a1a', highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.view = TrajectoryView(self.canvas, on_change=self.refresh_view)
        self.view.on_add_point = self.handle_add_point
        self.view.on_move_point = self.handle_move_point
        self.view.on_delete_point = self.handle_delete_point
        self.view.on_select_point = self.handle_select_point

        return panel

    # ─────────────────────────────── ДІЇ ────────────────────────────────────
    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Вибрати файл .waypoints",
            filetypes=[("Waypoints", "*.waypoints"), ("Усі файли", "*.*")]
        )
        if not file_path:
            return

        if self.transformer.parse_waypoints(file_path):
            self.file_path = file_path
            self.file_label.config(text=f"✅ {Path(file_path).name}", fg='#4caf50')
            self.angle_var.set(0)
            self.scale_var.set(1.0)
            self.update_info()
            self.update_table()
            self.refresh_view()
            self.status_var.set(f"Завантажено {len(self.transformer.waypoints)} точок із {Path(file_path).name}")
        else:
            messagebox.showerror("Помилка", "Не вдалося розібрати файл!")

    def update_info(self):
        if not self.transformer.waypoints:
            return

        dist = self.transformer.calculate_distance()
        center = self.transformer.calculate_center()
        end = self.transformer.calculate_end_point()
        wp_count = len(self.transformer._valid())

        info = (f"Точок: {wp_count}\nДистанція: {dist:.2f} км\n\n"
                f"Центр:\n{center['lat']:.4f}° {center['lon']:.4f}°\n\n"
                f"Кінець:\n{end['lat']:.4f}° {end['lon']:.4f}°")
        self.info_text.config(text=info, fg='#ccc')

    def update_table(self):
        for item in self.table.get_children():
            self.table.delete(item)
        for i, wp in enumerate(self.transformer.waypoints):
            if wp['lat'] != 0 or wp['lon'] != 0:
                self.table.insert('', 'end', iid=str(i), values=(
                    wp['id'], f"{wp['lat']:.5f}", f"{wp['lon']:.5f}", f"{wp['alt']:.0f}"
                ))

    def _on_table_select(self, event):
        sel = self.table.selection()
        if not sel:
            return
        idx = int(sel[0])
        self.handle_select_point(idx)
        self.view.selected_index = idx
        self.refresh_view()

    # ---------- Трансформація (кут/масштаб) ----------------------------------
    def open_transform_dialog(self):
        if self.transform_dialog is not None and self.transform_dialog.winfo_exists():
            self.transform_dialog.lift()
            self.transform_dialog.focus_set()
            return

        self.transform_dialog = TransformDialog(
            self.root, self.angle_var, self.scale_var,
            self.rotate_from_var, self.scale_from_var,
            on_change=self.on_transform_change,
            on_close=lambda: setattr(self, 'transform_dialog', None),
        )

    def on_transform_change(self):
        if not self.transformer.waypoints:
            return
        if self.view.edit_mode:
            # У режимі редагування трансформації слайдерів вимкнено,
            # щоб не змішувати ручне редагування з обертанням/масштабом.
            self.angle_var.set(0)
            self.scale_var.set(1.0)
            return

        self.transformer.restore_original()

        angle = self.angle_var.get()
        if angle != 0:
            self.transformer.rotate_waypoints(angle, self.rotate_from_var.get() == "end")

        scale = self.scale_var.get()
        if scale != 1.0:
            self.transformer.scale_waypoints(scale, self.scale_from_var.get() == "end")

        self.transform_summary.config(text=f"Кут: {angle:.0f}°   Масштаб: {scale:.1f}x")
        self.update_table()
        self.update_info()
        self.refresh_view()

    # ---------- Перегляд -------------------------------------------------------
    def refresh_view(self):
        lons, lats, alts, indices = self.transformer.get_trajectory_coords()
        self.view.view_3d = (self.current_view == "3d")
        if self.current_view == "2d":
            self.view.draw_2d(lons, lats, alts, indices)
        else:
            self.view.draw_3d(lons, lats, alts, indices)

    def toggle_view(self, view_type):
        self.current_view = view_type
        self.view.view_3d = (view_type == "3d")
        self.btn_2d.configure(bg='#2196f3' if view_type == '2d' else '#3a3a3a')
        self.btn_3d.configure(bg='#2196f3' if view_type == '3d' else '#3a3a3a')
        if view_type == "3d" and self.view.edit_mode:
            self.status_var.set("Редагування точок доступне лише в 2D-режимі")
        self.refresh_view()

    def apply_view_preset(self, key):
        label, rx, rz = self.VIEW_PRESETS[key]
        if self.current_view != "3d":
            self.toggle_view("3d")
        self.view.set_view_preset(rx, rz)
        self.status_var.set(f"Ракурс: {label}")

    # ---------- Режим редагування точок ---------------------------------------
    def set_edit_mode(self, enabled: bool):
        if enabled and self.current_view != "2d":
            self.toggle_view("2d")

        if enabled and (self.angle_var.get() != 0 or self.scale_var.get() != 1.0):
            # Фіксуємо поточну (трансформовану) форму як нову базову лінію,
            # щоб редагування точок не конфліктувало з активним обертанням/масштабом.
            self.transformer.flatten_to_baseline()
            self.angle_var.set(0)
            self.scale_var.set(1.0)
            self.transform_summary.config(text="Кут: 0°   Масштаб: 1.0x")

        self.view.set_edit_mode(enabled)
        self.btn_view_mode.configure(relief=tk.SUNKEN if not enabled else tk.RAISED,
                                      bg='#0078d4' if not enabled else '#3a3a3a',
                                      fg='white' if not enabled else '#ccc')
        self.btn_edit_mode.configure(relief=tk.SUNKEN if enabled else tk.RAISED,
                                      bg='#0078d4' if enabled else '#3a3a3a',
                                      fg='white' if enabled else '#ccc')
        self.btn_delete_point.configure(state=tk.NORMAL if (enabled and self.view.selected_index is not None) else tk.DISABLED)

        self.status_var.set(
            "Режим редагування: подвійний клік — додати, тягнути точку — перемістити, "
            "клік + Delete — видалити" if enabled else "Режим перегляду / навігації"
        )
        self.refresh_view()

    def handle_add_point(self, lon, lat):
        idx = self.transformer.add_waypoint(lat, lon)
        self.update_table()
        self.update_info()
        self.refresh_view()
        self.status_var.set(f"Додано точку #{idx}")

    def handle_move_point(self, index, lon, lat):
        self.transformer.move_waypoint(index, lat, lon)
        self.update_table()
        self.update_info()
        self.refresh_view()

    def handle_delete_point(self, index):
        if self.transformer.delete_waypoint(index):
            self.update_table()
            self.update_info()
            self.view.selected_index = None
            self.btn_delete_point.configure(state=tk.DISABLED)
            self.refresh_view()
            self.status_var.set(f"Точку #{index} видалено")

    def handle_select_point(self, index):
        self.view.selected_index = index
        self.btn_delete_point.configure(state=tk.NORMAL if (self.view.edit_mode and index is not None) else tk.DISABLED)
        if index is not None:
            self.status_var.set(f"Вибрано точку #{index}")
            iid = str(index)
            if self.table.exists(iid):
                self.table.selection_set(iid)
                self.table.see(iid)

    def delete_selected_point(self):
        if self.view.selected_index is not None:
            self.handle_delete_point(self.view.selected_index)

    # ---------- Збереження / скидання -------------------------------------------
    def save_changes(self):
        if not self.transformer.waypoints:
            messagebox.showwarning("Помилка", "Спочатку завантажте файл!")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".waypoints",
            initialfile=f"modified_{Path(self.file_path).name}" if self.file_path else "mission.waypoints",
            filetypes=[("Waypoints", "*.waypoints")]
        )
        if not file_path:
            return

        if self.transformer.save_waypoints(file_path):
            messagebox.showinfo("✅ Успіх", f"Файл збережено:\n{Path(file_path).name}")
            self.status_var.set(f"Збережено: {Path(file_path).name}")
        else:
            messagebox.showerror("Помилка", "Не вдалося зберегти!")

    def reset_all(self):
        self.angle_var.set(0)
        self.scale_var.set(1.0)
        self.on_transform_change()
        self.view.reset_navigation()
        self.refresh_view()
        self.status_var.set("Параметри трансформації та навігації скинуто")


def main():
    root = tk.Tk()
    root.resizable(True, True)
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
