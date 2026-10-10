import type { components, paths } from '@yearbook/openapi'

export type { paths }

type Schemas = components['schemas']

export type Me = Schemas['Me']
export type MeUpdate = Schemas['MeUpdate']
export type Event = Schemas['Event']
export type EventCreate = Schemas['EventCreate']
export type EventUpdate = Schemas['EventUpdate']
export type EventStatus = Schemas['EventStatus']
export type EventCounts = Schemas['EventCounts']
export type Viewer = Schemas['Viewer']
export type Guest = Schemas['Guest']
export type GridItem = Schemas['GridItem']
export type MediaDetail = Schemas['MediaDetail']
export type MediaGroup = Schemas['MediaGroup']
export type MediaPage = Schemas['MediaPage']
export type Variants = Schemas['Variants']
export type LikeResult = Schemas['LikeResult']
export type UploadFile = Schemas['UploadFile']
export type UploadInit = Schemas['UploadInit']
export type UploadPart = Schemas['UploadPart']
export type UploadStatus = Schemas['UploadStatus']
export type CompletedPart = Schemas['CompletedPart']
export type HostUploads = Schemas['HostUploads']
export type HostUploader = Schemas['HostUploader']
export type HostUploadItem = Schemas['HostUploadItem']
export type ZipTicket = Schemas['ZipTicket']
export type ErrorResponse = Schemas['ErrorResponse']
export type ErrorCode = ErrorResponse['error']['code']

export type Person = Schemas['Person']
export type PersonUpdate = Schemas['PersonUpdate']
export type PeopleList = Schemas['PeopleList']
export type Face = Schemas['Face']
export type Suggestion = Schemas['Suggestion']

export type AgentRequest = Schemas['AgentRequest']
export type AgentResponse = Schemas['AgentResponse']
export type AgentResult = Schemas['AgentResult']
export type Chip = Schemas['Chip']
export type SavedCommand = Schemas['SavedCommand']
export type Attachment = Schemas['Attachment']

export type Album = Schemas['Album']
export type AlbumCreate = Schemas['AlbumCreate']
export type AlbumUpdate = Schemas['AlbumUpdate']
export type AlbumDetail = Schemas['AlbumDetail']
export type Share = Schemas['Share']

export type EventSummary = Schemas['EventSummary']
export type YearSummary = Schemas['YearSummary']
export type YearRecap = Schemas['YearRecap']
export type TopPerson = Schemas['TopPerson']

export type Import = Schemas['Import']
export type ImportCreate = Schemas['ImportCreate']
export type ImportInit = Schemas['ImportInit']
export type ImportKind = Import['kind']

/** Chips shown in the gallery; the contract also admits person:{id}, album:{id} and library. */
export const mediaFilters = ['all', 'best', 'videos', 'mine', 'me'] as const
export type BaseFilter = (typeof mediaFilters)[number]
export type MediaFilter = BaseFilter | `person:${string}` | `album:${string}` | 'library'

export function isMediaFilter(value: unknown): value is MediaFilter {
  if (typeof value !== 'string') return false
  if ((mediaFilters as readonly string[]).includes(value) || value === 'library') return true
  return /^(person|album):[A-Za-z0-9_-]{22}$/.test(value)
}

export function personIdOf(filter: MediaFilter): string | null {
  return filter.startsWith('person:') ? filter.slice('person:'.length) : null
}
