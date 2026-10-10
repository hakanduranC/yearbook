import type { components, paths } from '@yearbook/openapi'

export type { paths }

type Schemas = components['schemas']

export type Me = Schemas['Me']
export type MeUpdate = Schemas['MeUpdate']
export type Event = Schemas['Event']
export type EventCreate = Schemas['EventCreate']
export type EventUpdate = Schemas['EventUpdate']
export type EventStatus = Schemas['EventStatus']
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

export type MediaFilter = NonNullable<
  NonNullable<paths['/events/{slug}/media']['get']['parameters']['query']>['filter']
>
export const mediaFilters = [
  'all',
  'best',
  'videos',
  'mine',
] as const satisfies readonly MediaFilter[]
