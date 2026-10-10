// Package mail sends transactional email over SMTP (Mailpit in dev, any relay in prod).
package mail

import (
	"context"
	"fmt"
	"sync"

	gomail "github.com/wneessen/go-mail"
)

// Sender delivers one plain-text message. Tests swap in a recorder.
type Sender interface {
	Send(ctx context.Context, to, subject, text string) error
}

// SMTP sends through a relay without authentication (Mailpit) or with the credentials given.
type SMTP struct {
	Host string
	Port int
	From string
}

// Send delivers a single message.
func (s SMTP) Send(ctx context.Context, to, subject, text string) error {
	m := gomail.NewMsg()
	if err := m.From(s.From); err != nil {
		return fmt.Errorf("mail: from: %w", err)
	}
	if err := m.To(to); err != nil {
		return fmt.Errorf("mail: to: %w", err)
	}
	m.Subject(subject)
	m.SetBodyString(gomail.TypeTextPlain, text)
	c, err := gomail.NewClient(s.Host, gomail.WithPort(s.Port), gomail.WithTLSPolicy(gomail.TLSOpportunistic))
	if err != nil {
		return fmt.Errorf("mail: client: %w", err)
	}
	if err := c.DialAndSendWithContext(ctx, m); err != nil {
		return fmt.Errorf("mail: send: %w", err)
	}
	return nil
}

// Recorder keeps sent messages in memory for tests.
type Recorder struct {
	mu       sync.Mutex
	Messages []Message
}

// Message is one recorded email.
type Message struct {
	To, Subject, Text string
}

// Send records the message instead of delivering it.
func (r *Recorder) Send(_ context.Context, to, subject, text string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.Messages = append(r.Messages, Message{To: to, Subject: subject, Text: text})
	return nil
}

// Last returns the most recent message, if any.
func (r *Recorder) Last() (Message, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.Messages) == 0 {
		return Message{}, false
	}
	return r.Messages[len(r.Messages)-1], true
}

// MagicLinkText is the body of the sign-in email in both languages.
func MagicLinkText(link string) string {
	return "Hier ist dein Link zum Anmelden bei Yearbook. Er gilt 15 Minuten.\n" +
		"Here is your link to sign in to Yearbook. It is valid for 15 minutes.\n\n" +
		link + "\n"
}
