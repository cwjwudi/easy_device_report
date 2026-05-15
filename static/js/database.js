export function defaultDatabaseConnection(demoDbPath = "") {
  return { type: "sqlite", path: demoDbPath };
}
