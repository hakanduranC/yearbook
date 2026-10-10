package media

import (
	"encoding/json"

	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
)

// URLBuilder turns a public object key into a CDN URL (storage.Client.PublicURL).
type URLBuilder func(key string) string

// GridItemFromRow maps one GetGridRows row onto the wire shape.
func GridItemFromRow(r db.GetGridRowsRow, publicURL URLBuilder) api.GridItem {
	item := api.GridItem{
		Id:         ids.Encode(r.ID),
		Kind:       api.GridItemKind(r.Kind),
		State:      api.GridItemState(r.State),
		CapturedAt: r.CapturedAt,
		Width:      int(deref32(r.Width)),
		Height:     int(deref32(r.Height)),
		LikeCount:  int(r.LikeCount),
		Liked:      r.Liked,
		Me:         r.Me,
		Mine:       &r.Mine,
		PersonIds:  make([]api.Id, 0, len(r.PersonIds)),
		Score:      r.Score,
		Processing: r.State != db.MediaStateReady,
	}
	for _, pid := range r.PersonIds {
		item.PersonIds = append(item.PersonIds, ids.Encode(pid))
	}
	analyzed := r.AnalyzedAt != nil
	item.Analyzed = &analyzed
	if r.CapturedSrc != nil {
		src := api.GridItemCapturedSrc(*r.CapturedSrc)
		item.CapturedSrc = &src
	}
	if r.DurationMs != nil {
		d := int(*r.DurationMs)
		item.DurationMs = &d
	}
	keys := map[string]string{}
	_ = json.Unmarshal(r.Variants, &keys)
	if len(keys) > 0 {
		item.Variants = VariantsFromKeys(keys, publicURL)
		if k, ok := keys["poster"]; ok {
			u := publicURL(k)
			item.Poster = &u
		}
		if k, ok := keys["video"]; ok {
			u := publicURL(k)
			item.VideoUrl = &u
		}
	}
	return item
}

// VariantsFromKeys builds the four image URLs from a name→key map; nil when none of them exist.
func VariantsFromKeys(keys map[string]string, publicURL URLBuilder) *api.Variants {
	v := &api.Variants{}
	found := false
	set := func(dst **string, name string) {
		if k, ok := keys[name]; ok {
			u := publicURL(k)
			*dst = &u
			found = true
		}
	}
	set(&v.Thumb, "thumb")
	set(&v.Small, "small")
	set(&v.Medium, "medium")
	set(&v.Large, "large")
	if !found {
		return nil
	}
	return v
}

// DetailFromRow builds a MediaDetail on top of the GridItem fields.
func DetailFromRow(r db.GetGridRowsRow, publicURL URLBuilder, canDelete bool) api.MediaDetail {
	g := GridItemFromRow(r, publicURL)
	d := api.MediaDetail{
		Id: g.Id, Kind: api.MediaDetailKind(g.Kind), State: api.MediaDetailState(g.State),
		CapturedAt: g.CapturedAt, DurationMs: g.DurationMs, Width: g.Width, Height: g.Height,
		LikeCount: g.LikeCount, Liked: g.Liked, Me: g.Me, Mine: g.Mine, PersonIds: g.PersonIds,
		Poster: g.Poster, Processing: g.Processing, Score: g.Score, Variants: g.Variants, VideoUrl: g.VideoUrl,
		OriginalFilename: r.OriginalFilename, PlaceName: r.PlaceName, CanDelete: canDelete, Analyzed: g.Analyzed,
	}
	if g.CapturedSrc != nil {
		src := api.MediaDetailCapturedSrc(*g.CapturedSrc)
		d.CapturedSrc = &src
	}
	name := r.UploaderName
	d.Uploader.DisplayName = &name
	isYou := r.Mine
	d.Uploader.IsYou = &isYou
	return d
}

func deref32(p *int32) int32 {
	if p == nil {
		return 0
	}
	return *p
}
