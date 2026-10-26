"""
Dash + dash-ag-grid PNL dashboard.
Expected: from data_service import request_data
request_data() returns a DataFrame with:
cobdate,gbl,subbusinessline,activityl1,activityl5,ptf,daily,mtd,ytd,ytdn1

Install: pip install dash dash-ag-grid pandas
Run: python app.py

Pivot Mode, enterprise grouping/aggregation and the Columns/Filters side panel
require AG Grid Enterprise and a valid license.
"""
import pandas as pd
from dash import Dash, Input, Output, callback, dcc, html
import dash_ag_grid as dag
from data_service import request_data  # Change to your module name if needed.

REQUIRED = ["cobdate", "gbl", "subbusinessline", "activityl1", "activityl5",
            "ptf", "daily", "mtd", "ytd", "ytdn1"]
DIMENSIONS = ["gbl", "subbusinessline", "activityl1", "activityl5", "ptf"]
VALUES = [("daily", "Daily PNL"), ("mtd", "MTD PNL"),
          ("ytd", "YTD PNL"), ("ytdn1", "YTD N-1 PNL")]

def load_data():
    df = request_data()
    if not isinstance(df, pd.DataFrame):
        raise TypeError("request_data() must return a pandas DataFrame.")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"request_data() missing columns: {missing}")
    df = df[REQUIRED].copy()
    df["cobdate"] = pd.to_datetime(df["cobdate"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["cobdate"] = df["cobdate"].fillna("(Invalid date)")
    for c in DIMENSIONS:
        df[c] = df[c].fillna("(Blank)").astype(str)
    for c, _ in VALUES:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def build_columns():
    columns = [{
        "field": "cobdate", "headerName": "COB Date", "hide": True,
        "enableRowGroup": True, "enablePivot": True,
        "filter": "agDateColumnFilter"
    }]
    for field in DIMENSIONS:
        columns.append({
            "field": field, "headerName": field.replace("_", " ").title(),
            "rowGroup": True, "hide": True,
            "enableRowGroup": True, "enablePivot": True,
            "filter": "agTextColumnFilter"
        })
    for field, title in VALUES:
        columns.append({
            "field": field, "headerName": title, "aggFunc": "sum",
            "enableValue": True, "filter": "agNumberColumnFilter",
            "type": "numericColumn", "minWidth": 145,
            "valueFormatter": {"function": """
                if (params.value == null || !Number.isFinite(Number(params.value))) return '-';
                const v = Number(params.value);
                const n = Math.abs(v).toLocaleString('en-US',{maximumFractionDigits:0});
                return v < 0 ? '(' + n + ')' : (v > 0 ? '+' + n : '-');
            """},
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
    dcc.Store(id="data-store"),
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
        html.Div([
            html.Div([html.Label("COB Date"),
                      dcc.Dropdown(id="date-filter", options=[], placeholder="All dates",
                                   clearable=True)], className="filter-control"),
            html.Div([html.Label("GBL"),
                      dcc.Dropdown(id="gbl-filter", options=[], placeholder="All GBLs",
                                   clearable=True)], className="filter-control"),
            html.Div([html.Label("Sub Business Line"),
                      dcc.Dropdown(id="sbl-filter", options=[], placeholder="All sub-business lines",
                                   clearable=True)], className="filter-control"),
            html.Div([html.Label("Portfolio"),
                      dcc.Input(id="ptf-search", placeholder="Search portfolio...", debounce=True)],
                     className="filter-control")
        ], className="filters-panel"),
        html.Div([
            html.Div([html.Div("Total Daily PNL", className="kpi-label"),
                      html.Div("—", id="kpi-daily", className="kpi-value")], className="kpi-card"),
            html.Div([html.Div("Total MTD PNL", className="kpi-label"),
                      html.Div("—", id="kpi-mtd", className="kpi-value")], className="kpi-card"),
            html.Div([html.Div("Total YTD PNL", className="kpi-label"),
                      html.Div("—", id="kpi-ytd", className="kpi-value")], className="kpi-card"),
            html.Div([html.Div("Portfolios", className="kpi-label"),
                      html.Div("—", id="kpi-count", className="kpi-value")], className="kpi-card")
        ], className="kpi-grid"),
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
                autoGroupColumnDef={"headerName": "Business Hierarchy", "minWidth": 290,
                                    "pinned": "left",
                                    "cellRendererParams": {"suppressCount": False}},
                enableEnterpriseModules=True,
                dashGridOptions={
                    "pivotMode": True,
                    "groupDisplayType": "singleColumn",
                    "groupDefaultExpanded": 1,
                    "animateRows": True,
                    "suppressAggFuncInHeader": True,
                    "sideBar": {"toolPanels": [
                        {"id": "columns", "labelDefault": "Columns", "iconKey": "columns",
                         "toolPanel": "agColumnsToolPanel"},
                        {"id": "filters", "labelDefault": "Filters", "iconKey": "filter",
                         "toolPanel": "agFiltersToolPanel"}
                    ], "defaultToolPanel": "columns"},
                    "pagination": True, "paginationPageSize": 50,
                    "getRowId": {"function": "params.data._row_id"}
                },
                className="ag-theme-alpine pnl-grid",
                style={"height": "650px", "width": "100%"}
            ),
            html.Div("Pivot Mode, grouping/aggregation and the Columns/Filters side panel require AG Grid Enterprise and a valid license.",
                     className="footnote")
        ], className="grid-panel")
    ], className="content")
])

@callback(
    Output("data-store", "data"), Output("date-filter", "options"),
    Output("gbl-filter", "options"), Output("sbl-filter", "options"),
    Output("status", "children"), Input("refresh", "n_clicks")
)
def refresh_data(_clicks):
    try:
        df = load_data()
        dates = sorted(df["cobdate"].unique().tolist(), reverse=True)
        gbls = sorted(df["gbl"].unique().tolist())
        sbls = sorted(df["subbusinessline"].unique().tolist())
        return (df.to_dict("records"),
                [{"label": x, "value": x} for x in dates],
                [{"label": x, "value": x} for x in gbls],
                [{"label": x, "value": x} for x in sbls],
                f"Loaded {len(df):,} records")
    except Exception as exc:
        return [], [], [], [], f"Data load failed: {exc}"

@callback(
    Output("pnl-grid", "rowData"), Output("kpi-daily", "children"),
    Output("kpi-mtd", "children"), Output("kpi-ytd", "children"),
    Output("kpi-count", "children"),
    Input("data-store", "data"), Input("date-filter", "value"),
    Input("gbl-filter", "value"), Input("sbl-filter", "value"),
    Input("ptf-search", "value")
)
def filter_data(records, cobdate, gbl, sbl, ptf_search):
    if not records:
        return [], "—", "—", "—", "0"
    df = pd.DataFrame(records)
    if cobdate:
        df = df[df["cobdate"] == cobdate]
    if gbl:
        df = df[df["gbl"] == gbl]
    if sbl:
        df = df[df["subbusinessline"] == sbl]
    if ptf_search:
        df = df[df["ptf"].astype(str).str.contains(ptf_search, case=False, na=False)]
    df = df.reset_index(drop=True)
    df["_row_id"] = df.index.astype(str)

    def fmt(v):
        v = float(v or 0)
        return f"({abs(v):,.0f})" if v < 0 else (f"+{v:,.0f}" if v > 0 else "-")

    return (df.to_dict("records"), fmt(df["daily"].sum()), fmt(df["mtd"].sum()),
            fmt(df["ytd"].sum()), f"{df['ptf'].nunique():,}")

app.index_string = """
<!DOCTYPE html><html><head>{%metas%}<title>PNL Reporting</title>{%favicon%}{%css%}
<style>
*{box-sizing:border-box}body{margin:0;background:#F4F7FB;color:#1E293B;font-family:Inter,"Segoe UI",Arial,sans-serif}
.topbar{height:70px;background:#17365D;color:white;padding:0 28px;display:flex;align-items:center;justify-content:space-between}
.brand{display:flex;align-items:center;gap:14px}.brand-mark{background:white;color:#17365D;font-weight:800;padding:10px;border-radius:7px}
.eyebrow{font-size:10px;letter-spacing:1.8px;opacity:.8}.brand-title{font-size:20px;font-weight:700;margin-top:3px}
.header-note{font-size:11px;letter-spacing:1.4px;opacity:.8}.content{max-width:1800px;margin:auto;padding:25px 28px 40px}
.page-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;gap:15px}
.page-title{margin:0;font-size:27px;color:#17365D}.page-subtitle{margin-top:7px;font-size:13px;color:#64748B}
.primary-button{background:#2563EB;border:0;border-radius:7px;color:white;padding:11px 16px;cursor:pointer;font-weight:650}
.filters-panel{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:14px;padding:16px;background:white;border:1px solid #DCE4EE;border-radius:10px;margin-bottom:18px}
.filter-control label{display:block;font-size:11px;font-weight:700;color:#64748B;margin-bottom:7px}
.filter-control input{width:100%;height:37px;border:1px solid #DCE4EE;border-radius:7px;padding:0 10px}
.filter-control .Select-control{border-color:#DCE4EE;border-radius:7px;min-height:37px}
.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}
.kpi-card{background:white;border:1px solid #DCE4EE;border-radius:10px;padding:17px 20px}
.kpi-label{color:#64748B;font-size:11px;font-weight:800;letter-spacing:.6px}.kpi-value{color:#15803D;font-size:27px;font-weight:750;margin-top:10px}
.grid-panel{background:white;border:1px solid #DCE4EE;border-radius:10px;padding:20px}
.grid-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:15px}
.section-title{margin:0;color:#17365D;font-size:18px}.section-subtitle{margin-top:6px;color:#64748B;font-size:12px}
.status-text{font-size:12px;color:#64748B}.pnl-grid{--ag-font-family:Inter,"Segoe UI",Arial,sans-serif;--ag-font-size:12px;--ag-header-background-color:#EDF3FA;--ag-header-foreground-color:#334155;--ag-border-color:#DCE4EE;--ag-row-hover-color:#EFF6FF;--ag-odd-row-background-color:#FAFCFE}
.pnl-grid .ag-header-cell-text{font-size:10px;font-weight:800;letter-spacing:.4px}.pnl-positive{color:#15803D;font-weight:650}.pnl-negative{color:#DC2626;font-weight:650}.pnl-zero{color:#94A3B8}
.footnote{color:#64748B;font-size:11px;margin-top:12px;line-height:1.5}
@media(max-width:950px){.filters-panel,.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.content{padding:15px 10px}.filters-panel,.kpi-grid{grid-template-columns:1fr}.page-heading{align-items:flex-start;flex-direction:column}.header-note{display:none}}
</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>
"""

if __name__ == "__main__":
    app.run(debug=True)
