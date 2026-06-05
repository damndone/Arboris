// frontend/src/lineage/detail/sections/sectionRegistry.ts
//
// V1.5.2 — moved to frontend/src/workbench/registry/sectionRegistry.ts
// as part of Plan §4 (registry promotion). This file is a back-compat
// re-export so V1.5.0/1.5.1 consumers (DetailDrawer + existing tests)
// keep working without touching imports. Remove this shim once all
// callers import from `workbench/registry/sectionRegistry` directly.

export {
  sectionRegistry,
  _needsTrust,
  type SectionEntry,
  type SectionSpec,
} from "../../../workbench/registry/sectionRegistry";
