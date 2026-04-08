export interface TangleNavFolderItem {
  kind: 'folder'
  key: string
  label: string
  children: TangleNavItemType[]
}

export interface TangleNavHeadingItem {
  kind: 'heading'
  key: string
  label: string
  filePath: string
  nodeId: number
  children: TangleNavHeadingItem[]
  collapsible: boolean
}

export type TangleNavItemType = TangleNavFolderItem | TangleNavHeadingItem

export type SpecNavFolderItem = TangleNavFolderItem
export type SpecNavHeadingItem = TangleNavHeadingItem
export type SpecNavItemType = TangleNavItemType
