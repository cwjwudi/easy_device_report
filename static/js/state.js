export const initialDesignerState = {
  activeTab: "page",
  selectedRegion: "header",
  selectedCell: { region: "header", row: 0, col: 0 },
  selectedBodyTable: 0,
  bodyEditorOpen: false,
  schema: null,
  opcuaNodes: [],
};

export const initialOpcuaBrowserState = {
  nodes: [],
  childrenByNode: {},
  expanded: {},
  points: [],
  selectedNodeId: null,
};
