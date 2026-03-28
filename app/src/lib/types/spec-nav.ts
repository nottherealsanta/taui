export interface SpecNavFolderItem {
  kind: 'folder'
  key: string
  label: string
  children: SpecNavItemType[]
}

export interface SpecNavHeadingItem {
  kind: 'heading'
  key: string
  label: string
  filePath: string
  nodeId: number
  children: SpecNavHeadingItem[]
  collapsible: boolean
}

export type SpecNavItemType = SpecNavFolderItem | SpecNavHeadingItem