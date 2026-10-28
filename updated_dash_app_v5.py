"""Dash + dash-ag-grid PNL dashboard.

Expected: data_service.py exposes request_data() returning a DataFrame with:
cobdate,gbl,subbusinessline,activityl1,activityl5,ptf,daily,mtd,ytd,ytdn1

Install: pip install dash dash-ag-grid pandas
Run: python updated_dash_app.py

AG Grid Enterprise features (pivoting, grouping/aggregation and side panels)
require an appropriate license.
"""
from time import perf_counter
import pandas as pd
from dash import Dash, Input, Output, State, callback, dcc, html
import dash_ag_grid as dag
from data_service import request_data

REQUIRED = ["cobdate", "gbl", "subbusinessline", "activityl1", "activityl5",
            "ptf", "daily", "mtd", "ytd", "ytdn1"]
DIMENSIONS = ["gbl", "subbusinessline", "activityl1", "activityl5", "ptf"]
VALUES = [("daily", "Daily PNL"), ("mtd", "MTD PNL"),
          ("ytd", "YTD PNL"), ("ytdn1", "YTD N-1 PNL")]

# Keep the DataFrame on the server instead of serializing the entire dataset into
# dcc.Store and reconstructing it on every filter change.
_DATA_CACHE = None
_DATA_VERSION = 0


def load_data():
    df = request_data()
    if not isinstance(df, pd.DataFrame):
        raise TypeError("request_data() must return a pandas DataFrame.")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"request_data() missing columns: {missing}")

    # Select only columns used by this dashboard and normalize once on load.
    df = df[REQUIRED].copy()
    df["cobdate"] = pd.to_datetime(df["cobdate"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["cobdate"] = df["cobdate"].fillna("(Invalid date)")
    for col in DIMENSIONS:
        df[col] = df[col].fillna("(Blank)").astype(str)
    for col, _ in VALUES:
        # Whole numbers are used both in portfolio rows and in aggregations.
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(0)
    return df


def number_formatter_js():
    return """
        if (params.value == null || !Number.isFinite(Number(params.value))) return '-';
        const v = Math.round(Number(params.value));
        const n = Math.abs(Math.round(v)).toLocaleString('en-US', { useGrouping: true, maximumFractionDigits: 0 });
        return v < 0 ? '(' + n + ')' : (v > 0 ? '+' + n : '-');
    """


def build_columns():
    columns = [{
        "field": "cobdate", "headerName": "COB Date", "hide": True,
        "enableRowGroup": True, "enablePivot": True,
        "filter": "agDateColumnFilter"
    }]
    for field in DIMENSIONS:
        columns.append({
            "field": field,
            "headerName": field.replace("_", " ").title(),
            "rowGroup": True, "hide": True,
            "enableRowGroup": True, "enablePivot": True,
            "filter": "agTextColumnFilter"
        })
    for field, title in VALUES:
        columns.append({
            "field": field, "headerName": title, "aggFunc": "sum",
            "enableValue": True, "filter": "agNumberColumnFilter",
            "type": "numericColumn", "minWidth": 145,
            # Disable AG Grid's inferred number cell type: its built-in formatter
            # can override custom formatters for group/aggregated values.
            "cellDataType": False,
            "valueFormatter": {"function": number_formatter_js()},
            "cellClassRules": {
                "pnl-positive": "Number(params.value) > 0",
                "pnl-negative": "Number(params.value) < 0",
                "pnl-zero": "Number(params.value) === 0"
            }
        })
    return columns


app = Dash(__name__)
app.title = "Global Markets | PNL Reporting"

app.layout = html.Div([
    dcc.Store(id="data-version", data=0),
    html.Header([
        html.Div([html.Div("GM", className="brand-mark"),
                  html.Div([html.Div("GLOBAL MARKETS", className="eyebrow"),
                            html.Div("PNL Reporting", className="brand-title")])],
                 className="brand"),
        html.Div("REPORTING PLATFORM", className="header-note")
    ], className="topbar"),
    html.Main([
        html.Div([
            html.Div([html.H1("Hierarchical PNL Report", className="page-title"),
                      html.Div("Filter, group, pivot and drill down to portfolio level.",
                               className="page-subtitle")]),
            html.Button("↻ Refresh data", id="refresh", n_clicks=0, className="primary-button")
        ], className="page-heading"),

        # Independent request/response section. Its callback does not update the grid.
        html.Section([
            html.Label("Request / command", htmlFor="request-input", className="request-label"),
            html.Div([
                dcc.Input(id="request-input", type="text",
                          placeholder="Enter a request...", className="request-input", debounce=False),
                html.Button("Send", id="send-request", n_clicks=0, className="send-button")
            ], className="request-row"),
            html.Div("", id="request-response", className="request-response", role="status")
        ], className="request-panel"),

        html.Div([
            html.Div([html.Label("COB Date"),
                      dcc.Dropdown(id="date-filter", options=[], value=None,
                                   placeholder="Select COB date", clearable=False)], className="filter-control"),
            html.Div([html.Label("GBL"),
                      dcc.Dropdown(id="gbl-filter", options=[], placeholder="All GBLs",
                                   clearable=True)], className="filter-control"),
            html.Div([html.Label("Activity L5"),
                      dcc.Dropdown(id="activityl5-filter", options=[], placeholder="All Activity L5 values",
                                   clearable=True)], className="filter-control"),
            html.Div([html.Label("Portfolio"),
                      dcc.Input(id="ptf-search", placeholder="Search portfolio...", debounce=True)],
                     className="filter-control")
        ], className="filters-panel"),
        html.Section([
            html.Div([html.Div([html.H2("PNL data grid", className="section-title"),
                                html.Div("Use header filters or the right-side Columns panel to configure Rows, Columns and Values.",
                                         className="section-subtitle")]),
                      html.Div(id="status", className="status-text")], className="grid-heading"),
            dag.AgGrid(
                id="pnl-grid", rowData=[], columnDefs=build_columns(),
                defaultColDef={"sortable": True, "filter": True, "floatingFilter": True,
                               "resizable": True, "minWidth": 115,
                               "enableRowGroup": True, "enablePivot": True, "enableValue": True},
                enableEnterpriseModules=True,
                dashGridOptions={
                    "autoGroupColumnDef": {"headerName": "Business Hierarchy", "minWidth": 290,
                                           "pinned": "left",
                                           "cellRendererParams": {"suppressCount": False}},
                    "pivotMode": True,
                    "groupDisplayType": "singleColumn",
                    "groupDefaultExpanded": 1,
                    "animateRows": False,
                    "suppressAggFuncInHeader": True,
                    # Apply number formatting to dynamically generated pivot result columns.
                    "processPivotResultColDef": {
                        # AG Grid passes the generated column definition itself
                        # to this callback (not a params object). Mutate colDef.
                        "function": """
                            colDef.cellDataType = false;
                            colDef.valueFormatter = function(params) {
                                if (params.value == null || params.value === '') return '-';
                                const value = Number(params.value);
                                if (!Number.isFinite(value)) return '-';
                                const rounded = Math.round(value);
                                const formatted = Math.abs(rounded).toLocaleString('en-US', {
                                    useGrouping: true,
                                    maximumFractionDigits: 0
                                });
                                return rounded < 0 ? '(' + formatted + ')' :
                                       rounded > 0 ? '+' + formatted : '-';
                            };
                        """
                    },
                    "sideBar": {"toolPanels": [
                        {"id": "columns", "labelDefault": "Columns", "iconKey": "columns",
                         "toolPanel": "agColumnsToolPanel"},
                        {"id": "filters", "labelDefault": "Filters", "iconKey": "filter",
                         "toolPanel": "agFiltersToolPanel"}
                    ], "defaultToolPanel": "columns"},
                    "pagination": True, "paginationPageSize": 100,
                    "getRowId": {"function": "params.data._row_id"}
                },
                className="ag-theme-alpine pnl-grid",
                style={"height": "850px", "width": "100%"}
            ),
            html.Div("Pivot Mode, grouping/aggregation and the Columns/Filters side panel require AG Grid Enterprise and a valid license.",
                     className="footnote")
        ], className="grid-panel")
    ], className="content")
])


@callback(
    Output("data-version", "data"),
    Output("date-filter", "options"), Output("date-filter", "value"),
    Output("gbl-filter", "options"), Output("activityl5-filter", "options"),
    Output("status", "children"),
    Input("refresh", "n_clicks")
)
def refresh_data(_clicks):
    global _DATA_CACHE, _DATA_VERSION
    started = perf_counter()
    try:
        df = load_data()
        _DATA_CACHE = df
        _DATA_VERSION += 1
        dates = sorted(df.loc[df["cobdate"] != "(Invalid date)", "cobdate"].unique().tolist(), reverse=True)
        gbls = sorted(df["gbl"].unique().tolist())
        activity_l5_values = sorted(df["activityl5"].unique().tolist())
        selected_date = dates[0] if dates else None  # Select latest COB date on load.
        elapsed = perf_counter() - started
        return (
            _DATA_VERSION,
            [{"label": x, "value": x} for x in dates], selected_date,
            [{"label": x, "value": x} for x in gbls],
            [{"label": x, "value": x} for x in activity_l5_values],
            f"Loaded {len(df):,} records in {elapsed:.2f}s"
        )
    except Exception as exc:
        _DATA_CACHE = None
        return _DATA_VERSION, [], None, [], [], f"Data load failed: {exc}"


@callback(
    Output("pnl-grid", "rowData"),
    Input("data-version", "data"), Input("date-filter", "value"),
    Input("gbl-filter", "value"), Input("activityl5-filter", "value"),
    Input("ptf-search", "value")
)
def filter_data(_version, cobdate, gbl, activityl5, ptf_search):
    if _DATA_CACHE is None or _DATA_CACHE.empty:
        return []
    # Filter the cached server-side DataFrame; do not reconstruct it from client JSON.
    df = _DATA_CACHE
    if cobdate:
        df = df[df["cobdate"] == cobdate]
    if gbl:
        df = df[df["gbl"] == gbl]
    if activityl5:
        df = df[df["activityl5"] == activityl5]
    if ptf_search:
        df = df[df["ptf"].str.contains(str(ptf_search), case=False, na=False, regex=False)]
    df = df.reset_index(drop=True).copy()
    df["_row_id"] = df.index.astype(str)
    return df.to_dict("records")


def handle_request(user_text):
    """Replace this function body with the business function/API you want to call."""
    text = (user_text or "").strip()
    if not text:
        return "Enter a request before selecting Send."
    # Placeholder response makes the independent input/button workflow testable.
    return f"Request received: {text}"


@callback(
    Output("request-response", "children"),
    Input("send-request", "n_clicks"),
    State("request-input", "value"),
    prevent_initial_call=True
)
def send_request(_clicks, user_text):
    # This callback only updates the response section, so it does not refresh the grid.
    try:
        return handle_request(user_text)
    except Exception as exc:
        return f"Request failed: {exc}"


app.index_string = """
<!DOCTYPE html><html><head>{%metas%}<title>PNL Reporting</title>{%favicon%}{%css%}
<style>
*{box-sizing:border-box}body{margin:0;background:#F5F8F5;color:#1F2933;font-family:Inter,"Segoe UI",Arial,sans-serif}
.topbar{height:70px;background:#166534;color:white;padding:0 28px;display:flex;align-items:center;justify-content:space-between}
.brand{display:flex;align-items:center;gap:14px}.brand-mark{background:white;color:#166534;font-weight:800;padding:10px;border-radius:7px}
.eyebrow{font-size:10px;letter-spacing:1.8px;opacity:.85}.brand-title{font-size:20px;font-weight:700;margin-top:3px}
.header-note{font-size:11px;letter-spacing:1.4px;opacity:.85}.content{max-width:1800px;margin:auto;padding:25px 28px 40px}
.page-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:15px}
.page-title{margin:0;font-size:27px;color:#166534}.page-subtitle{margin-top:7px;font-size:13px;color:#64748B}
.primary-button,.send-button{background:#7C3AED;border:0;border-radius:7px;color:white;padding:11px 16px;cursor:pointer;font-weight:650}
.primary-button:hover,.send-button:hover{background:#6D28D9}
.request-panel{background:white;border:1px solid #D7E7DA;border-radius:10px;padding:14px 16px;margin-bottom:16px}
.request-label{display:block;font-size:11px;font-weight:750;color:#52665A;margin-bottom:7px}
.request-row{display:flex;gap:10px}.request-input{flex:1;min-width:0;height:39px;border:1px solid #CFE0D2;border-radius:7px;padding:0 11px;font:inherit}
.request-response{font-size:12px;color:#166534;margin-top:8px;min-height:0;overflow-wrap:anywhere}
.filters-panel{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:14px;padding:16px;background:white;border:1px solid #D7E7DA;border-radius:10px;margin-bottom:18px}
.filter-control label{display:block;font-size:11px;font-weight:700;color:#64748B;margin-bottom:7px}
.filter-control input{width:100%;height:37px;border:1px solid #D7E7DA;border-radius:7px;padding:0 10px}
.filter-control .Select-control{border-color:#D7E7DA;border-radius:7px;min-height:37px}
.grid-panel{background:white;border:1px solid #D7E7DA;border-radius:10px;padding:20px}
.grid-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:15px}
.section-title{margin:0;color:#166534;font-size:18px}.section-subtitle{margin-top:6px;color:#64748B;font-size:12px}
.status-text{font-size:12px;color:#64748B}.pnl-grid{--ag-font-family:Inter,"Segoe UI",Arial,sans-serif;--ag-font-size:12px;--ag-header-background-color:#E8F5E9;--ag-header-foreground-color:#254B32;--ag-border-color:#D7E7DA;--ag-row-hover-color:#F0FDF4;--ag-odd-row-background-color:#FAFCFA;--ag-selected-row-background-color:#DCFCE7}
.pnl-grid .ag-header-cell-text{font-size:10px;font-weight:800;letter-spacing:.4px}.pnl-positive{color:#15803D;font-weight:650}.pnl-negative{color:#DC2626;font-weight:650}.pnl-zero{color:#94A3B8}
.footnote{color:#64748B;font-size:11px;margin-top:12px;line-height:1.5}
@media(max-width:950px){.filters-panel{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.content{padding:15px 10px}.filters-panel{grid-template-columns:1fr}.page-heading{align-items:flex-start;flex-direction:column}.header-note{display:none}}
</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>
"""

if __name__ == "__main__":
    app.run(debug=True)
