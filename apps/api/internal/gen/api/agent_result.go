package api

// AgentResult is the structured result the UI renders (components.schemas.AgentResult in the
// contract). The contract models it as a oneOf discriminated by kind; the generator cannot map an
// inline oneOf, so the union is flattened here with every variant's fields optional. Fields not
// used by a kind stay nil and are omitted on the wire.
type AgentResult struct {
	Kind string `json:"kind"` // media | people | stat | album | clarify | empty

	Title    *string     `json:"title,omitempty"`
	MediaIds *[]Id       `json:"media_ids,omitempty"`
	Items    *[]GridItem `json:"items,omitempty"`
	GroupBy  *string     `json:"group_by,omitempty"` // time | person | none
	Persons  *[]Person   `json:"persons,omitempty"`
	Value    *string     `json:"value,omitempty"`
	Detail   *string     `json:"detail,omitempty"`
	Album    *Album      `json:"album,omitempty"`
	Question *string     `json:"question,omitempty"`
	Options  *[]string   `json:"options,omitempty"`
}
