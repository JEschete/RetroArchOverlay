from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from ...core.map import (
    map_layer_for_position,
    map_source_point,
    tracked_map_position,
    uses_marker_glyph,
    waypoint_source_point,
)
from ...core.models import (
    MapDocument,
    MapLayer,
    MapOverlay,
    MapPosition,
    MapRegion,
    MapWaypoint,
)


class QtMapImageCache:
    def __init__(self, maximum_entries: int = 4) -> None:
        if maximum_entries <= 0:
            raise ValueError("Qt map image cache size must be positive")
        self.maximum_entries = maximum_entries
        self._entries: OrderedDict[str, QPixmap] = OrderedDict()

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def load(self, layer: MapLayer) -> QPixmap:
        cached = self._entries.pop(layer.key, None)
        if cached is not None:
            self._entries[layer.key] = cached
            return cached
        path = layer.image_loader() if layer.image_loader is not None else layer.image_path
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError(f"Map image could not be loaded: {path}")
        self._entries[layer.key] = pixmap
        while len(self._entries) > self.maximum_entries:
            self._entries.popitem(last=False)
        return pixmap

    def clear(self) -> None:
        self._entries.clear()


class QtMapView(QGraphicsView):
    ZOOM_LEVELS = (1, 2, 4, 8, 16)
    PATH_CHUNK_POINTS = 1024
    PATH_INCREMENT_LIMIT = 128
    OBJECTIVE_FLASH_INTERVAL_MS = 450
    PLAYER_BLINK_INTERVAL_MS = 450
    HIDDEN_OVERLAYS = frozenset(("path", "collectibles", "npcs", "encounters"))

    def __init__(
        self,
        document: MapDocument,
        *,
        image_cache: QtMapImageCache | None = None,
        hero_paths: dict[str, list[tuple[int, int]]] | None = None,
        animate_objectives: bool = True,
        blink_player: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        if not document.layers:
            raise ValueError("Map document must contain at least one layer")
        super().__init__(parent)
        self.document = document
        self.layers = {layer.key: layer for layer in document.layers}
        self._image_cache = image_cache or QtMapImageCache()
        self._map_scene = QGraphicsScene(self)
        self.setScene(self._map_scene)
        self.setAccessibleName(document.title)
        self.setBackgroundBrush(QColor("#050a12"))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._layer_key = document.layers[0].key
        self._position: MapPosition | None = None
        self._indoor_map_id: int | None = None
        self._overlays: dict[str, tuple[MapWaypoint, ...]] = {}
        self._overlay_signature: tuple[MapOverlay, ...] = ()
        self._pixmap: QPixmap | None = None
        self._image_items: list[QGraphicsPixmapItem] = []
        self._static_items: list[QGraphicsItem] = []
        self._overlay_items: list[QGraphicsItem] = []
        self._static_classified_items: list[tuple[QGraphicsItem, str, bool]] = []
        self._overlay_classified_items: list[tuple[QGraphicsItem, str, bool]] = []
        self._materialized_static_kinds: set[str] = set()
        self._player_items: list[QGraphicsEllipseItem] = []
        self._path_items: list[QGraphicsPathItem] = []
        self._path_increment_items: list[QGraphicsItem] = []
        self._path_snapshot: tuple[tuple[int, int], ...] = ()
        self._hero_paths = hero_paths if hero_paths is not None else {}
        available_kinds = (
            set(document.overlay_kinds)
            | {waypoint.kind for layer in document.layers for waypoint in layer.waypoints}
            | {region.kind for layer in document.layers for region in layer.regions}
            | {"player", "path"}
        )
        self._overlay_visibility = {
            kind: kind not in self.HIDDEN_OVERLAYS for kind in available_kinds
        }
        self._hide_completed = False
        self._animate_objectives = animate_objectives
        self._objective_flash_visible = True
        self._objective_timer = QTimer(self)
        self._objective_timer.setInterval(self.OBJECTIVE_FLASH_INTERVAL_MS)
        self._objective_timer.timeout.connect(self._toggle_objective_flash)
        self._blink_player = bool(blink_player)
        self._player_blink_visible = True
        self._player_timer = QTimer(self)
        self._player_timer.setInterval(self.PLAYER_BLINK_INTERVAL_MS)
        self._player_timer.timeout.connect(self._toggle_player_blink)
        self._zoom = 1
        self._static_build_count = 0
        self._dynamic_update_count = 0

    @property
    def layer_key(self) -> str:
        return self._layer_key

    @property
    def current_layer(self) -> MapLayer:
        return self.layers[self._layer_key]

    @property
    def position(self) -> MapPosition | None:
        return self._position

    @property
    def indoor_map_id(self) -> int | None:
        return self._indoor_map_id

    @property
    def zoom(self) -> int:
        return self._zoom

    @property
    def image_cache(self) -> QtMapImageCache:
        return self._image_cache

    @property
    def static_build_count(self) -> int:
        return self._static_build_count

    @property
    def dynamic_update_count(self) -> int:
        return self._dynamic_update_count

    @property
    def image_item_count(self) -> int:
        return len(self._image_items)

    @property
    def player_scene_positions(self) -> tuple[tuple[float, float], ...]:
        return tuple((item.pos().x(), item.pos().y()) for item in self._player_items)

    @property
    def available_overlay_kinds(self) -> tuple[str, ...]:
        preferred = (
            "player",
            "path",
            "objective",
            "entrance",
            "collectibles",
            "npcs",
            "encounters",
        )
        kinds = set(self._overlay_visibility)
        return tuple(kind for kind in preferred if kind in kinds) + tuple(
            sorted(kinds - set(preferred))
        )

    @property
    def overlay_visibility(self) -> dict[str, bool]:
        return dict(self._overlay_visibility)

    @property
    def hide_completed(self) -> bool:
        return self._hide_completed

    @property
    def path_item_count(self) -> int:
        return len(self._path_items) + len(self._path_increment_items)

    @property
    def objective_animation_enabled(self) -> bool:
        return self._animate_objectives

    @property
    def objective_timer_active(self) -> bool:
        return self._objective_timer.isActive()

    @property
    def player_blink_enabled(self) -> bool:
        return self._blink_player

    @property
    def player_timer_active(self) -> bool:
        return self._player_timer.isActive()

    def visible_waypoints(self) -> tuple[MapWaypoint, ...]:
        layer = self.layers[self._layer_key]
        waypoints = layer.waypoints + self._overlays.get(layer.key, ())
        return tuple(
            waypoint
            for waypoint in waypoints
            if self._overlay_visibility.get(waypoint.kind, True)
            and not (self._hide_completed and waypoint.completed)
        )

    def visible_regions(self) -> tuple[MapRegion, ...]:
        layer = self.layers[self._layer_key]
        return tuple(
            region
            for region in layer.regions
            if self._overlay_visibility.get(region.kind, True)
        )

    def set_overlay_visible(self, kind: str, visible: bool) -> bool:
        if kind not in self._overlay_visibility:
            return False
        visible = bool(visible)
        if self._overlay_visibility[kind] == visible:
            return False
        self._overlay_visibility[kind] = visible
        if visible and self._pixmap is not None:
            if kind == "path" and not self._path_items:
                self._rebuild_path_items()
            if kind not in self._materialized_static_kinds:
                self._build_static_items(self.current_layer, {kind})
        if self._pixmap is not None:
            self._rebuild_overlay_items()
        self._apply_item_visibility()
        if kind == "player":
            self._sync_player_timer()
        return True

    def set_hide_completed(self, hidden: bool) -> bool:
        hidden = bool(hidden)
        if hidden == self._hide_completed:
            return False
        self._hide_completed = hidden
        self._apply_item_visibility()
        return True

    def set_hero_paths(self, paths: dict[str, list[tuple[int, int]]]) -> None:
        self._hero_paths = paths
        self._sync_path_items()

    def set_objective_animation(self, enabled: bool) -> None:
        self._animate_objectives = bool(enabled)
        self._objective_flash_visible = True
        self._sync_objective_timer()
        self._apply_item_visibility()

    def set_layer(self, key: str, *, render: bool = True) -> bool:
        if key not in self.layers:
            raise KeyError(key)
        if key == self._layer_key and (self._pixmap is not None or not render):
            return False
        self._layer_key = key
        if render:
            self._rebuild_scene()
        else:
            self._pixmap = None
            self._map_scene.clear()
            self._image_items = []
            self._static_items = []
            self._overlay_items = []
            self._static_classified_items = []
            self._overlay_classified_items = []
            self._player_items = []
            self._path_items = []
            self._path_increment_items = []
            self._path_snapshot = ()
        return True

    def update_map(
        self,
        position: MapPosition,
        overlays: tuple[MapOverlay, ...] = (),
    ) -> None:
        previous = self._position
        previous_layer_key = self._layer_key
        matching = map_layer_for_position(self.document, position)
        self._position = position if matching is not None else tracked_map_position(previous, position)
        self._indoor_map_id = None if position.is_world or matching is not None else position.map_id
        if matching is not None and (
            previous is None
            or previous.area != position.area
            or previous.map_id != position.map_id
        ):
            self._layer_key = matching.key
        overlay_map: dict[str, tuple[MapWaypoint, ...]] = {}
        for overlay in overlays:
            overlay_map[overlay.layer_key] = (
                overlay_map.get(overlay.layer_key, ()) + overlay.waypoints
            )
        overlay_changed = overlays != self._overlay_signature
        self._overlays = overlay_map
        self._overlay_signature = overlays
        if self._pixmap is None or self._layer_key != previous_layer_key:
            self._rebuild_scene()
            return
        if overlay_changed:
            self._rebuild_overlay_items()
        self._update_player_items()
        self._sync_path_items()
        self._apply_item_visibility()
        self._dynamic_update_count += 1

    def set_zoom(self, zoom: int) -> bool:
        if zoom not in self.ZOOM_LEVELS:
            raise ValueError(f"Unsupported map zoom: {zoom}")
        if zoom == self._zoom:
            return False
        self._zoom = zoom
        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
            if zoom > 1
            else QGraphicsView.DragMode.NoDrag
        )
        self._apply_transform(recenter=True)
        return True

    def change_zoom(self, steps: int) -> int:
        index = self.ZOOM_LEVELS.index(self._zoom)
        index = max(0, min(len(self.ZOOM_LEVELS) - 1, index + steps))
        self.set_zoom(self.ZOOM_LEVELS[index])
        return self._zoom

    def recenter(self) -> None:
        self._apply_transform(recenter=True)

    def center_on_waypoint(self, waypoint: MapWaypoint) -> None:
        layer = self.layers[self._layer_key]
        source_x, source_y = waypoint_source_point(waypoint, layer)
        self.centerOn(*self._central_source_point(layer, source_x, source_y))

    def center_on_region(self, region: MapRegion) -> None:
        layer = self.layers[self._layer_key]
        source_x = (
            region.x + layer.offset_x + region.width / 2
        ) * layer.tile_width
        source_y = (
            region.y + layer.offset_y + region.height / 2
        ) * layer.tile_height
        self.centerOn(*self._central_source_point(layer, source_x, source_y))

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta:
            self.change_zoom(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        center = self.mapToScene(self.viewport().rect().center())
        super().resizeEvent(event)
        self._apply_transform(center=center)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_objective_timer()
        self._sync_player_timer()

    def hideEvent(self, event: QHideEvent) -> None:
        self._objective_timer.stop()
        self._player_timer.stop()
        self._player_blink_visible = True
        self._apply_item_visibility()
        super().hideEvent(event)

    def _rebuild_scene(self) -> None:
        layer = self.layers[self._layer_key]
        self._pixmap = self._image_cache.load(layer)
        self._map_scene.clear()
        self._image_items = []
        self._static_items = []
        self._overlay_items = []
        self._static_classified_items = []
        self._overlay_classified_items = []
        self._materialized_static_kinds = set()
        self._player_items = []
        self._path_items = []
        self._path_increment_items = []
        self._path_snapshot = ()
        width = self._pixmap.width()
        height = self._pixmap.height()
        for offset_x, offset_y in _tile_offsets(layer, width, height):
            item = self._map_scene.addPixmap(self._pixmap)
            item.setTransformationMode(Qt.TransformationMode.FastTransformation)
            item.setPos(offset_x, offset_y)
            item.setZValue(0)
            self._image_items.append(item)
        self._map_scene.setSceneRect(_scene_rect(layer, width, height))
        self._build_static_items(layer)
        self._rebuild_overlay_items()
        self._update_player_items()
        self._rebuild_path_items()
        self._apply_item_visibility()
        self._static_build_count += 1
        self._apply_transform(recenter=True)

    def _build_static_items(
        self,
        layer: MapLayer,
        kinds: set[str] | None = None,
    ) -> None:
        assert self._pixmap is not None
        requested = kinds or {
            kind for kind, visible in self._overlay_visibility.items() if visible
        }
        width = self._pixmap.width()
        height = self._pixmap.height()
        for region in layer.regions:
            if region.kind not in requested:
                continue
            source_x = (region.x + layer.offset_x) * layer.tile_width
            source_y = (region.y + layer.offset_y) * layer.tile_height
            region_width = region.width * layer.tile_width
            region_height = region.height * layer.tile_height
            region_fill = QColor(region.color)
            region_fill.setAlpha(64)
            for offset_x, offset_y in _tile_offsets(layer, width, height):
                item = self._map_scene.addRect(
                    source_x + offset_x,
                    source_y + offset_y,
                    region_width,
                    region_height,
                    QPen(QColor(region.color), 1),
                    region_fill,
                )
                item.setToolTip(_tooltip(region.title, region.detail))
                item.setZValue(5)
                self._static_items.append(item)
                self._static_classified_items.append((item, region.kind, False))
                label = region.label or region.compact_label
                if region.kind == "encounters" and label:
                    text = self._map_scene.addSimpleText(label)
                    text.setBrush(QColor("#ffffff"))
                    text.setFlag(
                        QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                    )
                    bounds = text.boundingRect()
                    text.setPos(
                        source_x + offset_x + region_width / 2 - bounds.width() / 2,
                        source_y + offset_y + region_height / 2 - bounds.height() / 2,
                    )
                    text.setToolTip(_tooltip(region.title, region.detail))
                    text.setZValue(6)
                    self._static_items.append(text)
                    self._static_classified_items.append((text, region.kind, False))
        for waypoint in layer.waypoints:
            if waypoint.kind not in requested:
                continue
            items = self._create_waypoint_items(layer, waypoint)
            self._static_items.extend(items)
            self._static_classified_items.extend(
                (item, waypoint.kind, waypoint.completed) for item in items
            )
        self._materialized_static_kinds.update(requested)

    def _rebuild_overlay_items(self) -> None:
        for item in self._overlay_items:
            self._map_scene.removeItem(item)
        self._overlay_items = []
        self._overlay_classified_items = []
        layer = self.layers[self._layer_key]
        for waypoint in self._overlays.get(layer.key, ()):
            if not self._overlay_visibility.get(waypoint.kind, True):
                continue
            items = self._create_waypoint_items(layer, waypoint)
            self._overlay_items.extend(items)
            self._overlay_classified_items.extend(
                (item, waypoint.kind, waypoint.completed) for item in items
            )
        self._sync_objective_timer()
        self._apply_item_visibility()

    def _create_waypoint_items(
        self,
        layer: MapLayer,
        waypoint: MapWaypoint,
    ) -> list[QGraphicsItem]:
        assert self._pixmap is not None
        source_x, source_y = waypoint_source_point(waypoint, layer)
        color = QColor("#767b77" if waypoint.completed else "#bb3e2f")
        items: list[QGraphicsItem] = []
        for offset_x, offset_y in _tile_offsets(
            layer,
            self._pixmap.width(),
            self._pixmap.height(),
        ):
            if waypoint.kind == "objective":
                ring = self._map_scene.addEllipse(
                    -11,
                    -11,
                    22,
                    22,
                    QPen(QColor("#f8c24e"), 3),
                )
                ring.setData(0, "objective-ring")
                ring.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                )
                ring.setPos(source_x + offset_x, source_y + offset_y)
                ring.setToolTip(_tooltip(waypoint.title, waypoint.detail))
                ring.setZValue(11)
                items.append(ring)
                item = self._map_scene.addPolygon(
                    QPolygonF(
                        (
                            QPointF(0, -7),
                            QPointF(7, 0),
                            QPointF(0, 7),
                            QPointF(-7, 0),
                        )
                    ),
                    QPen(QColor("#ffffff"), 2),
                    QColor("#bb3e2f"),
                )
                item.setData(1, "objective")
            elif not uses_marker_glyph(waypoint):
                item = self._map_scene.addEllipse(
                    -4,
                    -4,
                    8,
                    8,
                    QPen(QColor("#ffffff"), 1),
                    QColor(
                        "#16817a"
                        if waypoint.kind == "collectibles"
                        else "#bb3e2f"
                    ),
                )
                item.setData(1, "dot")
            else:
                marker = waypoint.marker or "person"
                marker_color, symbol = {
                    "shop": ("#16817a", "$"),
                    "service": ("#3d6da8", "+"),
                    "quest": ("#d38a17", "!"),
                    "item": ("#f0b429", "*"),
                    "boss": ("#b83232", "X"),
                    "building": ("#7c5cbf", "B"),
                    "person": ("#6b7280", ""),
                }.get(marker, ("#6b7280", ""))
                fill = QColor("#767b77" if waypoint.completed else marker_color)
                if marker == "shop":
                    item = self._map_scene.addPolygon(
                        QPolygonF(
                            (
                                QPointF(0, -6),
                                QPointF(6, 0),
                                QPointF(0, 6),
                                QPointF(-6, 0),
                            )
                        ),
                        QPen(QColor("#ffffff"), 1),
                        fill,
                    )
                    shape = "diamond"
                elif marker in {"quest", "item"}:
                    item = self._map_scene.addPolygon(
                        QPolygonF(
                            (
                                QPointF(0, -6),
                                QPointF(6, 5),
                                QPointF(-6, 5),
                            )
                        ),
                        QPen(QColor("#ffffff"), 1),
                        fill,
                    )
                    shape = "triangle"
                elif marker in {"service", "building"}:
                    item = self._map_scene.addRect(
                        -5,
                        -5,
                        10,
                        10,
                        QPen(QColor("#ffffff"), 1),
                        fill,
                    )
                    shape = "square"
                else:
                    item = self._map_scene.addEllipse(
                        -5,
                        -5,
                        10,
                        10,
                        QPen(QColor("#ffffff"), 1),
                        fill,
                    )
                    shape = "circle"
                item.setData(1, shape)
                item.setData(2, symbol)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            item.setPos(source_x + offset_x, source_y + offset_y)
            item.setToolTip(_tooltip(waypoint.title, waypoint.detail))
            item.setZValue(10)
            items.append(item)
            symbol = str(item.data(2) or "")
            if symbol:
                text = self._map_scene.addSimpleText(symbol)
                text.setBrush(QColor("#ffffff"))
                text.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                )
                bounds = text.boundingRect()
                text.setPos(
                    source_x + offset_x - bounds.width() / 2,
                    source_y + offset_y - bounds.height() / 2,
                )
                text.setToolTip(_tooltip(waypoint.title, waypoint.detail))
                text.setZValue(12)
                text.setData(1, "symbol")
                text.setData(2, symbol)
                items.append(text)
        return items

    def _update_player_items(self) -> None:
        if self._position is None or self._pixmap is None:
            self._remove_player_items()
            return
        layer = self.layers[self._layer_key]
        if self._position.area != layer.area:
            self._remove_player_items()
            return
        source_x, source_y = map_source_point(self._position, layer)
        offsets = _tile_offsets(
            layer,
            self._pixmap.width(),
            self._pixmap.height(),
        )
        if len(self._player_items) != len(offsets):
            self._remove_player_items()
            for _ in offsets:
                item = self._map_scene.addEllipse(
                    -7,
                    -7,
                    14,
                    14,
                    QPen(QColor("#20251f"), 2),
                    QColor("#f8c24e"),
                )
                item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                )
                item.setZValue(20)
                self._player_items.append(item)
        tooltip = f"Player · {self._position.x},{self._position.y}"
        for item, (offset_x, offset_y) in zip(self._player_items, offsets):
            item.setPos(source_x + offset_x, source_y + offset_y)
            item.setToolTip(tooltip)
        self._apply_item_visibility()
        self._sync_player_timer()

    def _remove_player_items(self) -> None:
        for item in self._player_items:
            self._map_scene.removeItem(item)
        self._player_items = []
        self._sync_player_timer()

    def _apply_item_visibility(self) -> None:
        for item, kind, completed in (
            *self._static_classified_items,
            *self._overlay_classified_items,
        ):
            visible = self._overlay_visibility.get(kind, True)
            if completed and self._hide_completed:
                visible = False
            if item.data(0) == "objective-ring" and self._animate_objectives:
                visible = visible and self._objective_flash_visible
            item.setVisible(visible)
        player_visible = self._overlay_visibility.get("player", True)
        if self._blink_player:
            player_visible = player_visible and self._player_blink_visible
        for item in self._player_items:
            item.setVisible(player_visible)
        path_visible = self._overlay_visibility.get("path", True)
        for item in (*self._path_items, *self._path_increment_items):
            item.setVisible(path_visible)

    def _sync_objective_timer(self) -> None:
        has_objective = any(
            item.data(0) == "objective-ring"
            for item, _, _ in (
                *self._static_classified_items,
                *self._overlay_classified_items,
            )
        )
        objective_visible = self._overlay_visibility.get("objective", True)
        if (
            self._animate_objectives
            and objective_visible
            and has_objective
            and self.isVisible()
        ):
            if not self._objective_timer.isActive():
                self._objective_timer.start()
        else:
            self._objective_timer.stop()
            self._objective_flash_visible = True

    def _toggle_objective_flash(self) -> None:
        self._objective_flash_visible = not self._objective_flash_visible
        self._apply_item_visibility()

    def _sync_player_timer(self) -> None:
        should_blink = (
            self._blink_player
            and bool(self._player_items)
            and self._overlay_visibility.get("player", True)
            and self.isVisible()
        )
        if should_blink:
            if not self._player_timer.isActive():
                self._player_timer.start()
            return
        self._player_timer.stop()
        self._player_blink_visible = True

    def _toggle_player_blink(self) -> None:
        self._player_blink_visible = not self._player_blink_visible
        self._apply_item_visibility()

    def _sync_path_items(self) -> None:
        points = tuple(self._hero_paths.get(self._layer_key, ()))
        if points == self._path_snapshot:
            return
        if not self._overlay_visibility.get("path", True):
            self._path_snapshot = points
            return
        previous = self._path_snapshot
        extends = (
            bool(previous)
            and len(points) >= len(previous)
            and points[: len(previous)] == previous
        )
        added = len(points) - len(previous) if extends else len(points)
        if (
            extends
            and added <= self.PATH_INCREMENT_LIMIT
            and self._path_items
            and self._overlay_visibility.get("path", True)
        ):
            self._append_path_segments(previous, points)
            self._path_snapshot = points
            if len(self._path_increment_items) >= self.PATH_INCREMENT_LIMIT:
                self._rebuild_path_items()
            return
        self._path_snapshot = points
        self._rebuild_path_items()

    def _rebuild_path_items(self) -> None:
        for item in (*self._path_items, *self._path_increment_items):
            self._map_scene.removeItem(item)
        self._path_items = []
        self._path_increment_items = []
        points = tuple(self._hero_paths.get(self._layer_key, ()))
        self._path_snapshot = points
        if (
            self._pixmap is None
            or len(points) < 2
            or not self._overlay_visibility.get("path", True)
        ):
            return
        layer = self.layers[self._layer_key]
        width = self._pixmap.width()
        height = self._pixmap.height()
        for run in _path_runs(points, width, height, layer.wraps):
            for start in range(0, len(run) - 1, self.PATH_CHUNK_POINTS - 1):
                chunk = run[start : start + self.PATH_CHUNK_POINTS]
                if len(chunk) < 2:
                    continue
                for offset_x, offset_y in _tile_offsets(layer, width, height):
                    path = QPainterPath(
                        QPointF(chunk[0][0] + offset_x, chunk[0][1] + offset_y)
                    )
                    for point_x, point_y in chunk[1:]:
                        path.lineTo(point_x + offset_x, point_y + offset_y)
                    item = self._map_scene.addPath(path, _path_pen())
                    item.setZValue(7)
                    self._path_items.append(item)
        self._apply_item_visibility()

    def _append_path_segments(
        self,
        previous: tuple[tuple[int, int], ...],
        points: tuple[tuple[int, int], ...],
    ) -> None:
        if self._pixmap is None:
            return
        layer = self.layers[self._layer_key]
        width = self._pixmap.width()
        height = self._pixmap.height()
        start_index = max(1, len(previous))
        for index in range(start_index, len(points)):
            start = points[index - 1]
            end = points[index]
            if layer.wraps and (
                abs(start[0] - end[0]) > width / 2
                or abs(start[1] - end[1]) > height / 2
            ):
                continue
            for offset_x, offset_y in _tile_offsets(layer, width, height):
                item = self._map_scene.addLine(
                    start[0] + offset_x,
                    start[1] + offset_y,
                    end[0] + offset_x,
                    end[1] + offset_y,
                    _path_pen(),
                )
                item.setZValue(7)
                self._path_increment_items.append(item)
        self._apply_item_visibility()

    def _apply_transform(
        self,
        *,
        recenter: bool = False,
        center: QPointF | None = None,
    ) -> None:
        if self._pixmap is None:
            return
        layer = self.layers[self._layer_key]
        base_rect = _base_image_rect(layer, self._pixmap.width(), self._pixmap.height())
        self.resetTransform()
        self.fitInView(base_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.scale(self._zoom, self._zoom)
        if recenter and self._position is not None and self._position.area == layer.area:
            source_x, source_y = map_source_point(self._position, layer)
            if layer.wraps:
                source_x += self._pixmap.width()
                source_y += self._pixmap.height()
            self.centerOn(source_x, source_y)
        elif center is not None:
            self.centerOn(center)

    def _central_source_point(
        self,
        layer: MapLayer,
        source_x: float,
        source_y: float,
    ) -> tuple[float, float]:
        if layer.wraps and self._pixmap is not None:
            source_x += self._pixmap.width()
            source_y += self._pixmap.height()
        return source_x, source_y


def _tile_offsets(
    layer: MapLayer,
    width: int,
    height: int,
) -> tuple[tuple[int, int], ...]:
    if not layer.wraps:
        return ((0, 0),)
    return tuple(
        (horizontal * width, vertical * height)
        for vertical in range(3)
        for horizontal in range(3)
    )


def _scene_rect(layer: MapLayer, width: int, height: int) -> QRectF:
    multiplier = 3 if layer.wraps else 1
    return QRectF(0, 0, width * multiplier, height * multiplier)


def _base_image_rect(layer: MapLayer, width: int, height: int) -> QRectF:
    if layer.wraps:
        return QRectF(width, height, width, height)
    return QRectF(0, 0, width, height)


def _tooltip(title: str, detail: str) -> str:
    return title + (f"\n{detail}" if detail else "")


def _path_runs(
    points: tuple[tuple[int, int], ...],
    width: int,
    height: int,
    wraps: bool,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    if len(points) < 2:
        return ()
    runs = []
    current = [points[0]]
    for point in points[1:]:
        previous = current[-1]
        if wraps and (
            abs(previous[0] - point[0]) > width / 2
            or abs(previous[1] - point[1]) > height / 2
        ):
            if len(current) >= 2:
                runs.append(tuple(current))
            current = [point]
        else:
            current.append(point)
    if len(current) >= 2:
        runs.append(tuple(current))
    return tuple(runs)


def _path_pen() -> QPen:
    pen = QPen(QColor("#2f8f83"), 2)
    pen.setCosmetic(True)
    return pen