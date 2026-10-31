var dagfuncs = window.dashAgGridComponentFunctions =
    window.dashAgGridComponentFunctions || {};

dagfuncs.TreeCellRenderer = function (props) {
    const data = props.data || {};
    const level = Number(data._level || 0);
    const hasChildren = Boolean(data._has_children);
    const expanded = Boolean(data._expanded);

    const toggle = hasChildren
        ? React.createElement(
            "button",
            {
                type: "button",
                className: "tree-toggle",
                title: expanded ? "Collapse" : "Expand",
                "aria-label": expanded ? "Collapse row" : "Expand row",
                onClick: function (event) {
                    event.stopPropagation();
                    if (props.setData) {
                        props.setData({
                            path_key: data._path_key,
                            expanded: !expanded
                        });
                    }
                }
            },
            expanded ? "▾" : "▸"
        )
        : React.createElement("span", {
            className: "tree-toggle-placeholder"
        });

    return React.createElement(
        "div",
        {
            className: "tree-cell",
            style: { paddingLeft: (level * 22 + 4) + "px" }
        },
        toggle,
        React.createElement(
            "span",
            { className: level === 0 ? "tree-label tree-root" : "tree-label" },
            data.Referential == null ? "" : String(data.Referential)
        )
    );
};
