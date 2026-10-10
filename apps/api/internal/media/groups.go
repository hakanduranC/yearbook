package media

import (
	"time"

	api "yearbook/api/internal/gen/api"
)

// DayPart returns the grouping key for a local time: morning 05–11, afternoon 11–17,
// evening 17–22, night 22–05 (see docs/CONVENTIONS.md).
func DayPart(hour int) string {
	switch {
	case hour >= 5 && hour < 11:
		return "morning"
	case hour >= 11 && hour < 17:
		return "afternoon"
	case hour >= 17 && hour < 22:
		return "evening"
	default:
		return "night"
	}
}

// partBounds returns the start and end of the day part that contains t (in t's location).
// Night runs from 22:00 to 05:00 the next day, so an hour before 05:00 belongs to the previous evening's night.
func partBounds(t time.Time) (start, end time.Time) {
	y, m, d := t.Date()
	day := func(h int) time.Time { return time.Date(y, m, d, h, 0, 0, 0, t.Location()) }
	switch DayPart(t.Hour()) {
	case "morning":
		return day(5), day(11)
	case "afternoon":
		return day(11), day(17)
	case "evening":
		return day(17), day(22)
	default:
		if t.Hour() >= 22 {
			return day(22), day(24 + 5)
		}
		return day(-2), day(5)
	}
}

// Groups buckets items (already sorted newest first) by calendar day and day part in loc.
func Groups(times []time.Time, loc *time.Location) []api.MediaGroup {
	var groups []api.MediaGroup
	for _, t := range times {
		local := t.In(loc)
		start, end := partBounds(local)
		if n := len(groups); n > 0 && groups[n-1].Start.Equal(start) {
			groups[n-1].Count++
			continue
		}
		groups = append(groups, api.MediaGroup{
			Label: DayPart(local.Hour()),
			Start: start.UTC(),
			End:   end.UTC(),
			Count: 1,
		})
	}
	if groups == nil {
		groups = []api.MediaGroup{}
	}
	return groups
}
