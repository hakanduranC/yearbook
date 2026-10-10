package ids

import "testing"

func TestRoundTrip(t *testing.T) {
	id := New()
	s := Encode(id)
	if len(s) != 22 {
		t.Fatalf("wire length %d", len(s))
	}
	back, err := Decode(s)
	if err != nil || string(back) != string(id) {
		t.Fatalf("decode: %v", err)
	}
	for _, bad := range []string{"", "short", s + "x", "AAAAAAAAAAAAAAAAAAAAA="} {
		if _, err := Decode(bad); err == nil {
			t.Errorf("%q should be invalid", bad)
		}
	}
}
