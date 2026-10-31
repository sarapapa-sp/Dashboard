from pathlib import Path
import json

import pandas as pd
from dash import Dash, Input, Output, State, ctx, dcc, html, no_update
import dash_ag_grid as dag


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "sample_data.csv"

REFERENTIAL_COLUMNS = ["cob_date", "gbl", "subsub", "activityl1"]
VALUE_COLUMNS = ["daily", "mtd", "ytd"]

DEFAULT_DIMENSIONS = ["cob_date", "gbl", "subsub", "activityl1"]
DEFAULT_VALUES = ["daily", "mtd", "ytd"]


# ---------------------------------------------------------------------
# Source data
# ---------------------------------------------------------------------
def read_source_data() -> pd.DataFrame:
    """Read and normalize the complete source dataset once."""
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {DATA_FILE}")

    data = pd.read_csv(DATA_FILE)

    required = REFERENTIAL_COLUMNS + VALUE_COLUMNS
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Source data is missing required columns: {missing}")

    data = data[required].copy()
    data["cob_date"] = pd.to_datetime(data["cob_date"], errors="coerce")

    for column in VALUE_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0)

    return data


SOURCE_DF = read_source_data()


def _display_dimension_value(column, value):
    """Return a readable value for the single Referential grid column."""
    if pd.isna(value):
        return "(Blank)"
    if column == "cob_date":
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    return str(value)


def _path_key(path_parts):
    """Create a stable JSON key for a hierarchy node."""
    return json.dumps(path_parts, ensure_ascii=False, default=str)


def get_filter_options():
    """Build filter dropdown choices from the original source data."""
    options = {}
    for column in REFERENTIAL_COLUMNS:
        values = SOURCE_DF[column].dropna().drop_duplicates().tolist()
        if column == "cob_date":
            values = sorted(pd.to_datetime(values))
            values = [value.strftime("%Y-%m-%d") for value in values]
        else:
            values = sorted(values, key=lambda value: str(value).lower())

        options[column] = [
            {"label": str(value), "value": str(value)}
            for value in values
        ]
    return options


FILTER_OPTIONS = get_filter_options()


def _apply_source_filters(data, filters):
    """Apply filters to source rows before any aggregation takes place."""
    filtered = data.copy()
    filters = filters or {}

    for column in REFERENTIAL_COLUMNS:
        selected = filters.get(column) or []
        if not selected:
            continue

        if column == "cob_date":
            selected_dates = pd.to_datetime(selected, errors="coerce")
            filtered = filtered[
                filtered[column].isin(selected_dates)
            ]
        else:
            filtered = filtered[
                filtered[column].astype(str).isin([str(v) for v in selected])
            ]

    return filtered


def get_default_expanded_paths(selected_columns, filters=None, source_df=None):
    """Return keys for top-level nodes so the first hierarchy level opens."""
    data = SOURCE_DF if source_df is None else source_df
    data = _apply_source_filters(data, filters)

    if not selected_columns or data.empty:
        return []

    first_column = selected_columns[0]
    values = data[first_column].drop_duplicates().tolist()
    paths = []

    for value in values:
        display_value = _display_dimension_value(first_column, value)
        paths.append(_path_key([
            {"column": first_column, "value": display_value}
        ]))

    return paths


# ---------------------------------------------------------------------
# Hierarchical data loader
# ---------------------------------------------------------------------
def load_data(
    selected_columns,
    selected_value_columns=None,
    source_df=None,
    filters=None,
    expanded_paths=None,
):
    """
    Create a flattened, expandable hierarchy for AG Grid.

    All selected referential columns are represented in ONE grid column:
    "Referential". The order in selected_columns defines the hierarchy.

    Example:
        selected_columns=["cob_date", "gbl", "subsub", "activityl1"]

    Grid appearance:
        2026-10-26
            GM
                FX
                    Spot
                    Options
                Rates
                    Swaps
            EQ
                Cash
                    Equities

    Each hierarchy node carries the sum of the selected value columns for
    all source records below that node. Only expanded branches are returned.

    Parameters
    ----------
    selected_columns : list[str]
        Referential columns and hierarchy order.
    selected_value_columns : list[str]
        Value columns to aggregate.
    source_df : pd.DataFrame, optional
        Source DataFrame. Defaults to SOURCE_DF.
    filters : dict, optional
        Mapping of referential column to selected filter values.
    expanded_paths : set/list, optional
        JSON path keys for currently expanded nodes. If None, top-level
        nodes are expanded by default.

    Returns
    -------
    pd.DataFrame
        Columns: Referential, selected value columns, and hidden tree metadata.
    """
    data = SOURCE_DF if source_df is None else source_df

    selected_columns = list(dict.fromkeys(selected_columns or []))
    selected_value_columns = list(dict.fromkeys(selected_value_columns or []))

    invalid_dimensions = [
        col for col in selected_columns if col not in REFERENTIAL_COLUMNS
    ]
    invalid_values = [
        col for col in selected_value_columns if col not in VALUE_COLUMNS
    ]

    if invalid_dimensions:
        raise ValueError(f"Invalid referential columns: {invalid_dimensions}")
    if invalid_values:
        raise ValueError(f"Invalid value columns: {invalid_values}")
    if not selected_columns:
        raise ValueError("Select at least one referential column.")

    data = _apply_source_filters(data, filters)

    if data.empty:
        return pd.DataFrame(
            columns=["Referential"] + selected_value_columns
            + ["_path_key", "_level", "_has_children", "_expanded"]
        )

    default_expand_roots = expanded_paths is None
    expanded_paths = set(expanded_paths or [])
    result_rows = []

    def walk(frame, level, parent_path):
        dimension = selected_columns[level]

        # sort=False preserves the source order for a stable report layout.
        grouped = frame.groupby(
            dimension, dropna=False, sort=False, observed=True
        )

        for raw_value, group in grouped:
            display_value = _display_dimension_value(dimension, raw_value)
            path_parts = parent_path + [
                {"column": dimension, "value": display_value}
            ]
            key = _path_key(path_parts)

            has_children = level < len(selected_columns) - 1

            if default_expand_roots and level == 0:
                is_expanded = True
            else:
                is_expanded = key in expanded_paths

            row = {
                "Referential": display_value,
                "_path_key": key,
                "_level": level,
                "_has_children": has_children,
                "_expanded": is_expanded,
            }

            for value_column in selected_value_columns:
                row[value_column] = float(group[value_column].sum())

            result_rows.append(row)

            if has_children and is_expanded:
                walk(group, level + 1, path_parts)

    walk(data, 0, [])

    return pd.DataFrame(result_rows)


# ---------------------------------------------------------------------
# AG Grid columns
# ---------------------------------------------------------------------
def make_column_definitions():
    """Expose all dimensions and measures to AG Grid's Columns panel.

    Dimensions start in Row Groups in the configured hierarchy order.
    Measures are available as aggregated values. Users can rearrange, add,
    remove, pivot, or hide fields in the native AG Grid Columns panel.
    """
    definitions = []

    for index, dimension in enumerate(REFERENTIAL_COLUMNS):
        definitions.append({
            "field": dimension,
            "headerName": dimension.replace("_", " ").upper(),
            "rowGroup": True,
            "rowGroupIndex": index,
            "hide": True,
            "enableRowGroup": True,
            "enablePivot": True,
            "filter": "agDateColumnFilter" if dimension == "cob_date" else "agTextColumnFilter",
        })

    for column in VALUE_COLUMNS:
        definitions.append({
            "field": column,
            "headerName": column.upper(),
            "aggFunc": "sum",
            "enableValue": True,
            "filter": "agNumberColumnFilter",
            "type": "numericColumn",
            "cellDataType": False,
            "minWidth": 145,
            "valueFormatter": {
                "function": (
                    "params.value == null || params.value === '' ? '' : "
                    "(Number(params.value) === 0 ? '-' : "
                    "(Number(params.value) < 0 ? '(' : '') + "
                    "Math.abs(Number(params.value)).toLocaleString('en-US', "
                    "{minimumFractionDigits: 2, maximumFractionDigits: 2}) + "
                    "(Number(params.value) < 0 ? ')' : ''))"
                )
            },
            "cellClassRules": {
                "pnl-positive": "Number(params.value) > 0",
                "pnl-negative": "Number(params.value) < 0",
                "pnl-zero": "Number(params.value) === 0",
            },
        })

    return definitions


# ---------------------------------------------------------------------
# Dash application
# ---------------------------------------------------------------------
app = Dash(
    __name__,
    assets_folder=str(BASE_DIR / "assets"),
    assets_url_path="assets",
    include_assets_files=True,
)
app.title = "GM | PNL Reporting"

app.layout = html.Div(
    className="app-shell",
    children=[
        html.Div(
            className="topbar",
            children=[
                html.Div("GM", className="brand-mark"),
                html.Div("PNL Reporting", className="brand-title"),
            ],
        ),

        html.Div(
            className="page",
            children=[
                html.Div(
                    className="page-header",
                    children=[
                        html.Div([
                            html.H2("Dynamic PNL Aggregation"),
                            html.P(
                                "Configure fields in the Columns panel. Press Refresh Data to load "
                                "only the selected fields and measures."
                            ),
                        ]),
                        html.Div(
                            id="record-count",
                            className="record-count",
                            children="",
                        ),
                    ],
                ),

                # Hierarchy and measure selection is handled by AG Grid's
                # native Columns panel (same interaction as the supplied app).
                html.Div(
                    className="controls-card grid-controls-card",
                    children=[
                        html.Div(
                            className="control",
                            children=[
                                html.Label("Configure the report"),
                                html.Small(
                                    "Open the Columns panel on the right to add, "
                                    "remove or reorder Row Groups, Values and Pivot fields."
                                ),
                            ],
                        ),
                        html.Div(
                            className="refresh-area",
                            children=[
                                html.Button(
                                    "Refresh Data",
                                    id="refresh-button",
                                    n_clicks=0,
                                    className="refresh-button",
                                ),
                                html.Div(
                                    id="refresh-status",
                                    className="refresh-status",
                                ),
                            ],
                        ),
                    ],
                ),

                # Custom filter view
                html.Div(
                    className="filter-card",
                    children=[
                        html.Div(
                            className="filter-heading",
                            children=[
                                html.Div([
                                    html.H4("Filters"),
                                    html.P(
                                        "Filter the source records before "
                                        "aggregation."
                                    ),
                                ]),
                                html.Button(
                                    "Clear filters",
                                    id="clear-filters-button",
                                    n_clicks=0,
                                    className="clear-filter-button",
                                ),
                            ],
                        ),
                        html.Div(
                            className="filter-grid",
                            children=[
                                html.Div(
                                    className="control",
                                    children=[
                                        html.Label("COB Date"),
                                        dcc.Dropdown(
                                            id="filter-cob-date",
                                            options=FILTER_OPTIONS["cob_date"],
                                            multi=True,
                                            placeholder="All COB dates",
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="control",
                                    children=[
                                        html.Label("GBL"),
                                        dcc.Dropdown(
                                            id="filter-gbl",
                                            options=FILTER_OPTIONS["gbl"],
                                            multi=True,
                                            placeholder="All GBLs",
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="control",
                                    children=[
                                        html.Label("Subsub"),
                                        dcc.Dropdown(
                                            id="filter-subsub",
                                            options=FILTER_OPTIONS["subsub"],
                                            multi=True,
                                            placeholder="All subsubs",
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="control",
                                    children=[
                                        html.Label("Activity L1"),
                                        dcc.Dropdown(
                                            id="filter-activityl1",
                                            options=FILTER_OPTIONS["activityl1"],
                                            multi=True,
                                            placeholder="All activities",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),

                # Grid
                html.Div(
                    className="grid-card",
                    children=[
                        html.Div(
                            className="grid-heading",
                            children=[
                                html.H4("Data View"),
                                html.Span(
                                    "Configure Row Groups and Values in the Columns panel. Changes are "
                                    "applied to the data only after Refresh Data."
                                ),
                            ],
                        ),
                        dag.AgGrid(
                            id="pnl-grid",
                            rowData=[],
                            columnDefs=make_column_definitions(),
                            defaultColDef={
                                "sortable": True,
                                "filter": True,
                                "resizable": True,
                                "floatingFilter": True,
                                "suppressMenu": False,
                            },
                            enableEnterpriseModules=True,
                            dashGridOptions={
                                "animateRows": False,
                                "pagination": True,
                                "paginationPageSize": 50,
                                "paginationPageSizeSelector": [20, 50, 100],
                                "rowSelection": "single",
                                "suppressAggFuncInHeader": True,
                                "suppressRowClickSelection": True,
                                "groupDisplayType": "singleColumn",
                                "groupDefaultExpanded": 1,
                                "autoGroupColumnDef": {
                                    "headerName": "REFERENTIAL",
                                    "minWidth": 320,
                                    "pinned": "left",
                                    "cellRendererParams": {"suppressCount": False},
                                },
                                "rowGroupPanelShow": "always",
                                "pivotMode": True,
                                "sideBar": {
                                    "toolPanels": [
                                        {
                                            "id": "columns",
                                            "labelDefault": "Columns",
                                            "iconKey": "columns",
                                            "toolPanel": "agColumnsToolPanel",
                                        },
                                        {
                                            "id": "filters",
                                            "labelDefault": "Filters",
                                            "iconKey": "filter",
                                            "toolPanel": "agFiltersToolPanel",
                                        },
                                    ],
                                    "defaultToolPanel": "columns",
                                },
                            },
                            className="ag-theme-quartz",
                            style={"height": "620px", "width": "100%"},
                        ),
                    ],
                ),

                html.Div(
                    className="footer",
                    children=(
                        "Only selected Row Group and Value fields are sent to AG Grid. "
                        "Data is filtered and pre-aggregated when Refresh Data is pressed."
                    ),
                ),
            ],
        ),
    ],
)


# ---------------------------------------------------------------------
# Clear custom filters
# ---------------------------------------------------------------------
@app.callback(
    Output("filter-cob-date", "value"),
    Output("filter-gbl", "value"),
    Output("filter-subsub", "value"),
    Output("filter-activityl1", "value"),
    Input("clear-filters-button", "n_clicks"),
    prevent_initial_call=True,
)
def clear_filters(_):
    return [], [], [], []


# ---------------------------------------------------------------------
# Refresh hierarchy and respond to expand/collapse clicks
# ---------------------------------------------------------------------
def get_active_grid_columns(column_state):
    """
    Read the current AG Grid column configuration.

    A dimension is included in the server payload only when it is active as a
    Row Group or Pivot field. A measure is included only when it is active in
    Values (aggFunc is set). The columnState is read only when Refresh Data is
    pressed, so panel interactions do not trigger a callback.
    """
    state_by_id = {
        item.get("colId"): item
        for item in (column_state or [])
        if isinstance(item, dict) and item.get("colId")
    }

    # If AG Grid has not yet reported state, use the configured initial view.
    if not state_by_id:
        return list(DEFAULT_DIMENSIONS), list(DEFAULT_VALUES)

    active_dimensions = []
    for column in REFERENTIAL_COLUMNS:
        item = state_by_id.get(column, {})
        if item.get("rowGroup") or item.get("pivot"):
            active_dimensions.append(column)

    # Respect the Row Group ordering configured in the Columns panel.
    active_dimensions.sort(
        key=lambda col: (
            state_by_id.get(col, {}).get("rowGroupIndex")
            if state_by_id.get(col, {}).get("rowGroupIndex") is not None
            else 10_000 + REFERENTIAL_COLUMNS.index(col)
        )
    )

    active_values = []
    for column in VALUE_COLUMNS:
        item = state_by_id.get(column, {})
        if item.get("aggFunc"):
            active_values.append(column)

    return active_dimensions, active_values


def prepare_grid_data(filters, selected_dimensions, selected_values):
    """
    Filter and aggregate source data before transferring it to the browser.

    Only active dimension/value columns are retained. Grouping at the lowest
    selected hierarchy grain reduces the number of records sent to AG Grid,
    while AG Grid can still build and expand all selected hierarchy levels.
    """
    if not selected_dimensions:
        raise ValueError(
            "No Row Groups are selected. Add at least one referential field "
            "to Row Groups in the Columns panel, then press Refresh Data."
        )

    filtered = _apply_source_filters(SOURCE_DF, filters)

    # Work only with the selected columns, not the full source schema.
    required_columns = list(selected_dimensions) + list(selected_values)
    working = filtered[required_columns].copy()

    if "cob_date" in working.columns:
        working["cob_date"] = pd.to_datetime(
            working["cob_date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")

    source_count = len(working)

    # Aggregate at the most detailed selected row-group level.
    # This is safe because AG Grid will aggregate these pre-summed records
    # again at each parent hierarchy level.
    if selected_values:
        grouped = (
            working.groupby(
                selected_dimensions,
                dropna=False,
                sort=False,
                observed=True,
            )[selected_values]
            .sum()
            .reset_index()
        )
    else:
        grouped = working[selected_dimensions].drop_duplicates().reset_index(drop=True)

    # Keep payload schema deterministic and exclude every unselected field.
    grouped = grouped[required_columns]
    return grouped, source_count


@app.callback(
    Output("pnl-grid", "rowData"),
    Output("record-count", "children"),
    Output("refresh-status", "children"),
    Input("refresh-button", "n_clicks"),
    State("filter-cob-date", "value"),
    State("filter-gbl", "value"),
    State("filter-subsub", "value"),
    State("filter-activityl1", "value"),
    State("pnl-grid", "columnState"),
    prevent_initial_call=True,
)
def update_grid(
    _refresh_clicks,
    filter_cob_date,
    filter_gbl,
    filter_subsub,
    filter_activityl1,
    column_state,
):
    """
    Refresh data only on an explicit button click.

    Filter selections and AG Grid column state are State, not Input. Therefore
    changing a filter or adding/removing fields in the Columns panel does not
    cause a grid refresh until the user presses Refresh Data.
    """
    try:
        filters = {
            "cob_date": filter_cob_date or [],
            "gbl": filter_gbl or [],
            "subsub": filter_subsub or [],
            "activityl1": filter_activityl1 or [],
        }

        selected_dimensions, selected_values = get_active_grid_columns(
            column_state
        )

        result, source_count = prepare_grid_data(
            filters,
            selected_dimensions,
            selected_values,
        )

        records = result.astype(object).where(pd.notna(result), None).to_dict("records")
        print(records)
        print("------------------------")
        return (
            records,
            f"{len(records):,} aggregated rows · {source_count:,} source rows",
            (
                f"Refreshed · {len(selected_dimensions)} hierarchy fields · "
                f"{len(selected_values)} measures · "
                f"{len(records):,} rows sent to grid"
            ),
        )
    except Exception as exc:
        return no_update, no_update, f"Refresh failed: {exc}"


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
