from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal, cast
from uuid import UUID, uuid5

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    model_serializer,
    model_validator,
)

from app.adapters.prototype_object_store import canonical_json_bytes
from app.domain.structured_prototype import (
    PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES,
    PrototypeCommandHistory,
    PrototypeCommandHistoryCheckpoint,
    PrototypeCommandHistoryEntry,
)

DOCUMENT_SCHEMA_VERSION: Literal[1] = 1
COMMAND_CONTRACT_VERSION: Literal[1] = 1
COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION: Literal[1] = 1
JOURNAL_PREFIX_CONTRACT_VERSION: Literal[1] = 1
FLOW_LAYOUT_NODE_LIMIT = 300
FLOW_COORDINATE_LIMIT = 32_768
PROTOTYPE_ENTITY_NAMESPACE = UUID("40a604ef-4769-5b60-9562-9cd0d9bfcbbd")

TECHNICAL_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ROUTE_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)?$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SIGNED_DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$")
FREEFORM_MOVE_EVIDENCE_DECIMAL_TOLERANCE = Decimal("0.0002")


def _camel_alias(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictPrototypeModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
        str_strip_whitespace=False,
    )


class StructuredPrototypeContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("entity ID must be a UUID") from exc
    if str(parsed) != value:
        raise ValueError("entity ID must use canonical lowercase UUID form")
    return value


type EntityId = Annotated[
    str,
    Field(min_length=36, max_length=36, pattern=r"^[0-9a-f-]+$"),
    AfterValidator(_canonical_uuid),
]
type TechnicalKey = Annotated[str, Field(pattern=TECHNICAL_KEY_RE.pattern)]
type Sha256 = Annotated[str, Field(pattern=SHA256_RE.pattern)]


def _non_blank_command_text(value: str) -> str:
    if not value.strip():
        raise ValueError("command text must contain a non-whitespace character")
    return value


type CommandNodeName = Annotated[
    str,
    Field(min_length=1, max_length=80),
    AfterValidator(_non_blank_command_text),
]
type CommandPageTitle = Annotated[
    str,
    Field(min_length=1, max_length=80),
    AfterValidator(_non_blank_command_text),
]


def _canonical_signed_decimal(value: str) -> str:
    if SIGNED_DECIMAL_RE.fullmatch(value) is None:
        raise ValueError("value must use a canonical signed decimal string")
    if value.startswith("-") and Decimal(value) == 0:
        raise ValueError("canonical signed decimal zero must not be negative")
    return value


def _canonical_non_negative_signed_decimal(value: str) -> str:
    _canonical_signed_decimal(value)
    if Decimal(value) < 0:
        raise ValueError("value must use a canonical non-negative decimal string")
    return value


def _canonical_positive_signed_decimal(value: str) -> str:
    _canonical_signed_decimal(value)
    if Decimal(value) <= 0:
        raise ValueError("value must use a canonical positive decimal string")
    return value


type CanonicalSignedDecimal = Annotated[str, AfterValidator(_canonical_signed_decimal)]
type CanonicalNonNegativeDecimal = Annotated[
    str,
    AfterValidator(_canonical_non_negative_signed_decimal),
]
type CanonicalPositiveDecimal = Annotated[
    str,
    AfterValidator(_canonical_positive_signed_decimal),
]


class LengthV1(StrictPrototypeModel):
    unit: Literal["px", "percent", "rem", "auto"]
    value: str | None

    @model_validator(mode="after")
    def validate_value(self) -> LengthV1:
        if self.unit == "auto":
            if self.value is not None:
                raise ValueError("auto length must use a null value")
            return self
        if (
            self.value is None
            or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?", self.value) is None
        ):
            raise ValueError("length value must be a canonical non-negative decimal string")
        numeric = float(self.value)
        if self.unit == "percent" and numeric > 100:
            raise ValueError("percentage length must not exceed 100")
        if self.unit == "px" and numeric > 4096:
            raise ValueError("pixel length must not exceed 4096")
        if self.unit == "rem" and numeric > 256:
            raise ValueError("rem length must not exceed 256")
        return self


class FreeformPositionV1(StrictPrototypeModel):
    x: str
    y: str

    @model_validator(mode="after")
    def validate_coordinates(self) -> FreeformPositionV1:
        for coordinate in (self.x, self.y):
            if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?", coordinate) is None:
                raise ValueError(
                    "freeform position must use canonical non-negative decimal strings"
                )
            if float(coordinate) > 4096:
                raise ValueError("freeform position must not exceed 4096")
        return self


def _validate_freeform_decimal(
    value: str,
    *,
    label: str,
    positive: bool = False,
) -> float:
    if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?", value) is None:
        raise ValueError(f"{label} must use a canonical non-negative decimal string")
    numeric = float(value)
    if numeric > 4096:
        raise ValueError(f"{label} must not exceed 4096")
    if positive and numeric == 0:
        raise ValueError(f"{label} must be positive")
    return numeric


class FreeformGridCommonV1(StrictPrototypeModel):
    id: EntityId
    version: Literal[1]
    visible: bool
    snap_enabled: bool
    origin: FreeformPositionV1


def _validate_freeform_grid_opacity(value: str, label: str) -> None:
    if _validate_freeform_decimal(value, label=label) > 1:
        raise ValueError(f"{label} must not exceed 1")


class SquareFreeformGridParamsV1(StrictPrototypeModel):
    size: str
    color_token_key: TechnicalKey
    opacity: str

    @model_validator(mode="after")
    def validate_values(self) -> SquareFreeformGridParamsV1:
        _validate_freeform_decimal(self.size, label="square grid size", positive=True)
        _validate_freeform_grid_opacity(self.opacity, "square grid opacity")
        return self


class FreeformTrackGridParamsV1(StrictPrototypeModel):
    count: Annotated[int, Field(ge=1, le=24)]
    item_size: str | None
    gutter: str
    margin: str
    alignment: Literal["stretch", "start", "center", "end"]
    color_token_key: TechnicalKey
    opacity: str

    @model_validator(mode="after")
    def validate_values(self) -> FreeformTrackGridParamsV1:
        _validate_freeform_track_grid_values(
            item_size=self.item_size,
            gutter=self.gutter,
            margin=self.margin,
            alignment=self.alignment,
            label="track grid",
        )
        _validate_freeform_grid_opacity(self.opacity, "track grid opacity")
        return self


class SquareFreeformGridV1(FreeformGridCommonV1):
    type: Literal["square"]
    params: SquareFreeformGridParamsV1


class ColumnsFreeformGridV1(FreeformGridCommonV1):
    type: Literal["columns"]
    params: FreeformTrackGridParamsV1


class RowsFreeformGridV1(FreeformGridCommonV1):
    type: Literal["rows"]
    params: FreeformTrackGridParamsV1


def _validate_freeform_track_grid_values(
    *,
    item_size: str | None,
    gutter: str,
    margin: str,
    alignment: Literal["stretch", "start", "center", "end"],
    label: str,
) -> None:
    _validate_freeform_decimal(gutter, label=f"{label} gutter")
    _validate_freeform_decimal(margin, label=f"{label} margin")
    if alignment == "stretch":
        if item_size is not None:
            raise ValueError(f"{label} itemSize must be null for stretch alignment")
        return
    if item_size is None:
        raise ValueError(f"{label} itemSize is required outside stretch alignment")
    _validate_freeform_decimal(item_size, label=f"{label} itemSize", positive=True)


type FreeformGridV1 = Annotated[
    SquareFreeformGridV1 | ColumnsFreeformGridV1 | RowsFreeformGridV1,
    Field(discriminator="type"),
]


class LayoutItemV1(StrictPrototypeModel):
    width: LengthV1
    min_width: LengthV1 | None
    max_width: LengthV1 | None
    height: LengthV1
    min_height: LengthV1 | None
    max_height: LengthV1 | None
    grow: Annotated[int, Field(ge=0, le=12)]
    shrink: Annotated[int, Field(ge=0, le=12)]
    align_self: Literal["auto", "start", "center", "end", "stretch"]
    position: FreeformPositionV1 | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class LayoutItemUpdateV1(StrictPrototypeModel):
    width: LengthV1 | None = None
    min_width: LengthV1 | None = None
    max_width: LengthV1 | None = None
    height: LengthV1 | None = None
    min_height: LengthV1 | None = None
    max_height: LengthV1 | None = None
    grow: Annotated[int | None, Field(ge=0, le=12)] = None
    shrink: Annotated[int | None, Field(ge=0, le=12)] = None
    align_self: Literal["auto", "start", "center", "end", "stretch"] | None = None
    position: FreeformPositionV1 | None = None

    @model_validator(mode="after")
    def require_update(self) -> LayoutItemUpdateV1:
        if not self.model_fields_set:
            raise ValueError("layout update must contain at least one field")
        required_values: dict[str, object | None] = {
            "width": self.width,
            "height": self.height,
            "grow": self.grow,
            "shrink": self.shrink,
            "align_self": self.align_self,
        }
        for field_name in required_values.keys() & self.model_fields_set:
            if required_values[field_name] is None:
                raise ValueError(f"layout update field {field_name} cannot be null")
        return self

    @model_serializer(mode="wrap")
    def serialize_only_explicit_updates(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, object]:
        serialized = cast(dict[str, object], handler(self))
        included_keys = self.model_fields_set | {
            _camel_alias(field_name) for field_name in self.model_fields_set
        }
        return {key: value for key, value in serialized.items() if key in included_keys}


class ResponsiveOverrideV1(StrictPrototypeModel):
    breakpoint: Literal["sm", "md", "lg"]
    layout_item: LayoutItemUpdateV1

    @model_validator(mode="after")
    def refuse_freeform_position(self) -> ResponsiveOverrideV1:
        if "position" in self.layout_item.model_fields_set:
            raise ValueError("responsive layout overrides cannot set freeform position")
        return self


_RESPONSIVE_BREAKPOINT_ORDER = {"sm": 0, "md": 1, "lg": 2}


def _validate_responsive_overrides(overrides: Iterable[ResponsiveOverrideV1]) -> None:
    breakpoints = [item.breakpoint for item in overrides]
    _unique(breakpoints, "responsive breakpoint")
    positions = [_RESPONSIVE_BREAKPOINT_ORDER[breakpoint] for breakpoint in breakpoints]
    if positions != sorted(positions):
        raise ValueError("responsive breakpoints must use canonical sm, md, lg order")


class PaddingV1(StrictPrototypeModel):
    top: Annotated[int, Field(ge=0, le=256)]
    right: Annotated[int, Field(ge=0, le=256)]
    bottom: Annotated[int, Field(ge=0, le=256)]
    left: Annotated[int, Field(ge=0, le=256)]


class GridColumnOverrideV1(StrictPrototypeModel):
    min_width: Annotated[int, Field(ge=320, le=2560)]
    columns: Annotated[int, Field(ge=1, le=12)]


def _validate_grid_column_overrides(min_widths: Iterable[int]) -> None:
    previous: int | None = None
    for min_width in min_widths:
        if previous is not None and min_width <= previous:
            raise ValueError("grid column overrides must use strictly increasing minWidth values")
        previous = min_width


class NodeCommonV1(StrictPrototypeModel):
    id: EntityId
    name: Annotated[str, Field(min_length=1, max_length=80)]
    visibility: Literal["visible", "hidden"]
    layout_item: LayoutItemV1
    responsive: Annotated[list[ResponsiveOverrideV1], Field(max_length=3)]

    @model_validator(mode="after")
    def validate_responsive_overrides(self) -> NodeCommonV1:
        _validate_responsive_overrides(self.responsive)
        return self


class TableColumnV1(StrictPrototypeModel):
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]
    field_id: EntityId | None = None


class TableCellV1(StrictPrototypeModel):
    column_key: TechnicalKey
    value: Annotated[str, Field(max_length=500)]


class TableRowV1(StrictPrototypeModel):
    id: EntityId
    cells: Annotated[list[TableCellV1], Field(max_length=30)]


class StackNodeV1(NodeCommonV1):
    type: Literal["Stack"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=128)]
    align: Literal["start", "center", "end", "stretch"]
    justify: Literal["start", "center", "end", "between"]
    padding: PaddingV1
    children: Annotated[list[UINodeV1], Field(max_length=500)]


class GridNodeV1(NodeCommonV1):
    type: Literal["Grid"]
    columns: Annotated[int, Field(ge=1, le=12)]
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    column_overrides: Annotated[list[GridColumnOverrideV1], Field(max_length=3)]
    children: Annotated[list[UINodeV1], Field(max_length=500)]

    @model_validator(mode="after")
    def validate_column_overrides(self) -> GridNodeV1:
        _validate_grid_column_overrides(item.min_width for item in self.column_overrides)
        return self


class FormNodeV1(NodeCommonV1):
    type: Literal["Form"]
    form_definition_id: EntityId
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    children: Annotated[list[UINodeV1], Field(min_length=1, max_length=200)]


def _validate_freeform_size(layout_item: LayoutItemV1) -> None:
    for field_name, length in (
        ("width", layout_item.width),
        ("height", layout_item.height),
    ):
        if length.unit != "px" or length.value is None or float(length.value) == 0:
            raise ValueError(f"freeform {field_name} must be a non-zero pixel length")


def _freeform_axis_size(layout_item: LayoutItemV1, axis: Literal["x", "y"]) -> float:
    length = layout_item.width if axis == "x" else layout_item.height
    if length.value is None:
        raise AssertionError("validated Freeform axis is missing its pixel length")
    return float(length.value)


def _validate_freeform_grid_geometry(
    grids: Iterable[FreeformGridV1],
    layout_item: LayoutItemV1,
) -> None:
    width = _freeform_axis_size(layout_item, "x")
    height = _freeform_axis_size(layout_item, "y")
    for grid in grids:
        origin_x = float(grid.origin.x)
        origin_y = float(grid.origin.y)
        if origin_x >= width or origin_y >= height:
            raise ValueError(f"freeform grid {grid.id} origin must be inside its Freeform bounds")
        if isinstance(grid, SquareFreeformGridV1):
            size = _validate_freeform_decimal(
                grid.params.size,
                label=f"freeform grid {grid.id} size",
                positive=True,
            )
            if origin_x + size > width or origin_y + size > height:
                raise ValueError(f"freeform grid {grid.id} square geometry exceeds Freeform bounds")
            continue
        axis = "x" if isinstance(grid, ColumnsFreeformGridV1) else "y"
        axis_size = width if axis == "x" else height
        axis_origin = origin_x if axis == "x" else origin_y
        gutter = _validate_freeform_decimal(
            grid.params.gutter,
            label=f"freeform grid {grid.id} gutter",
        )
        margin = _validate_freeform_decimal(
            grid.params.margin,
            label=f"freeform grid {grid.id} margin",
        )
        available = axis_size - axis_origin - 2 * margin - (grid.params.count - 1) * gutter
        if available <= 0:
            raise ValueError(f"freeform grid {grid.id} track geometry exceeds its Freeform axis")
        if grid.params.alignment == "stretch":
            continue
        if grid.params.item_size is None:
            raise AssertionError("validated non-stretch Freeform grid has no item size")
        item_size = _validate_freeform_decimal(
            grid.params.item_size,
            label=f"freeform grid {grid.id} itemSize",
            positive=True,
        )
        if grid.params.count * item_size > available:
            raise ValueError(f"freeform grid {grid.id} track geometry exceeds its Freeform axis")


class FreeformNodeV1(NodeCommonV1):
    type: Literal["Freeform"]
    children: Annotated[list[UINodeV1], Field(max_length=500)]
    grids: Annotated[
        list[FreeformGridV1],
        Field(default_factory=list, max_length=8, exclude_if=lambda value: not value),
    ]

    @model_validator(mode="after")
    def validate_size(self) -> FreeformNodeV1:
        _validate_freeform_size(self.layout_item)
        _validate_freeform_grid_geometry(self.grids, self.layout_item)
        return self


class TextNodeV1(NodeCommonV1):
    type: Literal["Text"]
    content: Annotated[str, Field(max_length=8_000)]
    semantic: Literal["heading", "body", "label", "caption"]
    tone: Literal["default", "muted", "success", "warning", "danger"]


class InputNodeV1(NodeCommonV1):
    type: Literal["Input"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    placeholder: Annotated[str, Field(max_length=240)]
    value: Annotated[str, Field(max_length=8_000)]
    input_type: Literal["text", "number", "email"]
    required: bool
    disabled: bool
    form_definition_id: EntityId | None = None
    form_field_id: EntityId | None = None

    @model_validator(mode="after")
    def validate_form_binding(self) -> InputNodeV1:
        if (self.form_definition_id is None) != (self.form_field_id is None):
            raise ValueError("input form and field bindings must be supplied together")
        return self


class ButtonNodeV1(NodeCommonV1):
    type: Literal["Button"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    variant: Literal["primary", "secondary", "danger", "ghost"]
    size: Literal["small", "medium", "large"]
    disabled: bool
    icon_name: Annotated[str, Field(min_length=1, max_length=80)] | None


class TableNodeV1(NodeCommonV1):
    type: Literal["Table"]
    columns: Annotated[list[TableColumnV1], Field(min_length=1, max_length=30)]
    rows: Annotated[list[TableRowV1], Field(max_length=200)]
    density: Literal["compact", "comfortable"]

    @model_validator(mode="after")
    def validate_table_shape(self) -> TableNodeV1:
        column_keys = _unique((column.key for column in self.columns), "table column key")
        _unique((row.id for row in self.rows), "table row ID")
        for row in self.rows:
            cell_keys = _unique((cell.column_key for cell in row.cells), "table cell column key")
            if cell_keys != column_keys:
                raise ValueError(f"table row {row.id} cells must match the table columns")
        return self


type UINodeV1 = Annotated[
    StackNodeV1
    | GridNodeV1
    | FormNodeV1
    | FreeformNodeV1
    | TextNodeV1
    | InputNodeV1
    | ButtonNodeV1
    | TableNodeV1,
    Field(discriminator="type"),
]

# These models reference the recursive alias above. Complete them before command
# edits use model_copy(), which otherwise leaves Pydantic's mock serializer in place.
StackNodeV1.model_rebuild()
GridNodeV1.model_rebuild()
FormNodeV1.model_rebuild()
FreeformNodeV1.model_rebuild()


class ViewportSettingsV1(StrictPrototypeModel):
    width: Annotated[int, Field(ge=320, le=2560)]
    height: Annotated[int, Field(ge=480, le=2160)]


class PrototypePageV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    title: Annotated[str, Field(min_length=1, max_length=80)]
    route: Annotated[str, Field(pattern=ROUTE_RE.pattern, max_length=240)]
    viewport: ViewportSettingsV1
    root: UINodeV1


class TopbarShellV1(StrictPrototypeModel):
    kind: Literal["topbar"]
    title: Annotated[str, Field(min_length=1, max_length=80)]
    accent_color_token_key: TechnicalKey
    navigation_background_color_token_key: TechnicalKey
    content_background_color_token_key: TechnicalKey
    surface_color_token_key: TechnicalKey


class SidebarShellV1(StrictPrototypeModel):
    kind: Literal["sidebar"]
    title: Annotated[str, Field(min_length=1, max_length=80)]
    accent_color_token_key: TechnicalKey
    navigation_background_color_token_key: TechnicalKey
    content_background_color_token_key: TechnicalKey
    surface_color_token_key: TechnicalKey
    navigation_width: Annotated[int, Field(ge=160, le=400)]
    expanded_min_width: Annotated[int, Field(ge=320, le=2560)]


type PrototypeShellV1 = Annotated[
    SidebarShellV1 | TopbarShellV1,
    Field(discriminator="kind"),
]


class PrototypeSettingsV1(StrictPrototypeModel):
    default_viewport: Literal["desktop", "tablet", "mobile"]
    theme: Literal["light", "dark", "system"]
    shell: PrototypeShellV1


class DesignTokenV1(StrictPrototypeModel):
    key: TechnicalKey
    value: Annotated[str, Field(min_length=1, max_length=120)]


class DesignTokensV1(StrictPrototypeModel):
    colors: Annotated[list[DesignTokenV1], Field(max_length=100)]
    spacing: Annotated[list[DesignTokenV1], Field(max_length=50)]


class ComponentDefinitionV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    root: UINodeV1


class NavigationItemV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]
    target_page_id: EntityId


class NavigationDefinitionV1(StrictPrototypeModel):
    items: Annotated[list[NavigationItemV1], Field(max_length=20)]


class PrototypeFlowV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    rule_id: EntityId
    from_node_id: EntityId
    to_page_id: EntityId | None


class AssetRefV1(StrictPrototypeModel):
    id: EntityId
    content_hash: Sha256
    media_type: Literal["image/png", "image/jpeg", "image/webp", "image/svg+xml"]
    alt: Annotated[str, Field(max_length=240)]


class NullRuntimeValueV1(StrictPrototypeModel):
    type: Literal["null"]


class BooleanRuntimeValueV1(StrictPrototypeModel):
    type: Literal["boolean"]
    value: bool


class IntegerRuntimeValueV1(StrictPrototypeModel):
    type: Literal["integer"]
    value: int


class StringRuntimeValueV1(StrictPrototypeModel):
    type: Literal["string"]
    value: Annotated[str, Field(max_length=8_000)]


class EnumRuntimeValueV1(StrictPrototypeModel):
    type: Literal["enum"]
    value: TechnicalKey


class EntityRefRuntimeValueV1(StrictPrototypeModel):
    type: Literal["entityRef"]
    schema_id: EntityId
    entity_id: EntityId


type RuntimeValueV1 = Annotated[
    NullRuntimeValueV1
    | BooleanRuntimeValueV1
    | IntegerRuntimeValueV1
    | StringRuntimeValueV1
    | EnumRuntimeValueV1
    | EntityRefRuntimeValueV1,
    Field(discriminator="type"),
]


class RuntimeRoleV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]


class RuntimeVariableV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    value_type: Literal["null", "boolean", "integer", "string", "enum", "entityRef"]
    nullable: bool
    entity_schema_id: EntityId | None
    default_value: RuntimeValueV1

    @model_validator(mode="after")
    def validate_entity_schema(self) -> RuntimeVariableV1:
        if self.value_type == "entityRef":
            if self.entity_schema_id is None:
                raise ValueError("runtime entityRef variable requires an entity schema")
        elif self.entity_schema_id is not None:
            raise ValueError("only runtime entityRef variables may declare an entity schema")
        return self


class RuntimeEntityFieldV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    value_type: Literal["null", "boolean", "integer", "string", "enum", "entityRef"]
    nullable: bool


class RuntimeEntitySchemaV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    fields: Annotated[list[RuntimeEntityFieldV1], Field(max_length=100)]


class RuntimeFormFieldV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    value_type: Literal["string", "integer"]
    initial_value: StringRuntimeValueV1 | IntegerRuntimeValueV1
    required: bool
    min_integer: int | None


class RuntimeFormV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    fields: Annotated[list[RuntimeFormFieldV1], Field(max_length=100)]


class LiteralExpressionV1(StrictPrototypeModel):
    kind: Literal["literal"]
    value: RuntimeValueV1


class VariableExpressionV1(StrictPrototypeModel):
    kind: Literal["variable"]
    variable_id: EntityId


class FormFieldExpressionV1(StrictPrototypeModel):
    kind: Literal["formField"]
    form_id: EntityId
    field_id: EntityId


class EventEntityRefExpressionV1(StrictPrototypeModel):
    kind: Literal["eventEntityRef"]


class EntityFieldExpressionV1(StrictPrototypeModel):
    kind: Literal["entityField"]
    entity_ref: VariableExpressionV1 | EventEntityRefExpressionV1
    field_id: EntityId
    fallback: RuntimeValueV1


type RuntimeExpressionV1 = Annotated[
    LiteralExpressionV1
    | VariableExpressionV1
    | FormFieldExpressionV1
    | EventEntityRefExpressionV1
    | EntityFieldExpressionV1,
    Field(discriminator="kind"),
]


class AllPredicateV1(StrictPrototypeModel):
    kind: Literal["all"]
    items: Annotated[list[RuntimePredicateV1], Field(min_length=1, max_length=20)]


class RoleIsPredicateV1(StrictPrototypeModel):
    kind: Literal["roleIs"]
    role_id: EntityId


class FormValidPredicateV1(StrictPrototypeModel):
    kind: Literal["formValid"]
    form_id: EntityId


class ComparePredicateV1(StrictPrototypeModel):
    kind: Literal["compare"]
    operator: Literal["eq", "ne"]
    left: RuntimeExpressionV1
    right: RuntimeExpressionV1


type RuntimePredicateV1 = Annotated[
    AllPredicateV1 | RoleIsPredicateV1 | FormValidPredicateV1 | ComparePredicateV1,
    Field(discriminator="kind"),
]

AllPredicateV1.model_rebuild()


class SetVariableEffectV1(StrictPrototypeModel):
    kind: Literal["setVariable"]
    variable_id: EntityId
    value: RuntimeExpressionV1


class ValidateFormEffectV1(StrictPrototypeModel):
    kind: Literal["validateForm"]
    form_id: EntityId


class RuntimeFieldAssignmentV1(StrictPrototypeModel):
    field_id: EntityId
    value: RuntimeExpressionV1


class CreateEntityEffectV1(StrictPrototypeModel):
    kind: Literal["createEntity"]
    schema_id: EntityId
    result_variable_id: EntityId
    values: Annotated[list[RuntimeFieldAssignmentV1], Field(max_length=100)]


class UpdateEntityEffectV1(StrictPrototypeModel):
    kind: Literal["updateEntity"]
    schema_id: EntityId
    entity_ref: VariableExpressionV1 | EventEntityRefExpressionV1
    updates: Annotated[list[RuntimeFieldAssignmentV1], Field(min_length=1, max_length=100)]


class NavigateEffectV1(StrictPrototypeModel):
    kind: Literal["navigate"]
    target_page_id: EntityId


class NotifyEffectV1(StrictPrototypeModel):
    kind: Literal["notify"]
    level: Literal["info", "success", "warning", "error"]
    message: Annotated[str, Field(min_length=1, max_length=240)]


type RuntimeEffectV1 = Annotated[
    SetVariableEffectV1
    | ValidateFormEffectV1
    | CreateEntityEffectV1
    | UpdateEntityEffectV1
    | NavigateEffectV1
    | NotifyEffectV1,
    Field(discriminator="kind"),
]


class RuntimeTriggerV1(StrictPrototypeModel):
    kind: Literal["nodeEvent"]
    node_id: EntityId
    event: Literal["click", "submit", "rowActivated"]


class RuntimeRuleV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    enabled: bool
    trigger: RuntimeTriggerV1
    guard: RuntimePredicateV1 | None
    effects: Annotated[list[RuntimeEffectV1], Field(min_length=1, max_length=100)]
    guard_false_effects: Annotated[list[RuntimeEffectV1], Field(max_length=100)]


class RuntimeRuleDefinitionV1(StrictPrototypeModel):
    key: TechnicalKey
    enabled: bool
    trigger: RuntimeTriggerV1
    guard: RuntimePredicateV1 | None
    effects: Annotated[list[RuntimeEffectV1], Field(min_length=1, max_length=100)]
    guard_false_effects: Annotated[list[RuntimeEffectV1], Field(max_length=100)]


class TextViewBindingV1(StrictPrototypeModel):
    id: EntityId
    node_id: EntityId
    target: Literal["textContent"]
    value: RuntimeExpressionV1


class VisibilityViewBindingV1(StrictPrototypeModel):
    id: EntityId
    node_id: EntityId
    target: Literal["visibility"]
    predicate: RuntimePredicateV1


class TableRowsViewBindingV1(StrictPrototypeModel):
    id: EntityId
    node_id: EntityId
    target: Literal["tableRows"]
    schema_id: EntityId
    sort_field_id: EntityId | None
    sort_direction: Literal["asc", "desc"]


type RuntimeViewBindingV1 = Annotated[
    TextViewBindingV1 | VisibilityViewBindingV1 | TableRowsViewBindingV1,
    Field(discriminator="target"),
]


class RuntimeVariableValueV1(StrictPrototypeModel):
    variable_id: EntityId
    value: RuntimeValueV1


class RuntimeFieldValueV1(StrictPrototypeModel):
    field_id: EntityId
    value: RuntimeValueV1


class RuntimeEntityV1(StrictPrototypeModel):
    id: EntityId
    schema_id: EntityId
    fields: Annotated[list[RuntimeFieldValueV1], Field(max_length=100)]


class RuntimeEntitySetV1(StrictPrototypeModel):
    schema_id: EntityId
    entities: Annotated[list[RuntimeEntityV1], Field(max_length=200)]


class RuntimeScenarioV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    actor_role_id: EntityId
    start_page_id: EntityId
    initial_variables: Annotated[list[RuntimeVariableValueV1], Field(max_length=100)]
    entity_fixtures: Annotated[list[RuntimeEntitySetV1], Field(max_length=50)]
    allow_simulated_role_switch: bool


class RuntimeFlowNodePositionV1(StrictPrototypeModel):
    node_id: EntityId
    x: Annotated[int, Field(ge=-FLOW_COORDINATE_LIMIT, le=FLOW_COORDINATE_LIMIT)]
    y: Annotated[int, Field(ge=-FLOW_COORDINATE_LIMIT, le=FLOW_COORDINATE_LIMIT)]


class RuntimeFlowLayoutV1(StrictPrototypeModel):
    nodes: Annotated[
        list[RuntimeFlowNodePositionV1],
        Field(max_length=FLOW_LAYOUT_NODE_LIMIT),
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_canonical_node_order(self) -> RuntimeFlowLayoutV1:
        node_ids = [node.node_id for node in self.nodes]
        _unique(node_ids, "runtime flow layout node ID")
        if node_ids != sorted(node_ids):
            raise ValueError("runtime flow layout nodes must use canonical nodeId order")
        return self


class RuntimeDefinitionV1(StrictPrototypeModel):
    runtime_schema_version: Literal[1]
    page_ids: Annotated[list[EntityId], Field(min_length=1, max_length=20)]
    roles: Annotated[list[RuntimeRoleV1], Field(min_length=1, max_length=20)]
    variables: Annotated[list[RuntimeVariableV1], Field(max_length=100)]
    entity_schemas: Annotated[list[RuntimeEntitySchemaV1], Field(max_length=50)]
    forms: Annotated[list[RuntimeFormV1], Field(max_length=50)]
    view_bindings: Annotated[list[RuntimeViewBindingV1], Field(max_length=200)]
    rules: Annotated[list[RuntimeRuleV1], Field(max_length=100)]
    scenarios: Annotated[list[RuntimeScenarioV1], Field(min_length=1, max_length=20)]
    flow_layout: RuntimeFlowLayoutV1 | None = Field(
        default=None,
        exclude_if=lambda value: value is None or not value.nodes,
    )


class PrototypeDocumentV1(StrictPrototypeModel):
    schema_version: Literal[1]
    id: EntityId
    title: Annotated[str, Field(min_length=1, max_length=120)]
    locale: Literal["zh-CN", "en-US"]
    settings: PrototypeSettingsV1
    tokens: DesignTokensV1
    component_definitions: Annotated[list[ComponentDefinitionV1], Field(max_length=50)]
    pages: Annotated[list[PrototypePageV1], Field(min_length=1, max_length=20)]
    navigation: NavigationDefinitionV1
    flows: Annotated[list[PrototypeFlowV1], Field(max_length=100)]
    runtime: RuntimeDefinitionV1
    asset_refs: Annotated[list[AssetRefV1], Field(max_length=200)]

    @model_validator(mode="after")
    def validate_document_graph(self) -> PrototypeDocumentV1:
        color_token_keys = {token.key for token in self.tokens.colors}
        shell = self.settings.shell
        shell_color_token_keys = {
            shell.accent_color_token_key,
            shell.navigation_background_color_token_key,
            shell.content_background_color_token_key,
            shell.surface_color_token_key,
        }
        missing_shell_color_token_keys = shell_color_token_keys - color_token_keys
        if missing_shell_color_token_keys:
            missing = ", ".join(sorted(missing_shell_color_token_keys))
            raise ValueError(f"prototype shell references unknown color token keys: {missing}")
        page_ids = _unique((page.id for page in self.pages), "page ID")
        _unique((page.key for page in self.pages), "page key")
        _unique((page.route for page in self.pages), "page route")
        nodes_by_id: dict[str, UINodeV1] = {}
        form_submit_button_ids: set[str] = set()
        for page in self.pages:
            _validate_layout_tree(page.root)
            _collect_nodes(page.root, nodes_by_id)
            _collect_form_submit_button_ids(page.root, form_submit_button_ids)
        for definition in self.component_definitions:
            _validate_layout_tree(definition.root)
            _collect_nodes(definition.root, nodes_by_id)
            _collect_form_submit_button_ids(definition.root, form_submit_button_ids)
        node_ids = set(nodes_by_id)
        freeform_grid_ids = _validate_freeform_grid_references(nodes_by_id, color_token_keys)
        _unique((item.id for item in self.navigation.items), "navigation item ID")
        _unique((item.key for item in self.navigation.items), "navigation item key")
        for item in self.navigation.items:
            if item.target_page_id not in page_ids:
                raise ValueError(f"navigation item {item.id} references an unknown page")
        if self.runtime.page_ids != [page.id for page in self.pages]:
            raise ValueError("runtime page IDs must match document page order exactly")
        _unique((form.id for form in self.runtime.forms), "runtime form ID")
        forms_by_id = {form.id: form for form in self.runtime.forms}
        _unique((rule.id for rule in self.runtime.rules), "runtime rule ID")
        rules_by_id = {rule.id: rule for rule in self.runtime.rules}
        _validate_runtime_semantics(
            self.runtime,
            page_ids=page_ids,
            nodes_by_id=nodes_by_id,
            form_submit_button_ids=form_submit_button_ids,
        )
        _validate_runtime_flow_layout(self.runtime, page_ids)
        _validate_table_view_bindings(self.runtime, nodes_by_id)
        for page in self.pages:
            _validate_node_references(page.root, forms_by_id)
        for definition in self.component_definitions:
            _validate_node_references(definition.root, forms_by_id)
        _validate_rule_flow_projections(
            self.flows,
            rules_by_id=rules_by_id,
            page_ids=page_ids,
            node_ids=node_ids,
        )
        entity_ids = [self.id]
        entity_ids.extend(page_ids)
        entity_ids.extend(node_ids)
        entity_ids.extend(freeform_grid_ids)
        entity_ids.extend(_table_row_ids(self))
        entity_ids.extend(definition.id for definition in self.component_definitions)
        entity_ids.extend(item.id for item in self.navigation.items)
        entity_ids.extend(flow.id for flow in self.flows)
        entity_ids.extend(asset.id for asset in self.asset_refs)
        entity_ids.extend(_runtime_entity_ids(self.runtime))
        _unique(entity_ids, "entity ID")
        return self


class NewPrototypeDocumentV1(StrictPrototypeModel):
    schema_version: Literal[1]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    locale: Literal["zh-CN", "en-US"]
    settings: PrototypeSettingsV1
    tokens: DesignTokensV1
    component_definitions: Annotated[list[ComponentDefinitionV1], Field(max_length=50)]
    pages: Annotated[list[PrototypePageV1], Field(min_length=1, max_length=20)]
    navigation: NavigationDefinitionV1
    flows: Annotated[list[PrototypeFlowV1], Field(max_length=100)]
    runtime: RuntimeDefinitionV1
    asset_refs: Annotated[list[AssetRefV1], Field(max_length=200)]

    def materialize(self, document_id: str) -> PrototypeDocumentV1:
        payload = self.model_dump(mode="json", by_alias=True)
        payload["id"] = document_id
        return PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def _unique(values: Iterable[str], label: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
    return seen


def _rule_navigate_targets(rule: RuntimeRuleV1) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for effect in (*rule.effects, *rule.guard_false_effects):
        if isinstance(effect, NavigateEffectV1) and effect.target_page_id not in seen:
            seen.add(effect.target_page_id)
            targets.append(effect.target_page_id)
    return targets


def _validate_rule_flow_projections(
    flows: list[PrototypeFlowV1],
    *,
    rules_by_id: dict[str, RuntimeRuleV1],
    page_ids: set[str],
    node_ids: set[str],
) -> None:
    _unique((flow.key for flow in flows), "flow key")
    _unique(
        (f"{flow.rule_id}:{flow.to_page_id}" for flow in flows),
        "runtime rule flow target",
    )
    flows_by_rule: dict[str, list[PrototypeFlowV1]] = {}
    for flow in flows:
        rule = rules_by_id.get(flow.rule_id)
        if rule is None or flow.from_node_id not in node_ids:
            raise ValueError(f"flow {flow.id} references an unknown rule or node")
        if flow.from_node_id != rule.trigger.node_id:
            raise ValueError(f"flow {flow.id} source does not match its runtime rule trigger")
        if flow.to_page_id is None or flow.to_page_id not in page_ids:
            raise ValueError(f"flow {flow.id} references an unknown target page")
        flows_by_rule.setdefault(flow.rule_id, []).append(flow)

    for rule_id, rule in rules_by_id.items():
        actual_targets = [flow.to_page_id for flow in flows_by_rule.get(rule_id, [])]
        if actual_targets != _rule_navigate_targets(rule):
            raise ValueError(
                f"runtime rule {rule_id} flows must exactly match its navigate targets"
            )


def _validate_layout_tree(root: UINodeV1) -> None:
    if root.layout_item.position is not None:
        raise ValueError(f"root node {root.id} cannot have a freeform position")

    def validate_children(parent: UINodeV1) -> None:
        children = _node_children(parent)
        if children is None:
            return
        parent_is_freeform = isinstance(parent, FreeformNodeV1)
        for child in children:
            if parent_is_freeform and child.layout_item.position is None:
                raise ValueError(f"freeform child node {child.id} requires a freeform position")
            validate_children(child)

    validate_children(root)


def _collect_nodes(node: UINodeV1, nodes_by_id: dict[str, UINodeV1]) -> None:
    if node.id in nodes_by_id:
        raise ValueError(f"duplicate node ID: {node.id}")
    nodes_by_id[node.id] = node
    if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        for child in node.children:
            _collect_nodes(child, nodes_by_id)


def _validate_freeform_grid_references(
    nodes_by_id: dict[str, UINodeV1],
    color_token_keys: set[str],
) -> list[str]:
    grid_ids: list[str] = []
    for node in nodes_by_id.values():
        if not isinstance(node, FreeformNodeV1):
            continue
        for grid in node.grids:
            if grid.params.color_token_key not in color_token_keys:
                raise ValueError(f"freeform grid {grid.id} references an unknown color token key")
            grid_ids.append(grid.id)
    _unique(grid_ids, "freeform grid ID")
    return grid_ids


def _collect_form_submit_button_ids(
    node: UINodeV1,
    result: set[str],
    *,
    inside_form: bool = False,
) -> None:
    if isinstance(node, ButtonNodeV1) and inside_form:
        result.add(node.id)
    if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        child_inside_form = inside_form or isinstance(node, FormNodeV1)
        for child in node.children:
            _collect_form_submit_button_ids(
                child,
                result,
                inside_form=child_inside_form,
            )


def _validate_table_view_bindings(
    runtime: RuntimeDefinitionV1,
    nodes_by_id: dict[str, UINodeV1],
) -> None:
    schemas_by_id = {schema.id: schema for schema in runtime.entity_schemas}
    for binding in runtime.view_bindings:
        if not isinstance(binding, TableRowsViewBindingV1):
            continue
        node = nodes_by_id[binding.node_id]
        if not isinstance(node, TableNodeV1):
            raise ValueError(f"runtime view binding {binding.id} requires a table node")
        schema_field_ids = {field.id for field in schemas_by_id[binding.schema_id].fields}
        for column in node.columns:
            if column.field_id is None:
                raise ValueError(
                    f"runtime table {node.id} column {column.key} requires a schema field"
                )
            if column.field_id not in schema_field_ids:
                raise ValueError(
                    f"runtime table {node.id} column {column.key} field is not in its binding schema"
                )


def _validate_node_references(
    node: UINodeV1,
    forms_by_id: dict[str, RuntimeFormV1],
) -> None:
    if isinstance(node, FormNodeV1) and node.form_definition_id not in forms_by_id:
        raise ValueError(f"form node {node.id} references an unknown runtime form")
    if isinstance(node, InputNodeV1) and node.form_definition_id is not None:
        form = forms_by_id.get(node.form_definition_id)
        if form is None or node.form_field_id not in {field.id for field in form.fields}:
            raise ValueError(f"input node {node.id} references an unknown runtime form field")
    if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        for child in node.children:
            _validate_node_references(child, forms_by_id)


def _runtime_entity_ids(runtime: RuntimeDefinitionV1) -> list[str]:
    result: list[str] = []
    result.extend(role.id for role in runtime.roles)
    result.extend(variable.id for variable in runtime.variables)
    for schema in runtime.entity_schemas:
        result.append(schema.id)
        result.extend(field.id for field in schema.fields)
    for form in runtime.forms:
        result.append(form.id)
        result.extend(field.id for field in form.fields)
    result.extend(binding.id for binding in runtime.view_bindings)
    result.extend(rule.id for rule in runtime.rules)
    for scenario in runtime.scenarios:
        result.append(scenario.id)
        for entity_set in scenario.entity_fixtures:
            result.extend(entity.id for entity in entity_set.entities)
    return result


def _validate_runtime_flow_layout(
    runtime: RuntimeDefinitionV1,
    page_ids: set[str],
) -> None:
    if runtime.flow_layout is None:
        return
    projection_entity_ids = _runtime_flow_projection_entity_ids(runtime, page_ids)
    if any(node.node_id not in projection_entity_ids for node in runtime.flow_layout.nodes):
        raise ValueError("runtime flow layout references an unknown projection entity")


def _runtime_flow_projection_entity_ids(
    runtime: RuntimeDefinitionV1,
    page_ids: set[str],
) -> set[str]:
    return page_ids | {
        *(variable.id for variable in runtime.variables),
        *(rule.id for rule in runtime.rules),
        *(scenario.id for scenario in runtime.scenarios),
    }


def _validate_runtime_semantics(
    runtime: RuntimeDefinitionV1,
    *,
    page_ids: set[str],
    nodes_by_id: dict[str, UINodeV1],
    form_submit_button_ids: set[str],
) -> None:
    node_ids = set(nodes_by_id)
    _unique((role.id for role in runtime.roles), "runtime role ID")
    _unique((variable.id for variable in runtime.variables), "runtime variable ID")
    _unique((schema.id for schema in runtime.entity_schemas), "runtime schema ID")
    _unique((form.id for form in runtime.forms), "runtime form ID")
    _unique((binding.id for binding in runtime.view_bindings), "runtime view-binding ID")
    _unique(
        (f"{binding.node_id}:{binding.target}" for binding in runtime.view_bindings),
        "runtime node view-binding target",
    )
    _unique((rule.id for rule in runtime.rules), "runtime rule ID")
    _unique((scenario.id for scenario in runtime.scenarios), "runtime scenario ID")
    _unique(
        (field.id for schema in runtime.entity_schemas for field in schema.fields),
        "runtime entity field ID",
    )
    _unique(
        (field.id for form in runtime.forms for field in form.fields),
        "runtime form field ID",
    )
    _unique((role.key for role in runtime.roles), "runtime role key")
    _unique((variable.key for variable in runtime.variables), "runtime variable key")
    _unique((schema.key for schema in runtime.entity_schemas), "runtime schema key")
    _unique((form.key for form in runtime.forms), "runtime form key")
    _unique((rule.key for rule in runtime.rules), "runtime rule key")
    _unique((scenario.key for scenario in runtime.scenarios), "runtime scenario key")
    role_ids = {role.id for role in runtime.roles}
    variable_by_id = {variable.id: variable for variable in runtime.variables}
    schema_by_id = {schema.id: schema for schema in runtime.entity_schemas}
    form_by_id = {form.id: form for form in runtime.forms}
    entity_field_by_id: dict[str, RuntimeEntityFieldV1] = {}
    for schema in runtime.entity_schemas:
        _unique(
            (entity_field.key for entity_field in schema.fields),
            f"runtime schema {schema.id} field key",
        )
        for entity_field in schema.fields:
            entity_field_by_id[entity_field.id] = entity_field
    for form in runtime.forms:
        _unique(
            (form_field.key for form_field in form.fields),
            f"runtime form {form.id} field key",
        )
        for form_field in form.fields:
            if form_field.initial_value.type != form_field.value_type:
                raise ValueError(
                    f"runtime form field {form_field.id} initial value type is invalid"
                )
            if form_field.value_type == "string" and form_field.min_integer is not None:
                raise ValueError(f"runtime string field {form_field.id} cannot define minInteger")
    for variable in runtime.variables:
        if variable.entity_schema_id is not None and variable.entity_schema_id not in schema_by_id:
            raise ValueError(f"runtime variable {variable.id} references an unknown entity schema")
        if not _runtime_value_matches(
            variable.default_value,
            variable.value_type,
            variable.nullable,
        ):
            raise ValueError(f"runtime variable {variable.id} default value type is invalid")
        _validate_runtime_value(variable.default_value, schema_by_id)
        if (
            isinstance(variable.default_value, EntityRefRuntimeValueV1)
            and variable.default_value.schema_id != variable.entity_schema_id
        ):
            raise ValueError(f"runtime variable {variable.id} default entity schema is invalid")
    for binding in runtime.view_bindings:
        if binding.node_id not in node_ids:
            raise ValueError(f"runtime view binding {binding.id} references an unknown node")
        if isinstance(binding, TextViewBindingV1):
            _expression_type(
                binding.value,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=False,
            )
        elif isinstance(binding, VisibilityViewBindingV1):
            _validate_predicate(
                binding.predicate,
                role_ids=role_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=False,
            )
        else:
            binding_schema = schema_by_id.get(binding.schema_id)
            if binding_schema is None:
                raise ValueError(f"runtime view binding {binding.id} references an unknown schema")
            if binding.sort_field_id is not None and not any(
                field.id == binding.sort_field_id for field in binding_schema.fields
            ):
                raise ValueError(
                    f"runtime view binding {binding.id} sort field is not in its schema"
                )
    _unique(
        (f"{rule.trigger.node_id}:{rule.trigger.event}" for rule in runtime.rules if rule.enabled),
        "enabled runtime rule trigger",
    )
    for rule in runtime.rules:
        trigger_node = nodes_by_id.get(rule.trigger.node_id)
        if trigger_node is None:
            raise ValueError(f"runtime rule {rule.id} references an unknown node")
        if rule.trigger.event == "click" and not isinstance(trigger_node, ButtonNodeV1):
            raise ValueError(f"runtime rule {rule.id} click trigger requires a Button node")
        if rule.trigger.event == "submit":
            if not isinstance(trigger_node, ButtonNodeV1):
                raise ValueError(f"runtime rule {rule.id} submit trigger requires a Button node")
            if trigger_node.id not in form_submit_button_ids:
                raise ValueError(
                    f"runtime rule {rule.id} submit trigger requires a Button inside a Form"
                )
        if rule.trigger.event == "rowActivated" and not isinstance(trigger_node, TableNodeV1):
            raise ValueError(f"runtime rule {rule.id} rowActivated trigger requires a Table node")
        if rule.guard is not None:
            _validate_predicate(
                rule.guard,
                role_ids=role_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=rule.trigger.event == "rowActivated",
            )
        for effect in (*rule.effects, *rule.guard_false_effects):
            _validate_effect(
                effect,
                page_ids=page_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=rule.trigger.event == "rowActivated",
            )
    for scenario in runtime.scenarios:
        if scenario.actor_role_id not in role_ids or scenario.start_page_id not in page_ids:
            raise ValueError(f"runtime scenario {scenario.id} has an invalid start identity")
        _unique(
            (entry.variable_id for entry in scenario.initial_variables),
            f"runtime scenario {scenario.id} variable ID",
        )
        for entry in scenario.initial_variables:
            scenario_variable = variable_by_id.get(entry.variable_id)
            if scenario_variable is None:
                raise ValueError(f"runtime scenario {scenario.id} references an unknown variable")
            if not _runtime_value_matches(
                entry.value,
                scenario_variable.value_type,
                scenario_variable.nullable,
            ):
                raise ValueError(
                    f"runtime scenario {scenario.id} variable {scenario_variable.id} has an invalid type"
                )
            _validate_runtime_value(entry.value, schema_by_id)
            if (
                isinstance(entry.value, EntityRefRuntimeValueV1)
                and entry.value.schema_id != scenario_variable.entity_schema_id
            ):
                raise ValueError(
                    f"runtime scenario {scenario.id} variable {scenario_variable.id} has an invalid entity schema"
                )
        _unique(
            (fixture.schema_id for fixture in scenario.entity_fixtures),
            f"runtime scenario {scenario.id} fixture schema ID",
        )
        for fixture in scenario.entity_fixtures:
            fixture_schema = schema_by_id.get(fixture.schema_id)
            if fixture_schema is None:
                raise ValueError(f"runtime scenario {scenario.id} references an unknown schema")
            _unique(
                (entity.id for entity in fixture.entities),
                f"runtime scenario {scenario.id} fixture entity ID",
            )
            expected_field_ids = {field.id for field in fixture_schema.fields}
            for entity in fixture.entities:
                if entity.schema_id != fixture.schema_id:
                    raise ValueError(f"runtime fixture entity {entity.id} schema is inconsistent")
                field_ids = _unique(
                    (field.field_id for field in entity.fields),
                    f"runtime fixture entity {entity.id} field ID",
                )
                if field_ids != expected_field_ids:
                    raise ValueError(f"runtime fixture entity {entity.id} fields are incomplete")
                for field_value in entity.fields:
                    definition = entity_field_by_id[field_value.field_id]
                    if not _runtime_value_matches(
                        field_value.value,
                        definition.value_type,
                        definition.nullable,
                    ):
                        raise ValueError(
                            f"runtime fixture entity {entity.id} field value type is invalid"
                        )
                    _validate_runtime_value(field_value.value, schema_by_id)


def _runtime_value_matches(
    value: RuntimeValueV1,
    expected_type: str,
    nullable: bool,
) -> bool:
    if value.type == "null":
        return nullable or expected_type == "null"
    return value.type == expected_type


def _validate_runtime_value(
    value: RuntimeValueV1,
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
) -> None:
    if isinstance(value, EntityRefRuntimeValueV1) and value.schema_id not in schema_by_id:
        raise ValueError("runtime entity reference value uses an unknown schema")


def _expression_type(
    expression: RuntimeExpressionV1,
    *,
    variable_by_id: dict[str, RuntimeVariableV1],
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
    form_by_id: dict[str, RuntimeFormV1],
    entity_field_by_id: dict[str, RuntimeEntityFieldV1],
    allow_event_entity_ref: bool,
) -> str:
    if isinstance(expression, LiteralExpressionV1):
        _validate_runtime_value(expression.value, schema_by_id)
        return expression.value.type
    if isinstance(expression, VariableExpressionV1):
        variable = variable_by_id.get(expression.variable_id)
        if variable is None:
            raise ValueError("runtime expression references an unknown variable")
        return variable.value_type
    if isinstance(expression, FormFieldExpressionV1):
        form = form_by_id.get(expression.form_id)
        if form is None:
            raise ValueError("runtime expression references an unknown form")
        field = next((item for item in form.fields if item.id == expression.field_id), None)
        if field is None:
            raise ValueError("runtime expression form field does not belong to its form")
        return field.value_type
    if isinstance(expression, EventEntityRefExpressionV1):
        if not allow_event_entity_ref:
            raise ValueError("runtime expression cannot reference an event entity in this context")
        return "entityRef"
    if isinstance(expression.entity_ref, VariableExpressionV1):
        ref_type = _expression_type(
            expression.entity_ref,
            variable_by_id=variable_by_id,
            schema_by_id=schema_by_id,
            form_by_id=form_by_id,
            entity_field_by_id=entity_field_by_id,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if ref_type != "entityRef":
            raise ValueError("runtime entity-field expression requires an entity reference")
    elif not allow_event_entity_ref:
        raise ValueError("runtime expression cannot reference an event entity in this context")
    field_definition = entity_field_by_id.get(expression.field_id)
    if field_definition is None:
        raise ValueError("runtime expression references an unknown entity field")
    if not _runtime_value_matches(expression.fallback, field_definition.value_type, True):
        raise ValueError("runtime entity-field fallback type is invalid")
    _validate_runtime_value(expression.fallback, schema_by_id)
    return field_definition.value_type


def _validate_predicate(
    predicate: RuntimePredicateV1,
    *,
    role_ids: set[str],
    variable_by_id: dict[str, RuntimeVariableV1],
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
    form_by_id: dict[str, RuntimeFormV1],
    entity_field_by_id: dict[str, RuntimeEntityFieldV1],
    allow_event_entity_ref: bool,
) -> None:
    if isinstance(predicate, AllPredicateV1):
        for item in predicate.items:
            _validate_predicate(
                item,
                role_ids=role_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=allow_event_entity_ref,
            )
        return
    if isinstance(predicate, RoleIsPredicateV1):
        if predicate.role_id not in role_ids:
            raise ValueError("runtime predicate references an unknown role")
        return
    if isinstance(predicate, FormValidPredicateV1):
        if predicate.form_id not in form_by_id:
            raise ValueError("runtime predicate references an unknown form")
        return
    left_type = _expression_type(
        predicate.left,
        variable_by_id=variable_by_id,
        schema_by_id=schema_by_id,
        form_by_id=form_by_id,
        entity_field_by_id=entity_field_by_id,
        allow_event_entity_ref=allow_event_entity_ref,
    )
    right_type = _expression_type(
        predicate.right,
        variable_by_id=variable_by_id,
        schema_by_id=schema_by_id,
        form_by_id=form_by_id,
        entity_field_by_id=entity_field_by_id,
        allow_event_entity_ref=allow_event_entity_ref,
    )
    if left_type != "null" and right_type != "null" and left_type != right_type:
        raise ValueError("runtime comparison expression types do not match")


def _validate_effect(
    effect: RuntimeEffectV1,
    *,
    page_ids: set[str],
    variable_by_id: dict[str, RuntimeVariableV1],
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
    form_by_id: dict[str, RuntimeFormV1],
    entity_field_by_id: dict[str, RuntimeEntityFieldV1],
    allow_event_entity_ref: bool,
) -> None:
    if isinstance(effect, SetVariableEffectV1):
        variable = variable_by_id.get(effect.variable_id)
        if variable is None:
            raise ValueError("runtime effect references an unknown variable")
        if (
            _expression_type(
                effect.value,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=allow_event_entity_ref,
            )
            != variable.value_type
        ):
            raise ValueError("runtime set-variable expression type is invalid")
        return
    if isinstance(effect, ValidateFormEffectV1):
        if effect.form_id not in form_by_id:
            raise ValueError("runtime effect references an unknown form")
        return
    if isinstance(effect, NavigateEffectV1):
        if effect.target_page_id not in page_ids:
            raise ValueError("runtime effect references an unknown page")
        return
    if isinstance(effect, NotifyEffectV1):
        return
    schema = schema_by_id.get(effect.schema_id)
    if schema is None:
        raise ValueError("runtime entity effect references an unknown schema")
    if isinstance(effect, CreateEntityEffectV1):
        result_variable = variable_by_id.get(effect.result_variable_id)
        if (
            result_variable is None
            or result_variable.value_type != "entityRef"
            or result_variable.entity_schema_id != effect.schema_id
        ):
            raise ValueError("runtime create-entity result variable is invalid")
        assignments = effect.values
    else:
        if isinstance(effect.entity_ref, VariableExpressionV1):
            variable = variable_by_id.get(effect.entity_ref.variable_id)
            if (
                variable is None
                or variable.value_type != "entityRef"
                or variable.entity_schema_id != effect.schema_id
            ):
                raise ValueError("runtime update-entity reference variable is invalid")
        elif not allow_event_entity_ref:
            raise ValueError("runtime update-entity effect cannot use an event entity here")
        assignments = effect.updates
    assignment_ids = _unique(
        (assignment.field_id for assignment in assignments),
        "runtime entity effect field ID",
    )
    schema_fields = {field.id: field for field in schema.fields}
    if not assignment_ids.issubset(schema_fields):
        raise ValueError("runtime entity effect field does not belong to its schema")
    for assignment in assignments:
        expression_type = _expression_type(
            assignment.value,
            variable_by_id=variable_by_id,
            schema_by_id=schema_by_id,
            form_by_id=form_by_id,
            entity_field_by_id=entity_field_by_id,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if expression_type != schema_fields[assignment.field_id].value_type:
            raise ValueError("runtime entity effect assignment type is invalid")


def _table_row_ids(document: PrototypeDocumentV1) -> list[str]:
    result: list[str] = []

    def collect(node: UINodeV1) -> None:
        if isinstance(node, TableNodeV1):
            result.extend(row.id for row in node.rows)
        if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
            for child in node.children:
                collect(child)

    for page in document.pages:
        collect(page.root)
    for definition in document.component_definitions:
        collect(definition.root)
    return result


class NewNodeCommonV1(StrictPrototypeModel):
    new_node_key: TechnicalKey
    name: Annotated[str, Field(min_length=1, max_length=80)]
    visibility: Literal["visible", "hidden"]
    layout_item: LayoutItemV1
    responsive: Annotated[list[ResponsiveOverrideV1], Field(max_length=3)]

    @model_validator(mode="after")
    def validate_responsive_overrides(self) -> NewNodeCommonV1:
        _validate_responsive_overrides(self.responsive)
        return self


class NewStackNodeV1(NewNodeCommonV1):
    type: Literal["Stack"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=128)]
    align: Literal["start", "center", "end", "stretch"]
    justify: Literal["start", "center", "end", "between"]
    padding: PaddingV1
    children: Annotated[list[NewUINodeV1], Field(max_length=500)]


class NewGridNodeV1(NewNodeCommonV1):
    type: Literal["Grid"]
    columns: Annotated[int, Field(ge=1, le=12)]
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    column_overrides: Annotated[list[GridColumnOverrideV1], Field(max_length=3)]
    children: Annotated[list[NewUINodeV1], Field(max_length=500)]

    @model_validator(mode="after")
    def validate_column_overrides(self) -> NewGridNodeV1:
        _validate_grid_column_overrides(item.min_width for item in self.column_overrides)
        return self


class NewFormNodeV1(NewNodeCommonV1):
    type: Literal["Form"]
    form_definition_id: EntityId
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    children: Annotated[list[NewUINodeV1], Field(min_length=1, max_length=200)]


class NewFreeformNodeV1(NewNodeCommonV1):
    type: Literal["Freeform"]
    children: Annotated[list[NewUINodeV1], Field(max_length=500)]
    grids: Annotated[
        list[FreeformGridV1],
        Field(default_factory=list, max_length=8, exclude_if=lambda value: not value),
    ]

    @model_validator(mode="after")
    def validate_size(self) -> NewFreeformNodeV1:
        _validate_freeform_size(self.layout_item)
        _validate_freeform_grid_geometry(self.grids, self.layout_item)
        return self


class NewTextNodeV1(NewNodeCommonV1):
    type: Literal["Text"]
    content: Annotated[str, Field(max_length=8_000)]
    semantic: Literal["heading", "body", "label", "caption"]
    tone: Literal["default", "muted", "success", "warning", "danger"]


class NewInputNodeV1(NewNodeCommonV1):
    type: Literal["Input"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    placeholder: Annotated[str, Field(max_length=240)]
    value: Annotated[str, Field(max_length=8_000)]
    input_type: Literal["text", "number", "email"]
    required: bool
    disabled: bool
    form_definition_id: EntityId | None = None
    form_field_id: EntityId | None = None

    @model_validator(mode="after")
    def validate_form_binding(self) -> NewInputNodeV1:
        if (self.form_definition_id is None) != (self.form_field_id is None):
            raise ValueError("input form and field bindings must be supplied together")
        return self


class NewButtonNodeV1(NewNodeCommonV1):
    type: Literal["Button"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    variant: Literal["primary", "secondary", "danger", "ghost"]
    size: Literal["small", "medium", "large"]
    disabled: bool
    icon_name: Annotated[str, Field(min_length=1, max_length=80)] | None


class NewTableNodeV1(NewNodeCommonV1):
    type: Literal["Table"]
    columns: Annotated[list[TableColumnV1], Field(min_length=1, max_length=30)]
    rows: Annotated[list[TableRowV1], Field(max_length=200)]
    density: Literal["compact", "comfortable"]

    @model_validator(mode="after")
    def validate_table_shape(self) -> NewTableNodeV1:
        column_keys = _unique((column.key for column in self.columns), "table column key")
        _unique((row.id for row in self.rows), "table row ID")
        for row in self.rows:
            cell_keys = _unique((cell.column_key for cell in row.cells), "table cell column key")
            if cell_keys != column_keys:
                raise ValueError(f"table row {row.id} cells must match the table columns")
        return self


type NewUINodeV1 = Annotated[
    NewStackNodeV1
    | NewGridNodeV1
    | NewFormNodeV1
    | NewFreeformNodeV1
    | NewTextNodeV1
    | NewInputNodeV1
    | NewButtonNodeV1
    | NewTableNodeV1,
    Field(discriminator="type"),
]

NewStackNodeV1.model_rebuild()
NewGridNodeV1.model_rebuild()
NewFormNodeV1.model_rebuild()
NewFreeformNodeV1.model_rebuild()


class ExistingNodeRefV1(StrictPrototypeModel):
    kind: Literal["existing"]
    node_id: EntityId


class NewNodeRefV1(StrictPrototypeModel):
    kind: Literal["new"]
    new_node_key: TechnicalKey


type NodeRefV1 = Annotated[ExistingNodeRefV1 | NewNodeRefV1, Field(discriminator="kind")]


class InsertNodeCommandV1(StrictPrototypeModel):
    kind: Literal["insertNode"]
    parent: NodeRefV1
    slot: None
    index: Annotated[int, Field(ge=0)]
    node: NewUINodeV1


class MoveNodeCommandV1(StrictPrototypeModel):
    kind: Literal["moveNode"]
    node: NodeRefV1
    target_parent: NodeRefV1
    target_slot: None
    target_index: Annotated[int, Field(ge=0)]
    target_position: FreeformPositionV1 | None = None

    @model_serializer(mode="wrap")
    def serialize_explicit_target_position(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, object]:
        serialized = cast(dict[str, object], handler(self))
        if "target_position" not in self.model_fields_set:
            serialized.pop("target_position", None)
            serialized.pop("targetPosition", None)
        return serialized


class RemoveNodeCommandV1(StrictPrototypeModel):
    kind: Literal["removeNode"]
    node_id: EntityId


class UpdateNodeNameCommandV1(StrictPrototypeModel):
    kind: Literal["updateNodeName"]
    node_id: EntityId
    name: CommandNodeName


class RestoreNodeNameCommandV1(StrictPrototypeModel):
    kind: Literal["restoreNodeName"]
    node_id: EntityId
    name: Annotated[str, Field(min_length=1, max_length=80)]


class TextContentUpdateV1(StrictPrototypeModel):
    kind: Literal["textContent"]
    content: Annotated[str, Field(max_length=8_000)]


class LabelUpdateV1(StrictPrototypeModel):
    kind: Literal["label"]
    label: Annotated[str, Field(min_length=1, max_length=120)]


class PlaceholderUpdateV1(StrictPrototypeModel):
    kind: Literal["placeholder"]
    placeholder: Annotated[str, Field(max_length=240)]


class ButtonVariantUpdateV1(StrictPrototypeModel):
    kind: Literal["buttonVariant"]
    variant: Literal["primary", "secondary", "danger", "ghost"]


class DisabledUpdateV1(StrictPrototypeModel):
    kind: Literal["disabled"]
    disabled: bool


class InputValueUpdateV1(StrictPrototypeModel):
    kind: Literal["inputValue"]
    value: Annotated[str, Field(max_length=8_000)]


class StackLayoutUpdateV1(StrictPrototypeModel):
    kind: Literal["stackLayout"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=128)]
    align: Literal["start", "center", "end", "stretch"]
    justify: Literal["start", "center", "end", "between"]
    padding: PaddingV1


class GridLayoutUpdateV1(StrictPrototypeModel):
    kind: Literal["gridLayout"]
    columns: Annotated[int, Field(ge=1, le=12)]
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    column_overrides: Annotated[list[GridColumnOverrideV1], Field(max_length=3)]

    @model_validator(mode="after")
    def validate_column_overrides(self) -> GridLayoutUpdateV1:
        _validate_grid_column_overrides(item.min_width for item in self.column_overrides)
        return self


class FormLayoutUpdateV1(StrictPrototypeModel):
    kind: Literal["formLayout"]
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1


class FreeformGridsUpdateV1(StrictPrototypeModel):
    kind: Literal["freeformGrids"]
    grids: Annotated[list[FreeformGridV1], Field(max_length=8)]


class ResponsiveLayoutUpdateV1(StrictPrototypeModel):
    kind: Literal["responsiveLayout"]
    responsive: Annotated[list[ResponsiveOverrideV1], Field(max_length=3)]

    @model_validator(mode="after")
    def validate_responsive_overrides(self) -> ResponsiveLayoutUpdateV1:
        _validate_responsive_overrides(self.responsive)
        return self


class TableDataUpdateV1(StrictPrototypeModel):
    kind: Literal["tableData"]
    columns: Annotated[list[TableColumnV1], Field(min_length=1, max_length=30)]
    rows: Annotated[list[TableRowV1], Field(max_length=200)]


class VisibilityUpdateV1(StrictPrototypeModel):
    kind: Literal["visibility"]
    visibility: Literal["visible", "hidden"]


type NodePropertyUpdateV1 = Annotated[
    TextContentUpdateV1
    | LabelUpdateV1
    | PlaceholderUpdateV1
    | ButtonVariantUpdateV1
    | DisabledUpdateV1
    | InputValueUpdateV1
    | StackLayoutUpdateV1
    | GridLayoutUpdateV1
    | FormLayoutUpdateV1
    | FreeformGridsUpdateV1
    | ResponsiveLayoutUpdateV1
    | TableDataUpdateV1
    | VisibilityUpdateV1,
    Field(discriminator="kind"),
]


class SetNodePropertyCommandV1(StrictPrototypeModel):
    kind: Literal["setNodeProperty"]
    node: NodeRefV1
    update: NodePropertyUpdateV1


class SetNodeLayoutCommandV1(StrictPrototypeModel):
    kind: Literal["setNodeLayout"]
    node: NodeRefV1
    update: LayoutItemUpdateV1


class ReorderPageCommandV1(StrictPrototypeModel):
    kind: Literal["reorderPage"]
    page_id: EntityId
    target_index: Annotated[int, Field(ge=0)]


class AddPageCommandV1(StrictPrototypeModel):
    kind: Literal["addPage"]
    after_page_id: EntityId
    new_page_key: TechnicalKey
    title: CommandPageTitle
    include_in_navigation: bool


class DuplicatePageCommandV1(StrictPrototypeModel):
    kind: Literal["duplicatePage"]
    page_id: EntityId
    new_page_key: TechnicalKey
    title: CommandPageTitle


class RenamePageCommandV1(StrictPrototypeModel):
    kind: Literal["renamePage"]
    page_id: EntityId
    title: CommandPageTitle


class DeletePageCommandV1(StrictPrototypeModel):
    kind: Literal["deletePage"]
    page_id: EntityId


class ReorderNavigationItemCommandV1(StrictPrototypeModel):
    kind: Literal["reorderNavigationItem"]
    item_id: EntityId
    target_index: Annotated[int, Field(ge=0)]


class SetRuntimeEntityFieldCommandV1(StrictPrototypeModel):
    kind: Literal["setRuntimeEntityField"]
    scenario_id: EntityId
    schema_id: EntityId
    entity_id: EntityId
    field_id: EntityId
    value: RuntimeValueV1


class SetRuntimeFlowNodePositionCommandV1(StrictPrototypeModel):
    kind: Literal["setRuntimeFlowNodePosition"]
    flow_node_id: EntityId
    x: Annotated[int, Field(ge=-FLOW_COORDINATE_LIMIT, le=FLOW_COORDINATE_LIMIT)]
    y: Annotated[int, Field(ge=-FLOW_COORDINATE_LIMIT, le=FLOW_COORDINATE_LIMIT)]


class AddBehaviorRuleCommandV1(StrictPrototypeModel):
    kind: Literal["addBehaviorRule"]
    new_rule_key: TechnicalKey
    definition: RuntimeRuleDefinitionV1

    @model_validator(mode="after")
    def validate_new_rule_key(self) -> AddBehaviorRuleCommandV1:
        if self.new_rule_key != self.definition.key:
            raise ValueError("newRuleKey must match the behavior rule definition key")
        return self


class ReplaceBehaviorRuleCommandV1(StrictPrototypeModel):
    kind: Literal["replaceBehaviorRule"]
    rule_id: EntityId
    definition: RuntimeRuleDefinitionV1


class RemoveBehaviorRuleCommandV1(StrictPrototypeModel):
    kind: Literal["removeBehaviorRule"]
    rule_id: EntityId


type DomainCommandV1 = Annotated[
    InsertNodeCommandV1
    | MoveNodeCommandV1
    | RemoveNodeCommandV1
    | UpdateNodeNameCommandV1
    | SetNodePropertyCommandV1
    | SetNodeLayoutCommandV1
    | ReorderPageCommandV1
    | AddPageCommandV1
    | DuplicatePageCommandV1
    | RenamePageCommandV1
    | DeletePageCommandV1
    | ReorderNavigationItemCommandV1
    | SetRuntimeEntityFieldCommandV1
    | SetRuntimeFlowNodePositionCommandV1
    | AddBehaviorRuleCommandV1
    | ReplaceBehaviorRuleCommandV1
    | RemoveBehaviorRuleCommandV1,
    Field(discriminator="kind"),
]


class FreeformMoveEvidencePointV1(StrictPrototypeModel):
    x: CanonicalSignedDecimal
    y: CanonicalSignedDecimal


class FreeformMoveEvidenceBoundsV1(FreeformMoveEvidencePointV1):
    width: CanonicalPositiveDecimal
    height: CanonicalPositiveDecimal


class FreeformMoveEvidenceSiblingV1(FreeformMoveEvidenceBoundsV1):
    node_id: EntityId


class FreeformMoveEvidenceContainerSizeV1(StrictPrototypeModel):
    width: CanonicalPositiveDecimal
    height: CanonicalPositiveDecimal


class FreeformMoveEvidenceAxisWinnersV1(StrictPrototypeModel):
    x: Literal["raw", "alignment", "spacing", "grid"]
    y: Literal["raw", "alignment", "spacing", "grid"]


class FreeformMoveEvidenceCandidateCommonV1(StrictPrototypeModel):
    axis: Literal["x", "y"]
    position: CanonicalSignedDecimal
    correction: CanonicalSignedDecimal
    distance: CanonicalNonNegativeDecimal
    sort_key: Annotated[str, Field(min_length=1, max_length=512)]
    outcome: Literal["winner", "farther", "tiePriority", "crossAxisInvalid"]


def _validate_freeform_move_candidate_anchors(
    *,
    axis: Literal["x", "y"],
    moving_anchor: str,
    target_anchor: str | None = None,
) -> None:
    allowed = {"left", "center", "right"} if axis == "x" else {"top", "middle", "bottom"}
    if moving_anchor not in allowed:
        raise ValueError("freeform move evidence moving anchor does not match its axis")
    if target_anchor is not None and target_anchor not in allowed:
        raise ValueError("freeform move evidence target anchor does not match its axis")


class FreeformMoveAlignmentCandidateV1(FreeformMoveEvidenceCandidateCommonV1):
    source: Literal["alignment"]
    coordinate: CanonicalSignedDecimal
    moving_anchor: Literal["left", "center", "right", "top", "middle", "bottom"]
    target_anchor: Literal["left", "center", "right", "top", "middle", "bottom"]
    target_kind: Literal["container", "sibling"]
    target_node_id: EntityId | None

    @model_validator(mode="after")
    def validate_source(self) -> FreeformMoveAlignmentCandidateV1:
        _validate_freeform_move_candidate_anchors(
            axis=self.axis,
            moving_anchor=self.moving_anchor,
            target_anchor=self.target_anchor,
        )
        if self.target_kind == "container" and self.target_node_id is not None:
            raise ValueError("container alignment evidence must use a null targetNodeId")
        if self.target_kind == "sibling" and self.target_node_id is None:
            raise ValueError("sibling alignment evidence requires targetNodeId")
        return self


class FreeformMoveSpacingCandidateV1(FreeformMoveEvidenceCandidateCommonV1):
    source: Literal["spacing"]
    placement: Literal["before", "between", "after"]
    gap: CanonicalPositiveDecimal
    reference_node_ids: Annotated[list[EntityId], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def validate_references(self) -> FreeformMoveSpacingCandidateV1:
        _unique(self.reference_node_ids, "freeform move spacing reference node ID")
        return self


class FreeformMoveGridCandidateV1(FreeformMoveEvidenceCandidateCommonV1):
    source: Literal["grid"]
    grid_id: EntityId
    grid_type: Literal["square", "columns", "rows"]
    grid_line_index: Annotated[int, Field(ge=0)]
    coordinate: CanonicalSignedDecimal
    moving_anchor: Literal["left", "center", "right", "top", "middle", "bottom"]

    @model_validator(mode="after")
    def validate_source(self) -> FreeformMoveGridCandidateV1:
        _validate_freeform_move_candidate_anchors(
            axis=self.axis,
            moving_anchor=self.moving_anchor,
        )
        return self


type FreeformMoveEvidenceCandidateV1 = Annotated[
    FreeformMoveAlignmentCandidateV1 | FreeformMoveSpacingCandidateV1 | FreeformMoveGridCandidateV1,
    Field(discriminator="source"),
]


def _freeform_move_evidence_decimals_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= FREEFORM_MOVE_EVIDENCE_DECIMAL_TOLERANCE


class FreeformMoveEvidenceV2(StrictPrototypeModel):
    evidence_version: Literal[2]
    kind: Literal["freeformMove"]
    snap_solver_version: Literal["structured-prototype-freeform-snap/v1"]
    snap_solver_source_hash: Sha256
    document_id: EntityId
    draft_id: EntityId
    freeform_id: EntityId
    base_head_sequence_no: Annotated[int, Field(ge=0)]
    base_document_hash: Sha256
    selected_node_ids: Annotated[list[EntityId], Field(min_length=1, max_length=500)]
    grids: Annotated[list[FreeformGridV1], Field(max_length=8)]
    grid_list_hash: Sha256
    grid_snapping_enabled: bool
    preview_scale: CanonicalPositiveDecimal
    client_threshold: Literal["6"]
    selection_bounds: FreeformMoveEvidenceBoundsV1
    direct_siblings: Annotated[list[FreeformMoveEvidenceSiblingV1], Field(max_length=500)]
    container_size: FreeformMoveEvidenceContainerSizeV1
    requested_delta: FreeformMoveEvidencePointV1
    raw_position: FreeformMoveEvidencePointV1
    final_position: FreeformMoveEvidencePointV1
    correction: FreeformMoveEvidencePointV1
    bypass_snapping: bool
    axis_winners: FreeformMoveEvidenceAxisWinnersV1
    candidates: Annotated[list[FreeformMoveEvidenceCandidateV1], Field(max_length=6)]
    terminal_reason: Literal["pointerup"]

    @model_validator(mode="after")
    def validate_evidence(self) -> FreeformMoveEvidenceV2:
        selected_ids = _unique(self.selected_node_ids, "freeform move selected node ID")
        if self.selected_node_ids != sorted(self.selected_node_ids):
            raise ValueError("freeform move selectedNodeIds must use canonical sorted order")
        sibling_ids = _unique(
            (sibling.node_id for sibling in self.direct_siblings),
            "freeform move direct sibling ID",
        )
        if [sibling.node_id for sibling in self.direct_siblings] != sorted(sibling_ids):
            raise ValueError("freeform move directSiblings must use canonical nodeId order")
        _unique(
            (candidate.sort_key for candidate in self.candidates),
            "freeform move candidate sortKey",
        )
        grid_ids = _unique((grid.id for grid in self.grids), "freeform move grid ID")
        if selected_ids & sibling_ids:
            raise ValueError("freeform move selected nodes cannot also be direct siblings")
        if self.freeform_id in selected_ids | sibling_ids | grid_ids:
            raise ValueError("freeform move Freeform ID must be distinct from captured entity IDs")
        if (selected_ids | sibling_ids) & grid_ids:
            raise ValueError("freeform move grid IDs must be distinct from captured node IDs")

        grids_by_id = {grid.id: grid for grid in self.grids}
        winner_candidates: dict[
            Literal["x", "y"],
            list[FreeformMoveEvidenceCandidateV1],
        ] = {"x": [], "y": []}
        raw_positions = {
            "x": Decimal(self.raw_position.x),
            "y": Decimal(self.raw_position.y),
        }
        final_positions = {
            "x": Decimal(self.final_position.x),
            "y": Decimal(self.final_position.y),
        }
        corrections = {
            "x": Decimal(self.correction.x),
            "y": Decimal(self.correction.y),
        }
        axes: tuple[Literal["x", "y"], ...] = ("x", "y")
        for axis in axes:
            if not _freeform_move_evidence_decimals_match(
                corrections[axis],
                final_positions[axis] - raw_positions[axis],
            ):
                raise ValueError(
                    f"freeform move {axis} correction must equal finalPosition - rawPosition"
                )

        for candidate in self.candidates:
            candidate_position = Decimal(candidate.position)
            candidate_correction = Decimal(candidate.correction)
            if not _freeform_move_evidence_decimals_match(
                candidate_position,
                raw_positions[candidate.axis] + candidate_correction,
            ):
                raise ValueError(
                    "freeform move candidate position must equal raw position plus correction"
                )
            if not _freeform_move_evidence_decimals_match(
                Decimal(candidate.distance),
                abs(candidate_correction),
            ):
                raise ValueError(
                    "freeform move candidate distance must equal its absolute correction"
                )
            if candidate.outcome == "winner":
                winner_candidates[candidate.axis].append(candidate)

            if isinstance(candidate, FreeformMoveAlignmentCandidateV1):
                if (
                    candidate.target_node_id is not None
                    and candidate.target_node_id not in sibling_ids
                ):
                    raise ValueError(
                        "freeform move alignment candidate references an uncaptured sibling"
                    )
                continue
            if isinstance(candidate, FreeformMoveSpacingCandidateV1):
                if any(node_id not in sibling_ids for node_id in candidate.reference_node_ids):
                    raise ValueError(
                        "freeform move spacing candidate references an uncaptured sibling"
                    )
                continue
            grid = grids_by_id.get(candidate.grid_id)
            if grid is None:
                raise ValueError("freeform move grid candidate references an uncaptured grid")
            if grid.type != candidate.grid_type:
                raise ValueError("freeform move grid candidate type does not match its grid")
            if (grid.type == "columns" and candidate.axis != "x") or (
                grid.type == "rows" and candidate.axis != "y"
            ):
                raise ValueError("freeform move grid candidate axis does not match its grid type")

        for axis in axes:
            winner_kind = self.axis_winners.x if axis == "x" else self.axis_winners.y
            winners = winner_candidates[axis]
            if winner_kind == "raw":
                if winners:
                    raise ValueError("raw freeform move axis cannot have a winner candidate")
                if not _freeform_move_evidence_decimals_match(corrections[axis], Decimal(0)):
                    raise ValueError("raw freeform move axis must have zero correction")
                continue
            if len(winners) != 1:
                raise ValueError(
                    "non-raw freeform move axis must have exactly one winner candidate"
                )
            winner = winners[0]
            if winner.source != winner_kind:
                raise ValueError("freeform move axis winner kind does not match its candidate")
            if not _freeform_move_evidence_decimals_match(
                Decimal(winner.position),
                final_positions[axis],
            ) or not _freeform_move_evidence_decimals_match(
                Decimal(winner.correction),
                corrections[axis],
            ):
                raise ValueError(
                    "freeform move winner candidate does not match the final axis projection"
                )
            if isinstance(winner, FreeformMoveGridCandidateV1):
                grid = grids_by_id[winner.grid_id]
                if not self.grid_snapping_enabled or not grid.snap_enabled:
                    raise ValueError("disabled grid snapping cannot win a freeform move axis")

        if self.bypass_snapping and (self.axis_winners.x != "raw" or self.axis_winners.y != "raw"):
            raise ValueError("bypassed freeform move snapping must use raw axis winners")
        return self


class DomainCommandBatchV1(StrictPrototypeModel):
    command_contract_version: Literal[1]
    commands: Annotated[list[DomainCommandV1], Field(min_length=1, max_length=100)]
    summary: Annotated[str, Field(min_length=1, max_length=240)]
    evidence: FreeformMoveEvidenceV2 | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_evidence_linkage(self) -> DomainCommandBatchV1:
        if self.evidence is None:
            return self
        moved_node_ids: list[str] = []
        target_positions: list[FreeformPositionV1] = []
        for command in self.commands:
            if (
                not isinstance(command, MoveNodeCommandV1)
                or not isinstance(command.node, ExistingNodeRefV1)
                or not isinstance(command.target_parent, ExistingNodeRefV1)
                or command.target_position is None
            ):
                raise ValueError(
                    "freeform move evidence requires only positioned existing-node move commands"
                )
            if command.target_parent.node_id != self.evidence.freeform_id:
                raise ValueError(
                    "freeform move evidence container ID must match every move target parent"
                )
            moved_node_ids.append(command.node.node_id)
            target_positions.append(command.target_position)
        _unique(moved_node_ids, "freeform move evidence command node ID")
        if sorted(moved_node_ids) != self.evidence.selected_node_ids:
            raise ValueError(
                "freeform move evidence selectedNodeIds must match the batch move commands"
            )
        if len(target_positions) == 1:
            target = target_positions[0]
            if not _freeform_move_evidence_decimals_match(
                Decimal(target.x),
                Decimal(self.evidence.final_position.x),
            ) or not _freeform_move_evidence_decimals_match(
                Decimal(target.y),
                Decimal(self.evidence.final_position.y),
            ):
                raise ValueError(
                    "freeform move evidence finalPosition must match the single-node targetPosition"
                )
        return self


class RestoreNodeCommandV1(StrictPrototypeModel):
    kind: Literal["restoreNode"]
    parent_id: EntityId
    index: Annotated[int, Field(ge=0)]
    node: UINodeV1


class RestoreRuntimeFlowNodePositionCommandV1(StrictPrototypeModel):
    kind: Literal["restoreRuntimeFlowNodePosition"]
    flow_node_id: EntityId
    x: Annotated[int, Field(ge=-FLOW_COORDINATE_LIMIT, le=FLOW_COORDINATE_LIMIT)]
    y: Annotated[int, Field(ge=-FLOW_COORDINATE_LIMIT, le=FLOW_COORDINATE_LIMIT)]


class RemoveRuntimeFlowNodePositionCommandV1(StrictPrototypeModel):
    kind: Literal["removeRuntimeFlowNodePosition"]
    flow_node_id: EntityId


class IndexedPrototypeFlowV1(StrictPrototypeModel):
    index: Annotated[int, Field(ge=0)]
    flow: PrototypeFlowV1


class IndexedNavigationItemV1(StrictPrototypeModel):
    index: Annotated[int, Field(ge=0)]
    item: NavigationItemV1


class IndexedRuntimeViewBindingV1(StrictPrototypeModel):
    index: Annotated[int, Field(ge=0)]
    binding: RuntimeViewBindingV1


class IndexedRuntimeRuleV1(StrictPrototypeModel):
    index: Annotated[int, Field(ge=0)]
    rule: RuntimeRuleV1


class NavigationLabelSnapshotV1(StrictPrototypeModel):
    item_id: EntityId
    label: Annotated[str, Field(min_length=1, max_length=80)]


class PageTitleProjectionSnapshotV1(StrictPrototypeModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    navigation_labels: Annotated[list[NavigationLabelSnapshotV1], Field(max_length=20)]

    @model_validator(mode="after")
    def validate_navigation_labels(self) -> PageTitleProjectionSnapshotV1:
        _unique(
            (entry.item_id for entry in self.navigation_labels),
            "page title snapshot navigation item ID",
        )
        return self


class RestorePageTitleProjectionCommandV1(StrictPrototypeModel):
    kind: Literal["restorePageTitleProjection"]
    page_id: EntityId
    snapshot: PageTitleProjectionSnapshotV1


class PageProjectionSnapshotV1(StrictPrototypeModel):
    page_index: Annotated[int | None, Field(ge=0)]
    runtime_page_index: Annotated[int | None, Field(ge=0)]
    page: PrototypePageV1 | None
    navigation_items: Annotated[list[IndexedNavigationItemV1], Field(max_length=20)]
    view_bindings: Annotated[list[IndexedRuntimeViewBindingV1], Field(max_length=200)]
    rules: Annotated[list[IndexedRuntimeRuleV1], Field(max_length=100)]
    flows: Annotated[list[IndexedPrototypeFlowV1], Field(max_length=100)]
    flow_layout_positions: Annotated[
        list[RuntimeFlowNodePositionV1],
        Field(max_length=FLOW_LAYOUT_NODE_LIMIT),
    ]

    @model_validator(mode="after")
    def validate_snapshot(self) -> PageProjectionSnapshotV1:
        collections = (
            self.navigation_items,
            self.view_bindings,
            self.rules,
            self.flows,
            self.flow_layout_positions,
        )
        if self.page is None:
            if (
                self.page_index is not None
                or self.runtime_page_index is not None
                or any(collections)
            ):
                raise ValueError("an absent page snapshot cannot contain projections")
            return self
        if self.page_index is None or self.runtime_page_index is None:
            raise ValueError("a page snapshot requires document and runtime indexes")
        for entries, label in (
            (self.navigation_items, "navigation item"),
            (self.view_bindings, "view binding"),
            (self.rules, "runtime rule"),
            (self.flows, "flow"),
        ):
            indexes = [entry.index for entry in entries]
            _unique((str(index) for index in indexes), f"page snapshot {label} index")
            if indexes != sorted(indexes):
                raise ValueError(f"page snapshot {label} indexes must be ascending")
        page_node_ids = _node_id_set(self.page.root)
        if any(entry.item.target_page_id != self.page.id for entry in self.navigation_items):
            raise ValueError("page snapshot contains navigation for another page")
        if any(entry.binding.node_id not in page_node_ids for entry in self.view_bindings):
            raise ValueError("page snapshot contains a view binding owned by another page")
        rule_ids = {entry.rule.id for entry in self.rules}
        if any(entry.rule.trigger.node_id not in page_node_ids for entry in self.rules):
            raise ValueError("page snapshot contains a runtime rule owned by another page")
        if any(entry.flow.rule_id not in rule_ids for entry in self.flows):
            raise ValueError("page snapshot contains a flow owned by another page")
        layout_ids = [position.node_id for position in self.flow_layout_positions]
        _unique(layout_ids, "page snapshot flow layout node ID")
        if any(node_id not in rule_ids | {self.page.id} for node_id in layout_ids):
            raise ValueError("page snapshot contains a flow layout node owned by another page")
        if layout_ids != sorted(layout_ids):
            raise ValueError("page snapshot flow layout nodes must use canonical nodeId order")
        return self


class RestorePageProjectionCommandV1(StrictPrototypeModel):
    kind: Literal["restorePageProjection"]
    page_id: EntityId
    snapshot: PageProjectionSnapshotV1

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> RestorePageProjectionCommandV1:
        if self.snapshot.page is not None and self.snapshot.page.id != self.page_id:
            raise ValueError("page snapshot identity does not match its restore command")
        return self


class BehaviorRuleProjectionSnapshotV1(StrictPrototypeModel):
    rule_index: Annotated[int | None, Field(ge=0)]
    rule: RuntimeRuleV1 | None
    flows: Annotated[list[IndexedPrototypeFlowV1], Field(max_length=100)]
    flow_layout_position: RuntimeFlowNodePositionV1 | None

    @model_validator(mode="after")
    def validate_snapshot(self) -> BehaviorRuleProjectionSnapshotV1:
        if self.rule is None:
            if self.rule_index is not None or self.flows or self.flow_layout_position is not None:
                raise ValueError("an absent behavior rule snapshot cannot contain projections")
            return self
        if self.rule_index is None:
            raise ValueError("a behavior rule snapshot requires its original rule index")
        flow_indices = [entry.index for entry in self.flows]
        _unique((str(index) for index in flow_indices), "behavior rule flow snapshot index")
        if flow_indices != sorted(flow_indices):
            raise ValueError("behavior rule flow snapshots must use ascending global indexes")
        if any(entry.flow.rule_id != self.rule.id for entry in self.flows):
            raise ValueError("behavior rule flow snapshot contains another rule projection")
        if (
            self.flow_layout_position is not None
            and self.flow_layout_position.node_id != self.rule.id
        ):
            raise ValueError("behavior rule layout snapshot contains another projection node")
        return self


class RestoreBehaviorRuleProjectionCommandV1(StrictPrototypeModel):
    kind: Literal["restoreBehaviorRuleProjection"]
    rule_id: EntityId
    snapshot: BehaviorRuleProjectionSnapshotV1

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> RestoreBehaviorRuleProjectionCommandV1:
        if self.snapshot.rule is not None and self.snapshot.rule.id != self.rule_id:
            raise ValueError("behavior rule snapshot identity does not match its restore command")
        return self


type InverseCommandV1 = Annotated[
    MoveNodeCommandV1
    | RemoveNodeCommandV1
    | RestoreNodeNameCommandV1
    | SetNodePropertyCommandV1
    | SetNodeLayoutCommandV1
    | ReorderPageCommandV1
    | ReorderNavigationItemCommandV1
    | SetRuntimeEntityFieldCommandV1
    | RestoreNodeCommandV1
    | RestoreRuntimeFlowNodePositionCommandV1
    | RemoveRuntimeFlowNodePositionCommandV1
    | RestoreBehaviorRuleProjectionCommandV1
    | RestorePageTitleProjectionCommandV1
    | RestorePageProjectionCommandV1,
    Field(discriminator="kind"),
]


class InverseCommandBatchV1(StrictPrototypeModel):
    command_contract_version: Literal[1]
    commands: Annotated[list[InverseCommandV1], Field(min_length=1, max_length=100)]


class CommandHistoryEntryV1(StrictPrototypeModel):
    batch_id: EntityId
    envelope_hash: Sha256


class CommandHistoryCheckpointV1(StrictPrototypeModel):
    schema_version: Literal[1]
    draft_id: EntityId
    checkpoint_sequence_no: Annotated[int, Field(ge=0)]
    checkpoint_document_hash: Sha256
    journal_prefix_hash: Sha256
    undo_stack: list[CommandHistoryEntryV1]
    redo_stack: list[CommandHistoryEntryV1]

    @model_validator(mode="after")
    def validate_history_stacks(self) -> CommandHistoryCheckpointV1:
        entries = [*self.undo_stack, *self.redo_stack]
        _unique((entry.batch_id for entry in entries), "command history batch ID")
        if len(entries) > self.checkpoint_sequence_no:
            raise ValueError("command history stack depth exceeds its checkpoint sequence")
        return self


class _InitialJournalPrefixV1(StrictPrototypeModel):
    journal_prefix_contract_version: Literal[1]
    kind: Literal["initial"]
    draft_id: EntityId


class _JournalPrefixAdvanceV1(StrictPrototypeModel):
    journal_prefix_contract_version: Literal[1]
    kind: Literal["batch"]
    previous_prefix_hash: Sha256
    batch_id: EntityId
    base_sequence_no: Annotated[int, Field(ge=0)]
    result_sequence_no: Annotated[int, Field(ge=1)]
    envelope_hash: Sha256
    base_document_hash: Sha256
    result_document_hash: Sha256

    @model_validator(mode="after")
    def validate_sequence(self) -> _JournalPrefixAdvanceV1:
        if self.result_sequence_no != self.base_sequence_no + 1:
            raise ValueError("journal prefix batch sequence must advance by exactly one")
        return self


@dataclass(frozen=True, slots=True)
class CommandExecutionResultV1:
    document: PrototypeDocumentV1
    inverse_commands: InverseCommandBatchV1
    allocated_entity_ids: tuple[tuple[str, str], ...]
    affected_entity_ids: tuple[str, ...]
    base_document_hash: str
    result_document_hash: str


def document_payload(document: PrototypeDocumentV1) -> dict[str, object]:
    return document.model_dump(mode="json", by_alias=True)


def document_hash(document: PrototypeDocumentV1) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(canonical_json_bytes(document_payload(document))).hexdigest()}"


def freeform_grid_list_hash(grids: Iterable[FreeformGridV1]) -> str:
    import hashlib

    wire = [grid.model_dump(mode="json", by_alias=True) for grid in grids]
    return f"sha256:{hashlib.sha256(canonical_json_bytes(wire)).hexdigest()}"


def _command_evidence_mismatch(message: str) -> StructuredPrototypeContractError:
    return StructuredPrototypeContractError("command_evidence_mismatch", message)


def validate_command_batch_evidence_context(
    document: PrototypeDocumentV1,
    batch: DomainCommandBatchV1,
    *,
    draft_id: str,
    base_head_sequence_no: int,
    base_document_hash: str,
) -> None:
    evidence = batch.evidence
    if evidence is None:
        return

    actual_document_hash = document_hash(document)
    if actual_document_hash != base_document_hash:
        raise _command_evidence_mismatch(
            "freeform move evidence base document does not match its materialized hash"
        )
    if evidence.document_id != document.id:
        raise _command_evidence_mismatch(
            "freeform move evidence documentId does not match the base document"
        )
    if evidence.draft_id != draft_id:
        raise _command_evidence_mismatch(
            "freeform move evidence draftId does not match the base draft"
        )
    if evidence.base_head_sequence_no != base_head_sequence_no:
        raise _command_evidence_mismatch(
            "freeform move evidence baseHeadSequenceNo does not match the base draft head"
        )
    if evidence.base_document_hash != base_document_hash:
        raise _command_evidence_mismatch(
            "freeform move evidence baseDocumentHash does not match the base draft head"
        )

    container: UINodeV1 | None = None
    for page in document.pages:
        container = _find_node(page.root, evidence.freeform_id)
        if container is not None:
            break
    if not isinstance(container, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        raise _command_evidence_mismatch(
            "freeform move evidence freeformId does not identify a positioned container"
        )

    captured_grid_wire = [grid.model_dump(mode="json", by_alias=True) for grid in evidence.grids]
    base_grids = container.grids if isinstance(container, FreeformNodeV1) else []
    base_grid_wire = [grid.model_dump(mode="json", by_alias=True) for grid in base_grids]
    if not isinstance(container, FreeformNodeV1) and evidence.grid_snapping_enabled:
        raise _command_evidence_mismatch(
            "freeform move evidence cannot enable grid snapping for an ordinary container"
        )
    if captured_grid_wire != base_grid_wire:
        raise _command_evidence_mismatch(
            "freeform move evidence grids do not exactly match the base container grid order"
        )
    if freeform_grid_list_hash(evidence.grids) != evidence.grid_list_hash:
        raise _command_evidence_mismatch(
            "freeform move evidence gridListHash does not match its canonical grid array"
        )

    children_by_id = {child.id: (index, child) for index, child in enumerate(container.children)}
    selected_positions: list[FreeformPositionV1] = []
    for node_id in evidence.selected_node_ids:
        selected_child = children_by_id.get(node_id)
        if selected_child is None:
            raise _command_evidence_mismatch(
                "freeform move evidence selected node is not a direct child of its container"
            )
        selected_position = selected_child[1].layout_item.position
        if selected_position is None:
            raise _command_evidence_mismatch(
                "freeform move evidence selected node is not positioned"
            )
        selected_positions.append(selected_position)
    if not _freeform_move_evidence_decimals_match(
        Decimal(evidence.selection_bounds.x),
        min(Decimal(position.x) for position in selected_positions),
    ) or not _freeform_move_evidence_decimals_match(
        Decimal(evidence.selection_bounds.y),
        min(Decimal(position.y) for position in selected_positions),
    ):
        raise _command_evidence_mismatch(
            "freeform move evidence selectionBounds origin does not match the base selection"
        )
    for sibling in evidence.direct_siblings:
        direct_child = children_by_id.get(sibling.node_id)
        if direct_child is None:
            raise _command_evidence_mismatch(
                "freeform move evidence sibling is not a direct child of its container"
            )
        position = direct_child[1].layout_item.position
        if position is None or position.x != sibling.x or position.y != sibling.y:
            raise _command_evidence_mismatch(
                "freeform move evidence sibling position does not match the base document"
            )

    expected_raw_x = Decimal(evidence.selection_bounds.x) + Decimal(evidence.requested_delta.x)
    expected_raw_y = Decimal(evidence.selection_bounds.y) + Decimal(evidence.requested_delta.y)
    if not _freeform_move_evidence_decimals_match(
        Decimal(evidence.raw_position.x),
        expected_raw_x,
    ) or not _freeform_move_evidence_decimals_match(
        Decimal(evidence.raw_position.y),
        expected_raw_y,
    ):
        raise _command_evidence_mismatch(
            "freeform move evidence rawPosition does not equal selection origin plus requestedDelta"
        )

    rigid_delta_x = Decimal(evidence.final_position.x) - Decimal(evidence.selection_bounds.x)
    rigid_delta_y = Decimal(evidence.final_position.y) - Decimal(evidence.selection_bounds.y)
    for command in batch.commands:
        assert isinstance(command, MoveNodeCommandV1)
        assert isinstance(command.node, ExistingNodeRefV1)
        assert command.target_position is not None
        original_index, base_node = children_by_id[command.node.node_id]
        if command.target_index != original_index:
            raise _command_evidence_mismatch(
                "freeform move evidence targetIndex must preserve the base child order"
            )
        base_position = base_node.layout_item.position
        assert base_position is not None
        expected_target_x = Decimal(base_position.x) + rigid_delta_x
        expected_target_y = Decimal(base_position.y) + rigid_delta_y
        if not _freeform_move_evidence_decimals_match(
            Decimal(command.target_position.x),
            expected_target_x,
        ) or not _freeform_move_evidence_decimals_match(
            Decimal(command.target_position.y),
            expected_target_y,
        ):
            raise _command_evidence_mismatch(
                "freeform move command targetPosition does not preserve the captured rigid delta"
            )


def canonical_model_json(model: StrictPrototypeModel) -> str:
    return canonical_json_bytes(model.model_dump(mode="json", by_alias=True)).decode("utf-8")


def command_history_checkpoint_payload(
    checkpoint: CommandHistoryCheckpointV1,
) -> dict[str, object]:
    return checkpoint.model_dump(mode="json", by_alias=True)


def canonical_command_history_checkpoint_json(
    checkpoint: CommandHistoryCheckpointV1,
) -> str:
    return canonical_json_bytes(command_history_checkpoint_payload(checkpoint)).decode("utf-8")


def parse_command_history_checkpoint_json(payload: bytes | str) -> CommandHistoryCheckpointV1:
    try:
        return CommandHistoryCheckpointV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "command_history_checkpoint_invalid",
            "prototype command history checkpoint does not satisfy schema version 1",
        ) from exc


def command_history_checkpoint_to_domain(
    checkpoint: CommandHistoryCheckpointV1,
    *,
    snapshot_object_hash: str,
) -> PrototypeCommandHistoryCheckpoint:
    if SHA256_RE.fullmatch(snapshot_object_hash) is None:
        raise StructuredPrototypeContractError(
            "command_history_checkpoint_invalid",
            "prototype command history checkpoint object hash is invalid",
        )
    return PrototypeCommandHistoryCheckpoint(
        draft_id=checkpoint.draft_id,
        checkpoint_sequence_no=checkpoint.checkpoint_sequence_no,
        checkpoint_document_hash=checkpoint.checkpoint_document_hash,
        journal_prefix_hash=checkpoint.journal_prefix_hash,
        history=PrototypeCommandHistory(
            undo_stack=tuple(
                PrototypeCommandHistoryEntry(
                    batch_id=entry.batch_id,
                    command_batch_hash=entry.envelope_hash,
                )
                for entry in checkpoint.undo_stack
            ),
            redo_stack=tuple(
                PrototypeCommandHistoryEntry(
                    batch_id=entry.batch_id,
                    command_batch_hash=entry.envelope_hash,
                )
                for entry in checkpoint.redo_stack
            ),
        ),
        snapshot_object_hash=snapshot_object_hash,
        snapshot_schema_version=checkpoint.schema_version,
    )


def command_history_checkpoint_from_domain(
    checkpoint: PrototypeCommandHistoryCheckpoint,
) -> CommandHistoryCheckpointV1:
    try:
        return CommandHistoryCheckpointV1.model_validate(
            checkpoint.to_payload(),
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "command_history_checkpoint_invalid",
            "prototype command history checkpoint domain state is invalid",
        ) from exc


def initial_journal_prefix_hash(*, draft_id: str) -> str:
    import hashlib

    try:
        payload = _InitialJournalPrefixV1(
            journal_prefix_contract_version=JOURNAL_PREFIX_CONTRACT_VERSION,
            kind="initial",
            draft_id=draft_id,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "journal_prefix_invalid",
            "prototype journal prefix initial identity is invalid",
        ) from exc
    digest = hashlib.sha256(
        canonical_json_bytes(payload.model_dump(mode="json", by_alias=True))
    ).hexdigest()
    return f"sha256:{digest}"


def advance_journal_prefix_hash(
    *,
    previous_prefix_hash: str,
    batch_id: str,
    base_sequence_no: int,
    result_sequence_no: int,
    command_batch_hash: str,
    base_document_hash: str,
    result_document_hash: str,
) -> str:
    import hashlib

    try:
        payload = _JournalPrefixAdvanceV1(
            journal_prefix_contract_version=JOURNAL_PREFIX_CONTRACT_VERSION,
            kind="batch",
            previous_prefix_hash=previous_prefix_hash,
            batch_id=batch_id,
            base_sequence_no=base_sequence_no,
            result_sequence_no=result_sequence_no,
            envelope_hash=command_batch_hash,
            base_document_hash=base_document_hash,
            result_document_hash=result_document_hash,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "journal_prefix_invalid",
            "prototype journal prefix batch evidence is invalid",
        ) from exc
    digest = hashlib.sha256(
        canonical_json_bytes(payload.model_dump(mode="json", by_alias=True))
    ).hexdigest()
    return f"sha256:{digest}"


def parse_prototype_document_json(payload: bytes | str) -> PrototypeDocumentV1:
    try:
        return PrototypeDocumentV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "document_invalid", "prototype document does not satisfy schema version 1"
        ) from exc


def parse_command_batch_json(payload: str) -> DomainCommandBatchV1:
    try:
        return DomainCommandBatchV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "command_batch_invalid", "prototype command batch does not satisfy contract version 1"
        ) from exc


def parse_inverse_command_batch_json(payload: str) -> InverseCommandBatchV1:
    try:
        return InverseCommandBatchV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "inverse_command_batch_invalid",
            "prototype inverse command batch does not satisfy contract version 1",
        ) from exc


def command_batch_hash(batch: DomainCommandBatchV1) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(canonical_json_bytes(batch.model_dump(mode='json', by_alias=True))).hexdigest()}"


def command_batch_envelope_hash(
    *,
    draft_id: str,
    base_sequence_no: int,
    result_sequence_no: int,
    origin: Literal["user", "ai", "system"],
    operation_kind: Literal["forward", "undo", "redo"],
    target_batch_id: str | None,
    commands: DomainCommandBatchV1 | InverseCommandBatchV1,
    inverse_commands: InverseCommandBatchV1,
) -> str:
    import hashlib

    envelope = {
        "commandContractVersion": COMMAND_CONTRACT_VERSION,
        "draftId": draft_id,
        "baseSequenceNo": base_sequence_no,
        "resultSequenceNo": result_sequence_no,
        "origin": origin,
        "operationKind": operation_kind,
        "targetBatchId": target_batch_id,
        "commands": commands.model_dump(mode="json", by_alias=True),
        "inverseCommands": inverse_commands.model_dump(mode="json", by_alias=True),
    }
    return f"sha256:{hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()}"


def execute_command_batch(
    document: PrototypeDocumentV1,
    batch: DomainCommandBatchV1,
    *,
    draft_id: str,
    client_request_id: str,
) -> CommandExecutionResultV1:
    if len(canonical_model_json(batch).encode("utf-8")) > PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES:
        raise StructuredPrototypeContractError(
            "command_batch_too_large",
            "prototype forward command payload exceeds 256 KiB",
        )
    base_hash = document_hash(document)
    current = document
    allocated: dict[str, str] = {}
    inverse: list[InverseCommandV1] = []
    affected: set[str] = set()
    for command in batch.commands:
        try:
            current, command_inverse, command_affected = _execute_command(
                current,
                command,
                draft_id=draft_id,
                client_request_id=client_request_id,
                allocated=allocated,
            )
        except ValidationError as exc:
            raise StructuredPrototypeContractError(
                "command_result_invalid",
                "prototype command would produce an invalid document",
            ) from exc
        inverse.insert(0, command_inverse)
        affected.update(command_affected)
    try:
        current = _validate_command_batch_document(current)
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "command_result_invalid",
            "prototype command would produce an invalid document",
        ) from exc
    serialized_inverse = InverseCommandBatchV1(
        command_contract_version=COMMAND_CONTRACT_VERSION,
        commands=inverse,
    )
    _require_inverse_round_trip(document, current, serialized_inverse)
    return CommandExecutionResultV1(
        document=current,
        inverse_commands=serialized_inverse,
        allocated_entity_ids=tuple(sorted(allocated.items())),
        affected_entity_ids=tuple(sorted(affected)),
        base_document_hash=base_hash,
        result_document_hash=document_hash(current),
    )


def apply_inverse_commands(
    document: PrototypeDocumentV1,
    batch: InverseCommandBatchV1,
) -> PrototypeDocumentV1:
    current = document
    for command in batch.commands:
        current = _apply_inverse_command(current, command)
    return _validate_command_batch_document(current)


def execute_inverse_command_batch(
    document: PrototypeDocumentV1,
    batch: InverseCommandBatchV1,
) -> CommandExecutionResultV1:
    base_hash = document_hash(document)
    current = document
    inverse: list[InverseCommandV1] = []
    affected: set[str] = set()
    for command in batch.commands:
        current, command_inverse, command_affected = _execute_inverse_command(current, command)
        inverse.insert(0, command_inverse)
        affected.update(command_affected)
    current = _validate_command_batch_document(current)
    serialized_inverse = InverseCommandBatchV1(
        command_contract_version=COMMAND_CONTRACT_VERSION,
        commands=inverse,
    )
    _require_inverse_round_trip(document, current, serialized_inverse)
    return CommandExecutionResultV1(
        document=current,
        inverse_commands=serialized_inverse,
        allocated_entity_ids=(),
        affected_entity_ids=tuple(sorted(affected)),
        base_document_hash=base_hash,
        result_document_hash=document_hash(current),
    )


def _require_inverse_round_trip(
    base_document: PrototypeDocumentV1,
    result_document: PrototypeDocumentV1,
    inverse: InverseCommandBatchV1,
) -> None:
    try:
        round_trip = apply_inverse_commands(result_document, inverse)
    except (StructuredPrototypeContractError, ValidationError) as exc:
        raise StructuredPrototypeContractError(
            "inverse_round_trip_mismatch",
            "prototype command inverse cannot restore its exact base document",
        ) from exc
    if canonical_model_json(round_trip) != canonical_model_json(base_document):
        raise StructuredPrototypeContractError(
            "inverse_round_trip_mismatch",
            "prototype command inverse does not round-trip to its exact base document",
        )


def _validate_command_batch_document(
    document: PrototypeDocumentV1,
) -> PrototypeDocumentV1:
    return PrototypeDocumentV1.model_validate(
        document.model_dump(mode="json", by_alias=True),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _execute_command(
    document: PrototypeDocumentV1,
    command: DomainCommandV1,
    *,
    draft_id: str,
    client_request_id: str,
    allocated: dict[str, str],
) -> tuple[PrototypeDocumentV1, InverseCommandV1, set[str]]:
    if isinstance(command, InsertNodeCommandV1):
        parent_id = _resolve_node_ref(command.parent, allocated)
        node = _allocate_new_node(
            command.node,
            draft_id=draft_id,
            client_request_id=client_request_id,
            allocated=allocated,
        )
        updated = _insert_node(document, parent_id, command.index, node)
        return (
            updated,
            RemoveNodeCommandV1(kind="removeNode", node_id=node.id),
            _node_id_set(node) | {parent_id},
        )
    if isinstance(command, MoveNodeCommandV1):
        node_id = _resolve_node_ref(command.node, allocated)
        target_parent_id = _resolve_node_ref(command.target_parent, allocated)
        node, source_parent_id, source_index = _locate_movable_node(document, node_id)
        source_position = node.layout_item.position
        if target_parent_id in _node_id_set(node):
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype node cannot move into its own subtree"
            )
        target_parent = _require_node(document, target_parent_id)
        positioned_node = _position_node_for_parent(
            node,
            target_parent,
            command.target_position,
            target_position_is_set="target_position" in command.model_fields_set,
        )
        without_node, _, _, _ = _detach_node_without_document_validation(document, node_id)
        updated = _insert_node(
            without_node,
            target_parent_id,
            command.target_index,
            positioned_node,
        )
        inverse_move = MoveNodeCommandV1(
            kind="moveNode",
            node=ExistingNodeRefV1(kind="existing", node_id=node_id),
            target_parent=ExistingNodeRefV1(kind="existing", node_id=source_parent_id),
            target_slot=None,
            target_index=source_index,
            target_position=source_position,
        )
        return updated, inverse_move, {node_id, source_parent_id, target_parent_id}
    if isinstance(command, RemoveNodeCommandV1):
        if any(page.root.id == command.node_id for page in document.pages):
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype page root cannot be removed"
            )
        removed_node = _require_node(document, command.node_id)
        _require_node_subtree_unreferenced(document, removed_node)
        updated, removed, parent_id, index = _remove_node(document, command.node_id)
        return (
            updated,
            RestoreNodeCommandV1(
                kind="restoreNode", parent_id=parent_id, index=index, node=removed
            ),
            _node_id_set(removed) | {parent_id},
        )
    if isinstance(command, UpdateNodeNameCommandV1):
        node = _require_node(document, command.node_id)
        updated = _replace_node(document, node.model_copy(update={"name": command.name}))
        return (
            updated,
            RestoreNodeNameCommandV1(
                kind="restoreNodeName",
                node_id=command.node_id,
                name=node.name,
            ),
            {command.node_id},
        )
    if isinstance(command, SetNodePropertyCommandV1):
        node_id = _resolve_node_ref(command.node, allocated)
        node = _require_node(document, node_id)
        updated_node, old_update = _apply_property_update(node, command.update)
        updated = _replace_node(document, updated_node)
        return (
            updated,
            SetNodePropertyCommandV1(
                kind="setNodeProperty",
                node=ExistingNodeRefV1(kind="existing", node_id=node_id),
                update=old_update,
            ),
            {node_id},
        )
    if isinstance(command, SetNodeLayoutCommandV1):
        node_id = _resolve_node_ref(command.node, allocated)
        node = _require_node(document, node_id)
        updated_layout, old_layout = _apply_layout_update(node.layout_item, command.update)
        updated = _replace_node(document, node.model_copy(update={"layout_item": updated_layout}))
        return (
            updated,
            SetNodeLayoutCommandV1(
                kind="setNodeLayout",
                node=ExistingNodeRefV1(kind="existing", node_id=node_id),
                update=old_layout,
            ),
            {node_id},
        )
    if isinstance(command, SetRuntimeEntityFieldCommandV1):
        updated, old_value = _apply_runtime_entity_field_update(document, command)
        return (
            updated,
            SetRuntimeEntityFieldCommandV1(
                kind="setRuntimeEntityField",
                scenario_id=command.scenario_id,
                schema_id=command.schema_id,
                entity_id=command.entity_id,
                field_id=command.field_id,
                value=old_value,
            ),
            {command.scenario_id, command.schema_id, command.entity_id, command.field_id},
        )
    if isinstance(command, SetRuntimeFlowNodePositionCommandV1):
        updated, previous_position = _set_runtime_flow_node_position(
            document,
            node_id=command.flow_node_id,
            x=command.x,
            y=command.y,
        )
        inverse: InverseCommandV1
        if previous_position is None:
            inverse = RemoveRuntimeFlowNodePositionCommandV1(
                kind="removeRuntimeFlowNodePosition",
                flow_node_id=command.flow_node_id,
            )
        else:
            inverse = RestoreRuntimeFlowNodePositionCommandV1(
                kind="restoreRuntimeFlowNodePosition",
                flow_node_id=previous_position.node_id,
                x=previous_position.x,
                y=previous_position.y,
            )
        return updated, inverse, {command.flow_node_id}
    if isinstance(command, AddBehaviorRuleCommandV1):
        if command.new_rule_key in allocated:
            raise StructuredPrototypeContractError(
                "command_new_key_duplicate",
                "prototype new behavior-rule key is duplicated in the batch",
            )
        rule_id = str(
            uuid5(
                PROTOTYPE_ENTITY_NAMESPACE,
                f"{draft_id}:{client_request_id}:rule:{command.new_rule_key}",
            )
        )
        allocated[command.new_rule_key] = rule_id
        rule = _materialize_behavior_rule(rule_id, command.definition)
        updated = _add_behavior_rule(document, rule)
        _register_allocated_behavior_flows(
            document,
            updated,
            rule_id=rule_id,
            allocated=allocated,
        )
        inverse = RestoreBehaviorRuleProjectionCommandV1(
            kind="restoreBehaviorRuleProjection",
            rule_id=rule_id,
            snapshot=BehaviorRuleProjectionSnapshotV1(
                rule_index=None,
                rule=None,
                flows=[],
                flow_layout_position=None,
            ),
        )
        return updated, inverse, _behavior_rule_projection_entity_ids(updated, rule_id)
    if isinstance(command, ReplaceBehaviorRuleCommandV1):
        previous_snapshot = _capture_behavior_rule_projection(document, command.rule_id)
        replacement = _materialize_behavior_rule(command.rule_id, command.definition)
        updated = _replace_behavior_rule(document, replacement)
        _register_allocated_behavior_flows(
            document,
            updated,
            rule_id=command.rule_id,
            allocated=allocated,
        )
        affected = _behavior_rule_snapshot_entity_ids(previous_snapshot)
        affected.update(_behavior_rule_projection_entity_ids(updated, command.rule_id))
        return (
            updated,
            RestoreBehaviorRuleProjectionCommandV1(
                kind="restoreBehaviorRuleProjection",
                rule_id=command.rule_id,
                snapshot=previous_snapshot,
            ),
            affected,
        )
    if isinstance(command, RemoveBehaviorRuleCommandV1):
        previous_snapshot = _capture_behavior_rule_projection(document, command.rule_id)
        updated = _restore_behavior_rule_projection(
            document,
            command.rule_id,
            BehaviorRuleProjectionSnapshotV1(
                rule_index=None,
                rule=None,
                flows=[],
                flow_layout_position=None,
            ),
        )
        return (
            updated,
            RestoreBehaviorRuleProjectionCommandV1(
                kind="restoreBehaviorRuleProjection",
                rule_id=command.rule_id,
                snapshot=previous_snapshot,
            ),
            _behavior_rule_snapshot_entity_ids(previous_snapshot),
        )
    if isinstance(command, AddPageCommandV1):
        updated, page_id = _add_blank_page(
            document,
            command,
            draft_id=draft_id,
            client_request_id=client_request_id,
            allocated=allocated,
        )
        affected = _page_projection_entity_ids(_capture_page_projection(updated, page_id))
        affected.add(command.after_page_id)
        return (
            updated,
            RestorePageProjectionCommandV1(
                kind="restorePageProjection",
                page_id=page_id,
                snapshot=_absent_page_projection_snapshot(),
            ),
            affected,
        )
    if isinstance(command, DuplicatePageCommandV1):
        updated, page_id = _duplicate_page(
            document,
            command,
            draft_id=draft_id,
            client_request_id=client_request_id,
            allocated=allocated,
        )
        affected = _page_projection_entity_ids(_capture_page_projection(updated, page_id))
        affected.add(command.page_id)
        return (
            updated,
            RestorePageProjectionCommandV1(
                kind="restorePageProjection",
                page_id=page_id,
                snapshot=_absent_page_projection_snapshot(),
            ),
            affected,
        )
    if isinstance(command, RenamePageCommandV1):
        previous_title_snapshot = _capture_page_title_projection(document, command.page_id)
        updated, affected = _rename_page(
            document,
            page_id=command.page_id,
            title=command.title,
        )
        return (
            updated,
            RestorePageTitleProjectionCommandV1(
                kind="restorePageTitleProjection",
                page_id=command.page_id,
                snapshot=previous_title_snapshot,
            ),
            affected,
        )
    if isinstance(command, DeletePageCommandV1):
        _require_page_deletable(document, command.page_id)
        snapshot = _capture_page_projection(document, command.page_id)
        updated = _restore_page_projection(
            document,
            command.page_id,
            _absent_page_projection_snapshot(),
        )
        return (
            updated,
            RestorePageProjectionCommandV1(
                kind="restorePageProjection",
                page_id=command.page_id,
                snapshot=snapshot,
            ),
            _page_projection_entity_ids(snapshot),
        )
    if isinstance(command, ReorderPageCommandV1):
        pages = list(document.pages)
        page_source_index = next(
            (index for index, page in enumerate(pages) if page.id == command.page_id), None
        )
        if page_source_index is None:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype page does not exist"
            )
        page = pages.pop(page_source_index)
        if command.target_index > len(pages):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype page target index is out of range"
            )
        pages.insert(command.target_index, page)
        runtime_page_ids = list(document.runtime.page_ids)
        runtime_page_id = runtime_page_ids.pop(page_source_index)
        runtime_page_ids.insert(command.target_index, runtime_page_id)
        runtime = document.runtime.model_copy(update={"page_ids": runtime_page_ids})
        updated = document.model_copy(update={"pages": pages, "runtime": runtime})
        return (
            updated,
            ReorderPageCommandV1(
                kind="reorderPage",
                page_id=command.page_id,
                target_index=page_source_index,
            ),
            {command.page_id},
        )
    if isinstance(command, ReorderNavigationItemCommandV1):
        items = list(document.navigation.items)
        item_source_index = next(
            (index for index, item in enumerate(items) if item.id == command.item_id), None
        )
        if item_source_index is None:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype navigation item does not exist"
            )
        item = items.pop(item_source_index)
        if command.target_index > len(items):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype navigation item target index is out of range"
            )
        items.insert(command.target_index, item)
        navigation = document.navigation.model_copy(update={"items": items})
        updated = document.model_copy(update={"navigation": navigation})
        return (
            updated,
            ReorderNavigationItemCommandV1(
                kind="reorderNavigationItem",
                item_id=command.item_id,
                target_index=item_source_index,
            ),
            {command.item_id},
        )
    raise AssertionError("unreachable domain command variant")


def _execute_inverse_command(
    document: PrototypeDocumentV1,
    command: InverseCommandV1,
) -> tuple[PrototypeDocumentV1, InverseCommandV1, set[str]]:
    if isinstance(command, RestoreNodeNameCommandV1):
        node = _require_node(document, command.node_id)
        updated = _replace_node(document, node.model_copy(update={"name": command.name}))
        return (
            updated,
            RestoreNodeNameCommandV1(
                kind="restoreNodeName",
                node_id=command.node_id,
                name=node.name,
            ),
            {command.node_id},
        )
    if isinstance(command, RestoreNodeCommandV1):
        updated = _insert_node(document, command.parent_id, command.index, command.node)
        return (
            updated,
            RemoveNodeCommandV1(kind="removeNode", node_id=command.node.id),
            _node_id_set(command.node) | {command.parent_id},
        )
    if isinstance(command, RestoreRuntimeFlowNodePositionCommandV1):
        updated, previous_position = _set_runtime_flow_node_position(
            document,
            node_id=command.flow_node_id,
            x=command.x,
            y=command.y,
        )
        inverse: InverseCommandV1
        if previous_position is None:
            inverse = RemoveRuntimeFlowNodePositionCommandV1(
                kind="removeRuntimeFlowNodePosition",
                flow_node_id=command.flow_node_id,
            )
        else:
            inverse = RestoreRuntimeFlowNodePositionCommandV1(
                kind="restoreRuntimeFlowNodePosition",
                flow_node_id=previous_position.node_id,
                x=previous_position.x,
                y=previous_position.y,
            )
        return updated, inverse, {command.flow_node_id}
    if isinstance(command, RemoveRuntimeFlowNodePositionCommandV1):
        updated, removed = _remove_runtime_flow_node_position(document, command.flow_node_id)
        return (
            updated,
            RestoreRuntimeFlowNodePositionCommandV1(
                kind="restoreRuntimeFlowNodePosition",
                flow_node_id=removed.node_id,
                x=removed.x,
                y=removed.y,
            ),
            {command.flow_node_id},
        )
    if isinstance(command, RestoreBehaviorRuleProjectionCommandV1):
        previous_snapshot = _capture_behavior_rule_projection(
            document,
            command.rule_id,
            allow_absent=True,
        )
        updated = _restore_behavior_rule_projection(
            document,
            command.rule_id,
            command.snapshot,
        )
        affected = _behavior_rule_snapshot_entity_ids(
            previous_snapshot,
            rule_id=command.rule_id,
        )
        affected.update(
            _behavior_rule_snapshot_entity_ids(command.snapshot, rule_id=command.rule_id)
        )
        return (
            updated,
            RestoreBehaviorRuleProjectionCommandV1(
                kind="restoreBehaviorRuleProjection",
                rule_id=command.rule_id,
                snapshot=previous_snapshot,
            ),
            affected,
        )
    if isinstance(command, RestorePageProjectionCommandV1):
        previous_page_snapshot = _capture_page_projection(
            document,
            command.page_id,
            allow_absent=True,
        )
        updated = _restore_page_projection(document, command.page_id, command.snapshot)
        affected = _page_projection_entity_ids(
            previous_page_snapshot,
            page_id=command.page_id,
        )
        affected.update(_page_projection_entity_ids(command.snapshot, page_id=command.page_id))
        return (
            updated,
            RestorePageProjectionCommandV1(
                kind="restorePageProjection",
                page_id=command.page_id,
                snapshot=previous_page_snapshot,
            ),
            affected,
        )
    if isinstance(command, RestorePageTitleProjectionCommandV1):
        previous_title_snapshot = _capture_page_title_projection(document, command.page_id)
        updated, affected = _restore_page_title_projection(
            document,
            command.page_id,
            command.snapshot,
        )
        return (
            updated,
            RestorePageTitleProjectionCommandV1(
                kind="restorePageTitleProjection",
                page_id=command.page_id,
                snapshot=previous_title_snapshot,
            ),
            affected,
        )
    return _execute_command(
        document,
        command,
        draft_id="",
        client_request_id="",
        allocated={},
    )


def _apply_inverse_command(
    document: PrototypeDocumentV1,
    command: InverseCommandV1,
) -> PrototypeDocumentV1:
    if isinstance(command, RestoreNodeCommandV1):
        return _insert_node(document, command.parent_id, command.index, command.node)
    if isinstance(command, RemoveNodeCommandV1):
        return _remove_node(document, command.node_id)[0]
    if isinstance(command, RestoreNodeNameCommandV1):
        node = _require_node(document, command.node_id)
        return _replace_node(document, node.model_copy(update={"name": command.name}))
    if isinstance(command, MoveNodeCommandV1):
        node_id = _existing_ref_id(command.node)
        parent_id = _existing_ref_id(command.target_parent)
        node = _require_node(document, node_id)
        target_parent = _require_node(document, parent_id)
        positioned_node = _position_node_for_parent(
            node,
            target_parent,
            command.target_position,
            target_position_is_set="target_position" in command.model_fields_set,
        )
        without_node, _, _, _ = _detach_node_without_document_validation(document, node_id)
        return _insert_node(without_node, parent_id, command.target_index, positioned_node)
    if isinstance(command, SetNodePropertyCommandV1):
        node_id = _existing_ref_id(command.node)
        node, _ = _apply_property_update(_require_node(document, node_id), command.update)
        return _replace_node(document, node)
    if isinstance(command, SetNodeLayoutCommandV1):
        node_id = _existing_ref_id(command.node)
        node = _require_node(document, node_id)
        layout, _ = _apply_layout_update(node.layout_item, command.update)
        return _replace_node(document, node.model_copy(update={"layout_item": layout}))
    if isinstance(command, SetRuntimeEntityFieldCommandV1):
        return _apply_runtime_entity_field_update(document, command)[0]
    if isinstance(command, RestoreRuntimeFlowNodePositionCommandV1):
        return _set_runtime_flow_node_position(
            document,
            node_id=command.flow_node_id,
            x=command.x,
            y=command.y,
        )[0]
    if isinstance(command, RemoveRuntimeFlowNodePositionCommandV1):
        return _remove_runtime_flow_node_position(document, command.flow_node_id)[0]
    if isinstance(command, RestoreBehaviorRuleProjectionCommandV1):
        return _restore_behavior_rule_projection(document, command.rule_id, command.snapshot)
    if isinstance(command, RestorePageProjectionCommandV1):
        return _restore_page_projection(document, command.page_id, command.snapshot)
    if isinstance(command, RestorePageTitleProjectionCommandV1):
        return _restore_page_title_projection(
            document,
            command.page_id,
            command.snapshot,
        )[0]
    if isinstance(command, ReorderPageCommandV1):
        pages = list(document.pages)
        source_index = next(
            (index for index, page in enumerate(pages) if page.id == command.page_id), None
        )
        if source_index is None:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype page does not exist"
            )
        page = pages.pop(source_index)
        if command.target_index > len(pages):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype page target index is out of range"
            )
        pages.insert(command.target_index, page)
        runtime_page_ids = list(document.runtime.page_ids)
        runtime_page_id = runtime_page_ids.pop(source_index)
        runtime_page_ids.insert(command.target_index, runtime_page_id)
        runtime = document.runtime.model_copy(update={"page_ids": runtime_page_ids})
        return document.model_copy(update={"pages": pages, "runtime": runtime})
    if isinstance(command, ReorderNavigationItemCommandV1):
        items = list(document.navigation.items)
        source_index = next(
            (index for index, item in enumerate(items) if item.id == command.item_id), None
        )
        if source_index is None:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype navigation item does not exist"
            )
        item = items.pop(source_index)
        if command.target_index > len(items):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype navigation item target index is out of range"
            )
        items.insert(command.target_index, item)
        navigation = document.navigation.model_copy(update={"items": items})
        return document.model_copy(update={"navigation": navigation})
    raise AssertionError("unreachable inverse command variant")


def _resolve_node_ref(reference: NodeRefV1, allocated: dict[str, str]) -> str:
    if isinstance(reference, ExistingNodeRefV1):
        return reference.node_id
    node_id = allocated.get(reference.new_node_key)
    if node_id is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype new-node reference has not been allocated"
        )
    return node_id


def _existing_ref_id(reference: NodeRefV1) -> str:
    if not isinstance(reference, ExistingNodeRefV1):
        raise StructuredPrototypeContractError(
            "inverse_command_invalid", "persisted inverse must use existing node references"
        )
    return reference.node_id


def _allocate_new_node(
    node: NewUINodeV1,
    *,
    draft_id: str,
    client_request_id: str,
    allocated: dict[str, str],
) -> UINodeV1:
    if node.new_node_key in allocated:
        raise StructuredPrototypeContractError(
            "command_new_key_duplicate", "prototype new-node key is duplicated in the batch"
        )
    node_id = str(
        uuid5(
            PROTOTYPE_ENTITY_NAMESPACE,
            f"{draft_id}:{client_request_id}:node:{node.new_node_key}",
        )
    )
    allocated[node.new_node_key] = node_id
    payload = node.model_dump(mode="python", by_alias=True)
    payload.pop("newNodeKey")
    if isinstance(
        node,
        (NewStackNodeV1, NewGridNodeV1, NewFormNodeV1, NewFreeformNodeV1),
    ):
        payload["children"] = [
            _allocate_new_node(
                child,
                draft_id=draft_id,
                client_request_id=client_request_id,
                allocated=allocated,
            )
            for child in node.children
        ]
    payload["id"] = node_id
    if isinstance(node, NewStackNodeV1):
        return StackNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewGridNodeV1):
        return GridNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewFormNodeV1):
        return FormNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewFreeformNodeV1):
        return FreeformNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewTextNodeV1):
        return TextNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewInputNodeV1):
        return InputNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewButtonNodeV1):
        return ButtonNodeV1.model_validate(payload, strict=True)
    return TableNodeV1.model_validate(payload, strict=True)


def _register_allocated_entity(
    allocated: dict[str, str],
    allocation_key: str,
    entity_id: str,
) -> str:
    if allocation_key in allocated:
        raise StructuredPrototypeContractError(
            "command_new_key_duplicate",
            "prototype page allocation key is duplicated in the batch",
        )
    allocated[allocation_key] = entity_id
    return entity_id


def _allocate_page_id(
    *,
    draft_id: str,
    client_request_id: str,
    new_page_key: str,
    allocated: dict[str, str],
) -> str:
    page_id = str(
        uuid5(
            PROTOTYPE_ENTITY_NAMESPACE,
            f"{draft_id}:{client_request_id}:page:{new_page_key}",
        )
    )
    return _register_allocated_entity(allocated, new_page_key, page_id)


def _allocate_page_owned_id(
    page_id: str,
    *,
    allocation_key: str,
    identity: str,
    allocated: dict[str, str],
) -> str:
    entity_id = str(uuid5(UUID(page_id), identity))
    return _register_allocated_entity(allocated, allocation_key, entity_id)


def _technical_key_base(value: str, *, fallback: str = "page") -> str:
    lowered = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"{fallback}-{normalized}" if normalized else fallback
    normalized = normalized[:64].rstrip("-")
    return normalized or fallback


def _unique_technical_key(base: str, existing: set[str]) -> str:
    normalized = _technical_key_base(base)
    if normalized not in existing:
        return normalized
    suffix_no = 2
    while True:
        suffix = f"-{suffix_no}"
        candidate = f"{normalized[: 64 - len(suffix)].rstrip('-')}{suffix}"
        if candidate not in existing:
            return candidate
        suffix_no += 1


def _unique_route(base: str, existing: set[str]) -> str:
    normalized = base if base.startswith("/") else f"/{base}"
    if normalized == "/":
        normalized = "/page"
    normalized = normalized[:240].rstrip("/") or "/page"
    if normalized not in existing:
        return normalized
    suffix_no = 2
    while True:
        suffix = f"-{suffix_no}"
        candidate = f"{normalized[: 240 - len(suffix)]}{suffix}"
        if candidate not in existing:
            return candidate
        suffix_no += 1


def _duplicate_route_base(route: str) -> str:
    return "/copy" if route == "/" else f"{route}-copy"


def _blank_freeform_root(
    *,
    page_id: str,
    new_page_key: str,
    title: str,
    viewport: ViewportSettingsV1,
    allocated: dict[str, str],
) -> FreeformNodeV1:
    root_id = _allocate_page_owned_id(
        page_id,
        allocation_key=f"{new_page_key}:root",
        identity="root",
        allocated=allocated,
    )
    return FreeformNodeV1(
        id=root_id,
        type="Freeform",
        name=title,
        visibility="visible",
        layout_item=LayoutItemV1(
            width=LengthV1(unit="px", value=str(viewport.width)),
            min_width=None,
            max_width=None,
            height=LengthV1(unit="px", value=str(viewport.height)),
            min_height=None,
            max_height=None,
            grow=0,
            shrink=0,
            align_self="stretch",
            position=None,
        ),
        responsive=[],
        children=[],
        grids=[],
    )


def _add_blank_page(
    document: PrototypeDocumentV1,
    command: AddPageCommandV1,
    *,
    draft_id: str,
    client_request_id: str,
    allocated: dict[str, str],
) -> tuple[PrototypeDocumentV1, str]:
    pages = list(document.pages)
    source_index = next(
        (index for index, page in enumerate(pages) if page.id == command.after_page_id),
        None,
    )
    if source_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page insertion anchor does not exist"
        )
    page_id = _allocate_page_id(
        draft_id=draft_id,
        client_request_id=client_request_id,
        new_page_key=command.new_page_key,
        allocated=allocated,
    )
    page_key = _unique_technical_key(
        command.title,
        {page.key for page in document.pages},
    )
    route = _unique_route(
        f"/{page_key}",
        {page.route for page in document.pages},
    )
    viewport = pages[source_index].viewport
    page = PrototypePageV1(
        id=page_id,
        key=page_key,
        title=command.title,
        route=route,
        viewport=viewport,
        root=_blank_freeform_root(
            page_id=page_id,
            new_page_key=command.new_page_key,
            title=command.title,
            viewport=viewport,
            allocated=allocated,
        ),
    )
    insertion_index = source_index + 1
    pages.insert(insertion_index, page)
    runtime_page_ids = list(document.runtime.page_ids)
    runtime_page_ids.insert(insertion_index, page_id)
    navigation_items = list(document.navigation.items)
    if command.include_in_navigation:
        navigation_id = _allocate_page_owned_id(
            page_id,
            allocation_key=f"{command.new_page_key}:navigation",
            identity="navigation",
            allocated=allocated,
        )
        navigation_key = _unique_technical_key(
            page_key,
            {item.key for item in navigation_items},
        )
        anchor_indexes = [
            index
            for index, item in enumerate(navigation_items)
            if item.target_page_id == command.after_page_id
        ]
        navigation_index = anchor_indexes[-1] + 1 if anchor_indexes else len(navigation_items)
        navigation_items.insert(
            navigation_index,
            NavigationItemV1(
                id=navigation_id,
                key=navigation_key,
                label=command.title,
                target_page_id=page_id,
            ),
        )
    runtime = document.runtime.model_copy(update={"page_ids": runtime_page_ids})
    navigation = document.navigation.model_copy(update={"items": navigation_items})
    updated = document.model_copy(
        update={"pages": pages, "runtime": runtime, "navigation": navigation}
    )
    return _validate_command_batch_document(updated), page_id


def _duplicate_page_node(
    node: UINodeV1,
    *,
    page_id: str,
    new_page_key: str,
    allocated: dict[str, str],
    node_id_map: dict[str, str],
) -> UINodeV1:
    new_node_id = _allocate_page_owned_id(
        page_id,
        allocation_key=f"{new_page_key}:node:{node.id}",
        identity=f"node:{node.id}",
        allocated=allocated,
    )
    node_id_map[node.id] = new_node_id
    updates: dict[str, object] = {"id": new_node_id}
    children = _node_children(node)
    if children is not None:
        updates["children"] = [
            _duplicate_page_node(
                child,
                page_id=page_id,
                new_page_key=new_page_key,
                allocated=allocated,
                node_id_map=node_id_map,
            )
            for child in children
        ]
    if isinstance(node, FreeformNodeV1):
        updates["grids"] = [
            grid.model_copy(
                update={
                    "id": _allocate_page_owned_id(
                        page_id,
                        allocation_key=f"{new_page_key}:grid:{grid.id}",
                        identity=f"grid:{grid.id}",
                        allocated=allocated,
                    )
                }
            )
            for grid in node.grids
        ]
    if isinstance(node, TableNodeV1):
        updates["rows"] = [
            row.model_copy(
                update={
                    "id": _allocate_page_owned_id(
                        page_id,
                        allocation_key=f"{new_page_key}:row:{row.id}",
                        identity=f"row:{row.id}",
                        allocated=allocated,
                    )
                }
            )
            for row in node.rows
        ]
    return node.model_copy(update=updates)


def _remap_duplicate_page_effect(
    effect: RuntimeEffectV1,
    *,
    source_page_id: str,
    duplicate_page_id: str,
) -> RuntimeEffectV1:
    if isinstance(effect, NavigateEffectV1) and effect.target_page_id == source_page_id:
        return effect.model_copy(update={"target_page_id": duplicate_page_id})
    return effect


def _duplicate_page(
    document: PrototypeDocumentV1,
    command: DuplicatePageCommandV1,
    *,
    draft_id: str,
    client_request_id: str,
    allocated: dict[str, str],
) -> tuple[PrototypeDocumentV1, str]:
    source_index = next(
        (index for index, page in enumerate(document.pages) if page.id == command.page_id),
        None,
    )
    if source_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page to duplicate does not exist"
        )
    source_page = document.pages[source_index]
    page_id = _allocate_page_id(
        draft_id=draft_id,
        client_request_id=client_request_id,
        new_page_key=command.new_page_key,
        allocated=allocated,
    )
    node_id_map: dict[str, str] = {}
    duplicated_root = _duplicate_page_node(
        source_page.root,
        page_id=page_id,
        new_page_key=command.new_page_key,
        allocated=allocated,
        node_id_map=node_id_map,
    )
    page_key = _unique_technical_key(
        f"{source_page.key}-copy",
        {page.key for page in document.pages},
    )
    route = _unique_route(
        _duplicate_route_base(source_page.route),
        {page.route for page in document.pages},
    )
    duplicated_page = source_page.model_copy(
        update={
            "id": page_id,
            "key": page_key,
            "title": command.title,
            "route": route,
            "root": duplicated_root,
        }
    )
    pages = list(document.pages)
    insertion_index = source_index + 1
    pages.insert(insertion_index, duplicated_page)

    navigation_keys = {item.key for item in document.navigation.items}
    navigation_items: list[NavigationItemV1] = []
    for item in document.navigation.items:
        navigation_items.append(item)
        if item.target_page_id != command.page_id:
            continue
        navigation_id = _allocate_page_owned_id(
            page_id,
            allocation_key=f"{command.new_page_key}:navigation:{item.id}",
            identity=f"navigation:{item.id}",
            allocated=allocated,
        )
        navigation_key = _unique_technical_key(f"{item.key}-copy", navigation_keys)
        navigation_keys.add(navigation_key)
        navigation_items.append(
            item.model_copy(
                update={
                    "id": navigation_id,
                    "key": navigation_key,
                    "label": command.title,
                    "target_page_id": page_id,
                }
            )
        )

    view_bindings: list[RuntimeViewBindingV1] = []
    for binding in document.runtime.view_bindings:
        view_bindings.append(binding)
        duplicate_node_id = node_id_map.get(binding.node_id)
        if duplicate_node_id is None:
            continue
        binding_id = _allocate_page_owned_id(
            page_id,
            allocation_key=f"{command.new_page_key}:binding:{binding.id}",
            identity=f"binding:{binding.id}",
            allocated=allocated,
        )
        view_bindings.append(
            binding.model_copy(update={"id": binding_id, "node_id": duplicate_node_id})
        )

    rule_id_map: dict[str, str] = {}
    duplicated_rules_by_source: dict[str, RuntimeRuleV1] = {}
    rule_keys = {rule.key for rule in document.runtime.rules}
    rules: list[RuntimeRuleV1] = []
    for rule in document.runtime.rules:
        rules.append(rule)
        duplicate_trigger_node_id = node_id_map.get(rule.trigger.node_id)
        if duplicate_trigger_node_id is None:
            continue
        rule_id = _allocate_page_owned_id(
            page_id,
            allocation_key=f"{command.new_page_key}:rule:{rule.id}",
            identity=f"rule:{rule.id}",
            allocated=allocated,
        )
        rule_key = _unique_technical_key(f"{rule.key}-copy", rule_keys)
        rule_keys.add(rule_key)
        duplicated_rule = rule.model_copy(
            update={
                "id": rule_id,
                "key": rule_key,
                "trigger": rule.trigger.model_copy(update={"node_id": duplicate_trigger_node_id}),
                "effects": [
                    _remap_duplicate_page_effect(
                        effect,
                        source_page_id=command.page_id,
                        duplicate_page_id=page_id,
                    )
                    for effect in rule.effects
                ],
                "guard_false_effects": [
                    _remap_duplicate_page_effect(
                        effect,
                        source_page_id=command.page_id,
                        duplicate_page_id=page_id,
                    )
                    for effect in rule.guard_false_effects
                ],
            }
        )
        rule_id_map[rule.id] = rule_id
        duplicated_rules_by_source[rule.id] = duplicated_rule
        rules.append(duplicated_rule)

    flows: list[PrototypeFlowV1] = []
    for flow in document.flows:
        flows.append(flow)
        flow_duplicate_rule = duplicated_rules_by_source.get(flow.rule_id)
        if flow_duplicate_rule is None or flow.to_page_id is None:
            continue
        target_page_id = page_id if flow.to_page_id == command.page_id else flow.to_page_id
        duplicated_flow = _new_behavior_rule_flow(flow_duplicate_rule, target_page_id)
        _register_allocated_entity(
            allocated,
            f"{command.new_page_key}:flow:{flow.id}",
            duplicated_flow.id,
        )
        flows.append(duplicated_flow)

    layout_nodes = list(document.runtime.flow_layout.nodes) if document.runtime.flow_layout else []
    duplicated_layout_nodes: list[RuntimeFlowNodePositionV1] = []
    for position in layout_nodes:
        duplicate_node_id = (
            page_id if position.node_id == command.page_id else rule_id_map.get(position.node_id)
        )
        if duplicate_node_id is not None:
            duplicated_layout_nodes.append(
                position.model_copy(update={"node_id": duplicate_node_id})
            )
    layout_nodes.extend(duplicated_layout_nodes)
    flow_layout = (
        RuntimeFlowLayoutV1(nodes=sorted(layout_nodes, key=lambda item: item.node_id))
        if layout_nodes
        else None
    )

    runtime_page_ids = list(document.runtime.page_ids)
    runtime_page_ids.insert(insertion_index, page_id)
    runtime = document.runtime.model_copy(
        update={
            "page_ids": runtime_page_ids,
            "view_bindings": view_bindings,
            "rules": rules,
            "flow_layout": flow_layout,
        }
    )
    navigation = document.navigation.model_copy(update={"items": navigation_items})
    updated = document.model_copy(
        update={
            "pages": pages,
            "navigation": navigation,
            "flows": flows,
            "runtime": runtime,
        }
    )
    return _validate_command_batch_document(updated), page_id


def _absent_page_projection_snapshot() -> PageProjectionSnapshotV1:
    return PageProjectionSnapshotV1(
        page_index=None,
        runtime_page_index=None,
        page=None,
        navigation_items=[],
        view_bindings=[],
        rules=[],
        flows=[],
        flow_layout_positions=[],
    )


def _capture_page_projection(
    document: PrototypeDocumentV1,
    page_id: str,
    *,
    allow_absent: bool = False,
) -> PageProjectionSnapshotV1:
    page_index = next(
        (index for index, page in enumerate(document.pages) if page.id == page_id),
        None,
    )
    if page_index is None:
        if allow_absent:
            return _absent_page_projection_snapshot()
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page does not exist"
        )
    runtime_page_index = next(
        (
            index
            for index, runtime_page_id in enumerate(document.runtime.page_ids)
            if runtime_page_id == page_id
        ),
        None,
    )
    if runtime_page_index is None:
        raise StructuredPrototypeContractError(
            "command_result_invalid", "prototype runtime page projection is missing"
        )
    page = document.pages[page_index]
    page_node_ids = _node_id_set(page.root)
    navigation_items = [
        IndexedNavigationItemV1(index=index, item=item)
        for index, item in enumerate(document.navigation.items)
        if item.target_page_id == page_id
    ]
    view_bindings = [
        IndexedRuntimeViewBindingV1(index=index, binding=binding)
        for index, binding in enumerate(document.runtime.view_bindings)
        if binding.node_id in page_node_ids
    ]
    rules = [
        IndexedRuntimeRuleV1(index=index, rule=rule)
        for index, rule in enumerate(document.runtime.rules)
        if rule.trigger.node_id in page_node_ids
    ]
    rule_ids = {entry.rule.id for entry in rules}
    flows = [
        IndexedPrototypeFlowV1(index=index, flow=flow)
        for index, flow in enumerate(document.flows)
        if flow.rule_id in rule_ids
    ]
    flow_layout_positions = [
        position
        for position in (document.runtime.flow_layout.nodes if document.runtime.flow_layout else [])
        if position.node_id == page_id or position.node_id in rule_ids
    ]
    return PageProjectionSnapshotV1(
        page_index=page_index,
        runtime_page_index=runtime_page_index,
        page=page,
        navigation_items=navigation_items,
        view_bindings=view_bindings,
        rules=rules,
        flows=flows,
        flow_layout_positions=flow_layout_positions,
    )


def _insert_indexed_projection(
    values: list[object],
    entries: Iterable[tuple[int, object]],
    *,
    label: str,
) -> None:
    for index, value in entries:
        if index > len(values):
            raise StructuredPrototypeContractError(
                "inverse_command_invalid",
                f"page {label} restore index is out of range",
            )
        values.insert(index, value)


def _restore_page_projection(
    document: PrototypeDocumentV1,
    page_id: str,
    snapshot: PageProjectionSnapshotV1,
) -> PrototypeDocumentV1:
    current_page = next((page for page in document.pages if page.id == page_id), None)
    if current_page is None and snapshot.page is None:
        raise StructuredPrototypeContractError(
            "inverse_command_invalid", "page restore has no current or snapshot projection"
        )
    current_node_ids = _node_id_set(current_page.root) if current_page is not None else set()
    current_rule_ids = {
        rule.id for rule in document.runtime.rules if rule.trigger.node_id in current_node_ids
    }
    pages: list[object] = [page for page in document.pages if page.id != page_id]
    runtime_page_ids: list[object] = [
        runtime_page_id
        for runtime_page_id in document.runtime.page_ids
        if runtime_page_id != page_id
    ]
    navigation_items: list[object] = [
        item for item in document.navigation.items if item.target_page_id != page_id
    ]
    view_bindings: list[object] = [
        binding
        for binding in document.runtime.view_bindings
        if binding.node_id not in current_node_ids
    ]
    rules: list[object] = [
        rule for rule in document.runtime.rules if rule.id not in current_rule_ids
    ]
    flows: list[object] = [flow for flow in document.flows if flow.rule_id not in current_rule_ids]
    layout_nodes = [
        position
        for position in (document.runtime.flow_layout.nodes if document.runtime.flow_layout else [])
        if position.node_id != page_id and position.node_id not in current_rule_ids
    ]

    if snapshot.page is not None:
        assert snapshot.page_index is not None
        assert snapshot.runtime_page_index is not None
        _insert_indexed_projection(
            pages,
            [(snapshot.page_index, snapshot.page)],
            label="document page",
        )
        _insert_indexed_projection(
            runtime_page_ids,
            [(snapshot.runtime_page_index, page_id)],
            label="runtime page",
        )
        _insert_indexed_projection(
            navigation_items,
            [(entry.index, entry.item) for entry in snapshot.navigation_items],
            label="navigation item",
        )
        _insert_indexed_projection(
            view_bindings,
            [(entry.index, entry.binding) for entry in snapshot.view_bindings],
            label="view binding",
        )
        _insert_indexed_projection(
            rules,
            [(entry.index, entry.rule) for entry in snapshot.rules],
            label="runtime rule",
        )
        _insert_indexed_projection(
            flows,
            [(entry.index, entry.flow) for entry in snapshot.flows],
            label="flow",
        )
        layout_nodes.extend(snapshot.flow_layout_positions)

    typed_pages = cast(list[PrototypePageV1], pages)
    typed_runtime_page_ids = cast(list[str], runtime_page_ids)
    typed_navigation_items = cast(list[NavigationItemV1], navigation_items)
    typed_view_bindings = cast(list[RuntimeViewBindingV1], view_bindings)
    typed_rules = cast(list[RuntimeRuleV1], rules)
    typed_flows = cast(list[PrototypeFlowV1], flows)
    flow_layout = (
        RuntimeFlowLayoutV1(nodes=sorted(layout_nodes, key=lambda item: item.node_id))
        if layout_nodes
        else None
    )
    navigation = document.navigation.model_copy(update={"items": typed_navigation_items})
    runtime = document.runtime.model_copy(
        update={
            "page_ids": typed_runtime_page_ids,
            "view_bindings": typed_view_bindings,
            "rules": typed_rules,
            "flow_layout": flow_layout,
        }
    )
    updated = document.model_copy(
        update={
            "pages": typed_pages,
            "navigation": navigation,
            "flows": typed_flows,
            "runtime": runtime,
        }
    )
    return _validate_command_batch_document(updated)


def _require_page_deletable(document: PrototypeDocumentV1, page_id: str) -> None:
    if len(document.pages) == 1:
        raise StructuredPrototypeContractError(
            "command_last_page_delete", "prototype final page cannot be deleted"
        )
    page = next((candidate for candidate in document.pages if candidate.id == page_id), None)
    if page is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page does not exist"
        )
    page_node_ids = _node_id_set(page.root)
    for rule in document.runtime.rules:
        if rule.trigger.node_id not in page_node_ids and page_id in _rule_navigate_targets(rule):
            raise StructuredPrototypeContractError(
                "command_page_inbound_navigation",
                f"prototype page is targeted by external runtime rule {rule.key}",
            )
    for scenario in document.runtime.scenarios:
        if scenario.start_page_id == page_id:
            raise StructuredPrototypeContractError(
                "command_page_scenario_start",
                f"prototype page is the start page for runtime scenario {scenario.key}",
            )


def _rename_page(
    document: PrototypeDocumentV1,
    *,
    page_id: str,
    title: str,
) -> tuple[PrototypeDocumentV1, set[str]]:
    pages = list(document.pages)
    page_index = next(
        (index for index, page in enumerate(pages) if page.id == page_id),
        None,
    )
    if page_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page does not exist"
        )
    pages[page_index] = pages[page_index].model_copy(update={"title": title})
    navigation_items = [
        item.model_copy(update={"label": title}) if item.target_page_id == page_id else item
        for item in document.navigation.items
    ]
    affected = {page_id}
    affected.update(item.id for item in document.navigation.items if item.target_page_id == page_id)
    navigation = document.navigation.model_copy(update={"items": navigation_items})
    updated = document.model_copy(update={"pages": pages, "navigation": navigation})
    return _validate_command_batch_document(updated), affected


def _capture_page_title_projection(
    document: PrototypeDocumentV1,
    page_id: str,
) -> PageTitleProjectionSnapshotV1:
    page = next((candidate for candidate in document.pages if candidate.id == page_id), None)
    if page is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page does not exist"
        )
    return PageTitleProjectionSnapshotV1(
        title=page.title,
        navigation_labels=[
            NavigationLabelSnapshotV1(item_id=item.id, label=item.label)
            for item in document.navigation.items
            if item.target_page_id == page_id
        ],
    )


def _restore_page_title_projection(
    document: PrototypeDocumentV1,
    page_id: str,
    snapshot: PageTitleProjectionSnapshotV1,
) -> tuple[PrototypeDocumentV1, set[str]]:
    pages = list(document.pages)
    page_index = next(
        (index for index, page in enumerate(pages) if page.id == page_id),
        None,
    )
    if page_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype page does not exist"
        )
    pages[page_index] = pages[page_index].model_copy(update={"title": snapshot.title})
    labels_by_item_id = {entry.item_id: entry.label for entry in snapshot.navigation_labels}
    current_item_ids = {
        item.id for item in document.navigation.items if item.target_page_id == page_id
    }
    if current_item_ids != set(labels_by_item_id):
        raise StructuredPrototypeContractError(
            "inverse_command_invalid",
            "page title snapshot navigation projection does not match the document",
        )
    navigation_items = [
        item.model_copy(update={"label": labels_by_item_id[item.id]})
        if item.id in labels_by_item_id
        else item
        for item in document.navigation.items
    ]
    navigation = document.navigation.model_copy(update={"items": navigation_items})
    updated = document.model_copy(update={"pages": pages, "navigation": navigation})
    return _validate_command_batch_document(updated), {page_id, *labels_by_item_id}


def _page_projection_entity_ids(
    snapshot: PageProjectionSnapshotV1,
    *,
    page_id: str | None = None,
) -> set[str]:
    affected = {page_id} if page_id is not None else set()
    if snapshot.page is None:
        return affected
    affected.add(snapshot.page.id)
    affected.update(_page_owned_entity_ids(snapshot.page.root))
    affected.update(entry.item.id for entry in snapshot.navigation_items)
    affected.update(entry.binding.id for entry in snapshot.view_bindings)
    affected.update(entry.rule.id for entry in snapshot.rules)
    affected.update(entry.flow.id for entry in snapshot.flows)
    return affected


def _page_owned_entity_ids(node: UINodeV1) -> set[str]:
    result = {node.id}
    if isinstance(node, FreeformNodeV1):
        result.update(grid.id for grid in node.grids)
    if isinstance(node, TableNodeV1):
        result.update(row.id for row in node.rows)
    children = _node_children(node)
    if children is not None:
        for child in children:
            result.update(_page_owned_entity_ids(child))
    return result


def _node_id_set(node: UINodeV1) -> set[str]:
    result = {node.id}
    if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        for child in node.children:
            result.update(_node_id_set(child))
    return result


def _require_node_subtree_unreferenced(
    document: PrototypeDocumentV1,
    node: UINodeV1,
) -> None:
    subtree_ids = _node_id_set(node)
    referenced = (
        any(binding.node_id in subtree_ids for binding in document.runtime.view_bindings)
        or any(rule.trigger.node_id in subtree_ids for rule in document.runtime.rules)
        or any(flow.from_node_id in subtree_ids for flow in document.flows)
    )
    if referenced:
        raise StructuredPrototypeContractError(
            "command_target_in_use",
            "prototype node subtree is referenced by runtime bindings, rules, or flows",
        )


def _node_children(node: UINodeV1) -> list[UINodeV1] | None:
    if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        return list(node.children)
    return None


def _replace_children(node: UINodeV1, children: list[UINodeV1]) -> UINodeV1:
    if not isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        raise StructuredPrototypeContractError(
            "command_target_invalid", "prototype target node is not a container"
        )
    return node.model_copy(update={"children": children})


def _walk_replace(node: UINodeV1, replacement: UINodeV1) -> tuple[UINodeV1, bool]:
    if node.id == replacement.id:
        return replacement, True
    children = _node_children(node)
    if children is None:
        return node, False
    for index, child in enumerate(children):
        updated_child, changed = _walk_replace(child, replacement)
        if changed:
            children[index] = updated_child
            return _replace_children(node, children), True
    return node, False


def _replace_node(document: PrototypeDocumentV1, replacement: UINodeV1) -> PrototypeDocumentV1:
    pages = list(document.pages)
    for index, page in enumerate(pages):
        root, changed = _walk_replace(page.root, replacement)
        if changed:
            pages[index] = page.model_copy(update={"root": root})
            return document.model_copy(update={"pages": pages})
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _find_node(node: UINodeV1, node_id: str) -> UINodeV1 | None:
    if node.id == node_id:
        return node
    children = _node_children(node)
    if children is None:
        return None
    for child in children:
        found = _find_node(child, node_id)
        if found is not None:
            return found
    return None


def _require_node(document: PrototypeDocumentV1, node_id: str) -> UINodeV1:
    for page in document.pages:
        node = _find_node(page.root, node_id)
        if node is not None:
            return node
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _insert_into_tree(
    node: UINodeV1,
    parent_id: str,
    index: int,
    inserted: UINodeV1,
) -> tuple[UINodeV1, bool]:
    if node.id == parent_id:
        children = _node_children(node)
        if children is None:
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype target node is not a container"
            )
        if index > len(children):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype node target index is out of range"
            )
        children.insert(index, inserted)
        return _replace_children(node, children), True
    children = _node_children(node)
    if children is None:
        return node, False
    for child_index, child in enumerate(children):
        updated_child, changed = _insert_into_tree(child, parent_id, index, inserted)
        if changed:
            children[child_index] = updated_child
            return _replace_children(node, children), True
    return node, False


def _insert_node(
    document: PrototypeDocumentV1,
    parent_id: str,
    index: int,
    inserted: UINodeV1,
) -> PrototypeDocumentV1:
    if _node_id_set(inserted) & _document_node_ids(document):
        raise StructuredPrototypeContractError(
            "command_entity_id_conflict", "prototype inserted node ID already exists"
        )
    pages = list(document.pages)
    for page_index, page in enumerate(pages):
        root, changed = _insert_into_tree(page.root, parent_id, index, inserted)
        if changed:
            pages[page_index] = page.model_copy(update={"root": root})
            return PrototypeDocumentV1.model_validate(
                document.model_copy(update={"pages": pages}).model_dump(mode="json", by_alias=True),
                strict=True,
            )
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype parent node does not exist"
    )


def _document_node_ids(document: PrototypeDocumentV1) -> set[str]:
    result: set[str] = set()
    for page in document.pages:
        result.update(_node_id_set(page.root))
    for definition in document.component_definitions:
        result.update(_node_id_set(definition.root))
    return result


def _remove_from_tree(
    node: UINodeV1,
    node_id: str,
) -> tuple[UINodeV1, UINodeV1 | None, str | None, int | None]:
    children = _node_children(node)
    if children is None:
        return node, None, None, None
    for index, child in enumerate(children):
        if child.id == node_id:
            removed = children.pop(index)
            return _replace_children(node, children), removed, node.id, index
        updated_child, recursive_removed, parent_id, removed_index = _remove_from_tree(
            child, node_id
        )
        if recursive_removed is not None:
            children[index] = updated_child
            return (
                _replace_children(node, children),
                recursive_removed,
                parent_id,
                removed_index,
            )
    return node, None, None, None


def _detach_node_without_document_validation(
    document: PrototypeDocumentV1,
    node_id: str,
) -> tuple[PrototypeDocumentV1, UINodeV1, str, int]:
    pages = list(document.pages)
    for page_index, page in enumerate(pages):
        if page.root.id == node_id:
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype page root cannot be removed"
            )
        root, removed, parent_id, removed_index = _remove_from_tree(page.root, node_id)
        if removed is not None and parent_id is not None and removed_index is not None:
            pages[page_index] = page.model_copy(update={"root": root})
            return (
                document.model_copy(update={"pages": pages}),
                removed,
                parent_id,
                removed_index,
            )
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _remove_node(
    document: PrototypeDocumentV1,
    node_id: str,
) -> tuple[PrototypeDocumentV1, UINodeV1, str, int]:
    detached, removed, parent_id, removed_index = _detach_node_without_document_validation(
        document, node_id
    )
    updated = PrototypeDocumentV1.model_validate(
        detached.model_dump(mode="json", by_alias=True),
        strict=True,
    )
    return updated, removed, parent_id, removed_index


def _locate_movable_node(
    document: PrototypeDocumentV1,
    node_id: str,
) -> tuple[UINodeV1, str, int]:
    for page in document.pages:
        if page.root.id == node_id:
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype page root cannot be moved"
            )
        found = _locate_child(page.root, node_id)
        if found is not None:
            return found
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _locate_child(node: UINodeV1, node_id: str) -> tuple[UINodeV1, str, int] | None:
    children = _node_children(node)
    if children is None:
        return None
    for index, child in enumerate(children):
        if child.id == node_id:
            return child, node.id, index
        found = _locate_child(child, node_id)
        if found is not None:
            return found
    return None


def _position_node_for_parent(
    node: UINodeV1,
    target_parent: UINodeV1,
    target_position: FreeformPositionV1 | None,
    *,
    target_position_is_set: bool,
) -> UINodeV1:
    if _node_children(target_parent) is None:
        raise StructuredPrototypeContractError(
            "command_target_invalid", "prototype target node is not a container"
        )
    resolved_position = target_position if target_position_is_set else node.layout_item.position
    if isinstance(target_parent, FreeformNodeV1) and resolved_position is None:
        raise StructuredPrototypeContractError(
            "command_target_invalid",
            "prototype move into a freeform container requires a target position",
        )
    layout_item = node.layout_item.model_copy(update={"position": resolved_position})
    return node.model_copy(update={"layout_item": layout_item})


def _apply_property_update(
    node: UINodeV1,
    update: NodePropertyUpdateV1,
) -> tuple[UINodeV1, NodePropertyUpdateV1]:
    if isinstance(update, VisibilityUpdateV1):
        return (
            node.model_copy(update={"visibility": update.visibility}),
            VisibilityUpdateV1(kind="visibility", visibility=node.visibility),
        )
    if isinstance(update, TextContentUpdateV1) and isinstance(node, TextNodeV1):
        return (
            node.model_copy(update={"content": update.content}),
            TextContentUpdateV1(kind="textContent", content=node.content),
        )
    if isinstance(update, LabelUpdateV1) and isinstance(node, (InputNodeV1, ButtonNodeV1)):
        return (
            node.model_copy(update={"label": update.label}),
            LabelUpdateV1(kind="label", label=node.label),
        )
    if isinstance(update, PlaceholderUpdateV1) and isinstance(node, InputNodeV1):
        return (
            node.model_copy(update={"placeholder": update.placeholder}),
            PlaceholderUpdateV1(kind="placeholder", placeholder=node.placeholder),
        )
    if isinstance(update, ButtonVariantUpdateV1) and isinstance(node, ButtonNodeV1):
        return (
            node.model_copy(update={"variant": update.variant}),
            ButtonVariantUpdateV1(kind="buttonVariant", variant=node.variant),
        )
    if isinstance(update, DisabledUpdateV1) and isinstance(node, (InputNodeV1, ButtonNodeV1)):
        return (
            node.model_copy(update={"disabled": update.disabled}),
            DisabledUpdateV1(kind="disabled", disabled=node.disabled),
        )
    if isinstance(update, InputValueUpdateV1) and isinstance(node, InputNodeV1):
        return (
            node.model_copy(update={"value": update.value}),
            InputValueUpdateV1(kind="inputValue", value=node.value),
        )
    if isinstance(update, StackLayoutUpdateV1) and isinstance(node, StackNodeV1):
        return (
            node.model_copy(
                update={
                    "direction": update.direction,
                    "gap": update.gap,
                    "align": update.align,
                    "justify": update.justify,
                    "padding": update.padding,
                }
            ),
            StackLayoutUpdateV1(
                kind="stackLayout",
                direction=node.direction,
                gap=node.gap,
                align=node.align,
                justify=node.justify,
                padding=node.padding,
            ),
        )
    if isinstance(update, GridLayoutUpdateV1) and isinstance(node, GridNodeV1):
        return (
            node.model_copy(
                update={
                    "columns": update.columns,
                    "gap": update.gap,
                    "padding": update.padding,
                    "column_overrides": update.column_overrides,
                }
            ),
            GridLayoutUpdateV1(
                kind="gridLayout",
                columns=node.columns,
                gap=node.gap,
                padding=node.padding,
                column_overrides=node.column_overrides,
            ),
        )
    if isinstance(update, FormLayoutUpdateV1) and isinstance(node, FormNodeV1):
        return (
            node.model_copy(update={"gap": update.gap, "padding": update.padding}),
            FormLayoutUpdateV1(
                kind="formLayout",
                gap=node.gap,
                padding=node.padding,
            ),
        )
    if isinstance(update, FreeformGridsUpdateV1) and isinstance(node, FreeformNodeV1):
        return (
            node.model_copy(update={"grids": update.grids}),
            FreeformGridsUpdateV1(kind="freeformGrids", grids=node.grids),
        )
    if isinstance(update, ResponsiveLayoutUpdateV1):
        return (
            node.model_copy(update={"responsive": update.responsive}),
            ResponsiveLayoutUpdateV1(
                kind="responsiveLayout",
                responsive=node.responsive,
            ),
        )
    if isinstance(update, TableDataUpdateV1) and isinstance(node, TableNodeV1):
        return (
            node.model_copy(update={"columns": update.columns, "rows": update.rows}),
            TableDataUpdateV1(kind="tableData", columns=node.columns, rows=node.rows),
        )
    raise StructuredPrototypeContractError(
        "command_property_invalid", "prototype property update is invalid for the node type"
    )


def _materialize_behavior_rule(
    rule_id: str,
    definition: RuntimeRuleDefinitionV1,
) -> RuntimeRuleV1:
    payload = definition.model_dump(mode="json", by_alias=True)
    payload["id"] = rule_id
    return RuntimeRuleV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _new_behavior_rule_flow(rule: RuntimeRuleV1, target_page_id: str) -> PrototypeFlowV1:
    flow_id = str(uuid5(UUID(rule.id), target_page_id))
    return PrototypeFlowV1(
        id=flow_id,
        key=f"flow-{UUID(flow_id).hex}",
        rule_id=rule.id,
        from_node_id=rule.trigger.node_id,
        to_page_id=target_page_id,
    )


def _register_allocated_behavior_flows(
    before: PrototypeDocumentV1,
    after: PrototypeDocumentV1,
    *,
    rule_id: str,
    allocated: dict[str, str],
) -> None:
    existing_flow_ids = {flow.id for flow in before.flows}
    for flow in after.flows:
        if flow.rule_id != rule_id or flow.id in existing_flow_ids:
            continue
        if flow.key in allocated:
            raise StructuredPrototypeContractError(
                "command_new_key_duplicate",
                "prototype generated behavior-flow key is duplicated in the batch",
            )
        allocated[flow.key] = flow.id


def _validate_behavior_rule_document_update(
    document: PrototypeDocumentV1,
    *,
    rules: list[RuntimeRuleV1],
    flows: list[PrototypeFlowV1],
    flow_layout: RuntimeFlowLayoutV1 | None,
) -> PrototypeDocumentV1:
    runtime = document.runtime.model_copy(
        update={
            "rules": rules,
            "flow_layout": flow_layout,
        }
    )
    return PrototypeDocumentV1.model_validate(
        document.model_copy(update={"runtime": runtime, "flows": flows}).model_dump(
            mode="json",
            by_alias=True,
        ),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _add_behavior_rule(
    document: PrototypeDocumentV1,
    rule: RuntimeRuleV1,
) -> PrototypeDocumentV1:
    rules = [*document.runtime.rules, rule]
    flows = list(document.flows)
    flows.extend(_new_behavior_rule_flow(rule, target) for target in _rule_navigate_targets(rule))
    return _validate_behavior_rule_document_update(
        document,
        rules=rules,
        flows=flows,
        flow_layout=document.runtime.flow_layout,
    )


def _replace_behavior_rule(
    document: PrototypeDocumentV1,
    replacement: RuntimeRuleV1,
) -> PrototypeDocumentV1:
    rules = list(document.runtime.rules)
    rule_index = next(
        (index for index, rule in enumerate(rules) if rule.id == replacement.id),
        None,
    )
    if rule_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype behavior rule does not exist"
        )
    rules[rule_index] = replacement

    existing_entries = [
        (index, flow) for index, flow in enumerate(document.flows) if flow.rule_id == replacement.id
    ]
    existing_by_target = {flow.to_page_id: flow for _, flow in existing_entries}
    target_page_ids = _rule_navigate_targets(replacement)
    projected: list[PrototypeFlowV1] = []
    for target in target_page_ids:
        existing = existing_by_target.get(target)
        if existing is None:
            projected.append(_new_behavior_rule_flow(replacement, target))
        else:
            projected.append(
                existing.model_copy(update={"from_node_id": replacement.trigger.node_id})
            )

    existing_targets = [flow.to_page_id for _, flow in existing_entries]
    stable_prefix_length = 0
    for existing_target, target_page_id in zip(existing_targets, target_page_ids, strict=False):
        if existing_target != target_page_id:
            break
        stable_prefix_length += 1

    flows = list(document.flows)
    for flow_index, flow in existing_entries[:stable_prefix_length]:
        flows[flow_index] = flow.model_copy(update={"from_node_id": replacement.trigger.node_id})
    stale_entries = existing_entries[stable_prefix_length:]
    stale_flow_ids = {flow.id for _, flow in stale_entries}
    flows = [flow for flow in flows if flow.id not in stale_flow_ids]
    projected_suffix = projected[stable_prefix_length:]
    if projected_suffix:
        if stale_entries:
            insertion_index = min(stale_entries[0][0], len(flows))
        elif stable_prefix_length:
            last_stable_id = existing_entries[stable_prefix_length - 1][1].id
            insertion_index = (
                next(index for index, flow in enumerate(flows) if flow.id == last_stable_id) + 1
            )
        else:
            insertion_index = len(flows)
        flows[insertion_index:insertion_index] = projected_suffix
    return _validate_behavior_rule_document_update(
        document,
        rules=rules,
        flows=flows,
        flow_layout=document.runtime.flow_layout,
    )


def _capture_behavior_rule_projection(
    document: PrototypeDocumentV1,
    rule_id: str,
    *,
    allow_absent: bool = False,
) -> BehaviorRuleProjectionSnapshotV1:
    rule_index = next(
        (index for index, rule in enumerate(document.runtime.rules) if rule.id == rule_id),
        None,
    )
    if rule_index is None:
        if not allow_absent:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype behavior rule does not exist"
            )
        return BehaviorRuleProjectionSnapshotV1(
            rule_index=None,
            rule=None,
            flows=[],
            flow_layout_position=None,
        )
    rule = document.runtime.rules[rule_index]
    indexed_flows = [
        IndexedPrototypeFlowV1(index=index, flow=flow)
        for index, flow in enumerate(document.flows)
        if flow.rule_id == rule_id
    ]
    flow_layout_position = next(
        (
            position
            for position in (
                document.runtime.flow_layout.nodes if document.runtime.flow_layout else []
            )
            if position.node_id == rule_id
        ),
        None,
    )
    return BehaviorRuleProjectionSnapshotV1(
        rule_index=rule_index,
        rule=rule,
        flows=indexed_flows,
        flow_layout_position=flow_layout_position,
    )


def _restore_behavior_rule_projection(
    document: PrototypeDocumentV1,
    rule_id: str,
    snapshot: BehaviorRuleProjectionSnapshotV1,
) -> PrototypeDocumentV1:
    rules = [rule for rule in document.runtime.rules if rule.id != rule_id]
    if snapshot.rule is not None:
        assert snapshot.rule_index is not None
        if snapshot.rule_index > len(rules):
            raise StructuredPrototypeContractError(
                "inverse_command_invalid", "behavior rule restore index is out of range"
            )
        rules.insert(snapshot.rule_index, snapshot.rule)

    flows = [flow for flow in document.flows if flow.rule_id != rule_id]
    for entry in snapshot.flows:
        if entry.index > len(flows):
            raise StructuredPrototypeContractError(
                "inverse_command_invalid", "behavior rule flow restore index is out of range"
            )
        flows.insert(entry.index, entry.flow)

    layout_nodes = [
        position
        for position in (document.runtime.flow_layout.nodes if document.runtime.flow_layout else [])
        if position.node_id != rule_id
    ]
    if snapshot.flow_layout_position is not None:
        layout_nodes.append(snapshot.flow_layout_position)
    flow_layout = (
        RuntimeFlowLayoutV1(nodes=sorted(layout_nodes, key=lambda item: item.node_id))
        if layout_nodes
        else None
    )
    return _validate_behavior_rule_document_update(
        document,
        rules=rules,
        flows=flows,
        flow_layout=flow_layout,
    )


def _behavior_rule_snapshot_entity_ids(
    snapshot: BehaviorRuleProjectionSnapshotV1,
    *,
    rule_id: str | None = None,
) -> set[str]:
    affected = {rule_id} if rule_id is not None else set()
    if snapshot.rule is None:
        return affected
    affected.add(snapshot.rule.id)
    affected.add(snapshot.rule.trigger.node_id)
    affected.update(_rule_navigate_targets(snapshot.rule))
    affected.update(entry.flow.id for entry in snapshot.flows)
    return affected


def _behavior_rule_projection_entity_ids(
    document: PrototypeDocumentV1,
    rule_id: str,
) -> set[str]:
    return _behavior_rule_snapshot_entity_ids(_capture_behavior_rule_projection(document, rule_id))


def _require_runtime_flow_projection_entity(
    document: PrototypeDocumentV1,
    node_id: str,
) -> None:
    projection_entity_ids = _runtime_flow_projection_entity_ids(
        document.runtime,
        {page.id for page in document.pages},
    )
    if node_id not in projection_entity_ids:
        raise StructuredPrototypeContractError(
            "command_target_missing",
            "prototype runtime flow projection entity does not exist",
        )


def _replace_runtime_flow_layout_nodes(
    document: PrototypeDocumentV1,
    nodes: list[RuntimeFlowNodePositionV1],
) -> PrototypeDocumentV1:
    ordered = sorted(nodes, key=lambda node: node.node_id)
    flow_layout = RuntimeFlowLayoutV1(nodes=ordered) if ordered else None
    runtime = document.runtime.model_copy(update={"flow_layout": flow_layout})
    return PrototypeDocumentV1.model_validate(
        document.model_copy(update={"runtime": runtime}).model_dump(mode="json", by_alias=True),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _set_runtime_flow_node_position(
    document: PrototypeDocumentV1,
    *,
    node_id: str,
    x: int,
    y: int,
) -> tuple[PrototypeDocumentV1, RuntimeFlowNodePositionV1 | None]:
    _require_runtime_flow_projection_entity(document, node_id)
    nodes = list(document.runtime.flow_layout.nodes) if document.runtime.flow_layout else []
    index = next(
        (index for index, node in enumerate(nodes) if node.node_id == node_id),
        None,
    )
    previous = nodes[index] if index is not None else None
    positioned = RuntimeFlowNodePositionV1(node_id=node_id, x=x, y=y)
    if index is None:
        nodes.append(positioned)
    else:
        nodes[index] = positioned
    return _replace_runtime_flow_layout_nodes(document, nodes), previous


def _remove_runtime_flow_node_position(
    document: PrototypeDocumentV1,
    node_id: str,
) -> tuple[PrototypeDocumentV1, RuntimeFlowNodePositionV1]:
    _require_runtime_flow_projection_entity(document, node_id)
    nodes = list(document.runtime.flow_layout.nodes) if document.runtime.flow_layout else []
    index = next(
        (index for index, node in enumerate(nodes) if node.node_id == node_id),
        None,
    )
    if index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing",
            "prototype runtime flow node position does not exist",
        )
    removed = nodes.pop(index)
    return _replace_runtime_flow_layout_nodes(document, nodes), removed


def _runtime_entity_field_definition(
    document: PrototypeDocumentV1,
    *,
    schema_id: str,
    field_id: str,
) -> RuntimeEntityFieldV1:
    schema = next(
        (candidate for candidate in document.runtime.entity_schemas if candidate.id == schema_id),
        None,
    )
    if schema is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype runtime entity schema does not exist"
        )
    field = next((candidate for candidate in schema.fields if candidate.id == field_id), None)
    if field is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype runtime entity field does not exist"
        )
    return field


def _validate_runtime_command_value(
    document: PrototypeDocumentV1,
    field: RuntimeEntityFieldV1,
    value: RuntimeValueV1,
) -> None:
    if not _runtime_value_matches(value, field.value_type, field.nullable):
        raise StructuredPrototypeContractError(
            "command_value_invalid", "prototype runtime entity field value type is invalid"
        )
    schema_ids = {schema.id for schema in document.runtime.entity_schemas}
    if isinstance(value, EntityRefRuntimeValueV1) and value.schema_id not in schema_ids:
        raise StructuredPrototypeContractError(
            "command_value_invalid", "prototype runtime entity reference value schema is invalid"
        )


def _apply_runtime_entity_field_update(
    document: PrototypeDocumentV1,
    command: SetRuntimeEntityFieldCommandV1,
) -> tuple[PrototypeDocumentV1, RuntimeValueV1]:
    field_definition = _runtime_entity_field_definition(
        document,
        schema_id=command.schema_id,
        field_id=command.field_id,
    )
    _validate_runtime_command_value(document, field_definition, command.value)
    scenarios = list(document.runtime.scenarios)
    scenario_index = next(
        (index for index, scenario in enumerate(scenarios) if scenario.id == command.scenario_id),
        None,
    )
    if scenario_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype runtime scenario does not exist"
        )
    scenario = scenarios[scenario_index]
    fixtures = list(scenario.entity_fixtures)
    fixture_index = next(
        (index for index, fixture in enumerate(fixtures) if fixture.schema_id == command.schema_id),
        None,
    )
    if fixture_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype runtime entity fixture does not exist"
        )
    fixture = fixtures[fixture_index]
    entities = list(fixture.entities)
    entity_index = next(
        (index for index, entity in enumerate(entities) if entity.id == command.entity_id),
        None,
    )
    if entity_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype runtime entity does not exist"
        )
    entity = entities[entity_index]
    if entity.schema_id != command.schema_id:
        raise StructuredPrototypeContractError(
            "command_target_invalid", "prototype runtime entity schema is inconsistent"
        )
    fields = list(entity.fields)
    field_index = next(
        (index for index, field in enumerate(fields) if field.field_id == command.field_id),
        None,
    )
    if field_index is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype runtime entity field value does not exist"
        )
    old_value = fields[field_index].value
    fields[field_index] = fields[field_index].model_copy(update={"value": command.value})
    entities[entity_index] = entity.model_copy(update={"fields": fields})
    fixtures[fixture_index] = fixture.model_copy(update={"entities": entities})
    scenarios[scenario_index] = scenario.model_copy(update={"entity_fixtures": fixtures})
    runtime = document.runtime.model_copy(update={"scenarios": scenarios})
    updated = PrototypeDocumentV1.model_validate(
        document.model_copy(update={"runtime": runtime}).model_dump(mode="json", by_alias=True),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    return updated, old_value


def _apply_layout_update(
    layout: LayoutItemV1,
    update: LayoutItemUpdateV1,
) -> tuple[LayoutItemV1, LayoutItemUpdateV1]:
    update_values: dict[str, object | None] = {
        "width": update.width,
        "min_width": update.min_width,
        "max_width": update.max_width,
        "height": update.height,
        "min_height": update.min_height,
        "max_height": update.max_height,
        "grow": update.grow,
        "shrink": update.shrink,
        "align_self": update.align_self,
        "position": update.position,
    }
    changed = {field: update_values[field] for field in update.model_fields_set}
    layout_values: dict[str, object] = {
        "width": layout.width,
        "min_width": layout.min_width,
        "max_width": layout.max_width,
        "height": layout.height,
        "min_height": layout.min_height,
        "max_height": layout.max_height,
        "grow": layout.grow,
        "shrink": layout.shrink,
        "align_self": layout.align_self,
        "position": layout.position,
    }
    previous = {field: layout_values[field] for field in changed}
    previous_aliases = {_camel_alias(field): value for field, value in previous.items()}
    return layout.model_copy(update=changed), LayoutItemUpdateV1.model_validate(
        previous_aliases, strict=True
    )
