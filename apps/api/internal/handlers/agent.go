package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"yearbook/api/internal/agent"
	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	api "yearbook/api/internal/gen/api"
	db "yearbook/api/internal/gen/db"
	"yearbook/api/internal/ids"
	"yearbook/api/internal/mail"
	"yearbook/api/internal/middleware"
)

// The language-model loop runs in the Python agent service (apps/agent). These handlers
// authenticate the caller, check the event scope and proxy the body with the actor headers from
// docs/CONVENTIONS.md ("Agent"). The service calls back into /mcp as the same principal.

const agentProxyTimeout = 30 * time.Second

// errAgentUnavailable is the contract's 503 for a missing or unreachable agent service.
var errAgentUnavailable = &apperr.Error{Status: http.StatusServiceUnavailable, Code: apperr.Internal, Message: "agent_not_configured"}

// rawResponse relays the agent service's answer unchanged.
type rawResponse struct {
	status int
	body   []byte
}

func (r rawResponse) write(w http.ResponseWriter) error {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(r.status)
	_, err := w.Write(r.body)
	return err
}

func (r rawResponse) VisitSendAgentMessageResponse(w http.ResponseWriter) error { return r.write(w) }
func (r rawResponse) VisitSaveCommandResponse(w http.ResponseWriter) error      { return r.write(w) }
func (r rawResponse) VisitDescribeMediaResponse(w http.ResponseWriter) error    { return r.write(w) }
func (r rawResponse) VisitRunSavedCommandResponse(w http.ResponseWriter) error  { return r.write(w) }

// localeFor is the caller's locale: the account setting, else the Accept-Language header, else de.
func (s *Server) localeFor(ctx context.Context) string {
	if u := auth.FromContext(ctx).User; u != nil && mail.Locales[u.Locale] {
		return u.Locale
	}
	if r := middleware.RequestFrom(ctx); r != nil {
		for _, part := range strings.Split(r.Header.Get("Accept-Language"), ",") {
			lang := strings.ToLower(strings.TrimSpace(strings.SplitN(part, ";", 2)[0]))
			if len(lang) >= 2 && mail.Locales[lang[:2]] {
				return lang[:2]
			}
		}
	}
	return "de"
}

// sessionToken is the raw cookie value identifying the caller (yb_session for users, yb_guest
// for guests), handed to the agent service so it can call /mcp as the same principal.
func sessionToken(ctx context.Context) string {
	r := middleware.RequestFrom(ctx)
	if r == nil {
		return ""
	}
	if auth.FromContext(ctx).User != nil {
		if c, err := r.Cookie(auth.SessionCookie); err == nil {
			return c.Value
		}
	}
	if c, err := r.Cookie(auth.GuestCookie); err == nil {
		return c.Value
	}
	return ""
}

// proxyAgent forwards a JSON request to the agent service. Connection problems are 503.
func (s *Server) proxyAgent(ctx context.Context, path string, body any, eventSlug string) (rawResponse, error) {
	p := auth.FromContext(ctx)
	if p.Anonymous() {
		return rawResponse{}, apperr.Unauthorizedf("sign in or open an event as a guest first")
	}
	if s.Cfg.AgentURL == "" {
		return rawResponse{}, errAgentUnavailable
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return rawResponse{}, err
	}
	ctx, cancel := context.WithTimeout(ctx, agentProxyTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(s.Cfg.AgentURL, "/")+path, bytes.NewReader(payload))
	if err != nil {
		return rawResponse{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-Actor", ids.Encode(p.Actor()))
	kind := "guest"
	if p.User != nil {
		kind = "user"
	}
	req.Header.Set("X-Actor-Kind", kind)
	if eventSlug != "" {
		req.Header.Set("X-Event-Slug", eventSlug)
	}
	req.Header.Set("X-Locale", s.localeFor(ctx))
	req.Header.Set("X-Session-Token", sessionToken(ctx))
	resp, err := s.AgentHTTP.Do(req)
	if err != nil {
		logErr(ctx, "agent service unreachable", err)
		return rawResponse{}, errAgentUnavailable
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return rawResponse{}, errAgentUnavailable
	}
	if resp.StatusCode >= 500 {
		logErr(ctx, "agent service error", fmt.Errorf("status %d: %.200s", resp.StatusCode, data))
		return rawResponse{}, errAgentUnavailable
	}
	if !json.Valid(data) {
		return rawResponse{}, errAgentUnavailable
	}
	return rawResponse{status: resp.StatusCode, body: data}, nil
}

// SendAgentMessage proxies a turn to the agent service after checking the event scope.
func (s *Server) SendAgentMessage(ctx context.Context, req api.SendAgentMessageRequestObject) (api.SendAgentMessageResponseObject, error) {
	if req.Body == nil || strings.TrimSpace(req.Body.Text) == "" {
		return nil, apperr.BadRequestf("text required")
	}
	if len(req.Body.Text) > 500 {
		return nil, apperr.BadRequestf("text may be at most 500 characters")
	}
	slug := ""
	if req.Body.EventSlug != nil {
		slug = *req.Body.EventSlug
	}
	if _, err := s.toolScopeFor(ctx, auth.FromContext(ctx), slug); err != nil {
		return nil, err
	}
	return s.proxyAgent(ctx, "/agent/messages", req.Body, slug)
}

// SaveCommand proxies "save as chip" (the templating model call lives in the agent service).
func (s *Server) SaveCommand(ctx context.Context, req api.SaveCommandRequestObject) (api.SaveCommandResponseObject, error) {
	if req.Body == nil || req.Body.TurnId == "" || strings.TrimSpace(req.Body.Label) == "" {
		return nil, apperr.BadRequestf("turn_id and label required")
	}
	if len(req.Body.Label) > 30 {
		return nil, apperr.BadRequestf("label may be at most 30 characters")
	}
	slug := ""
	if raw, err := ids.Decode(req.Body.TurnId); err == nil {
		if turn, err := s.Q.GetAgentTurn(ctx, raw); err == nil && turn.EventID != nil {
			if ev, err := s.Q.GetEventByID(ctx, turn.EventID); err == nil {
				slug = ev.Event.Slug
			}
		}
	}
	return s.proxyAgent(ctx, "/agent/commands", req.Body, slug)
}

// DescribeMedia is the one user-initiated vision call: the medium variant URL goes to the agent
// service, which fetches the pixels itself.
func (s *Server) DescribeMedia(ctx context.Context, req api.DescribeMediaRequestObject) (api.DescribeMediaResponseObject, error) {
	m, v, err := s.requireViewable(ctx, req.MediaId)
	if err != nil {
		return nil, err
	}
	if v.p.Anonymous() {
		return nil, apperr.Unauthorizedf("sign in or open an event as a guest first")
	}
	variants, err := s.Q.GetVariants(ctx, m.ID)
	if err != nil {
		return nil, err
	}
	url := ""
	for _, vr := range variants {
		if vr.Name == "medium" {
			url = s.Store.PublicURL(vr.Key)
		}
		if vr.Name == "poster" && url == "" {
			url = s.Store.PublicURL(vr.Key)
		}
	}
	if url == "" {
		return nil, apperr.Conflictf("this item has no preview yet")
	}
	slug := ""
	if !v.library {
		slug = v.event.Slug
	}
	return s.proxyAgent(ctx, "/describe", map[string]any{"media_id": ids.Encode(m.ID), "url": url, "kind": m.Kind, "locale": s.localeFor(ctx)}, slug)
}

// Saved commands (SDD §9 layer 3) ------------------------------------------------------------
//
// Rows are written by the agent service; Go lists, deletes and runs them. sql and search kinds
// run here with bind parameters and no model call; python tools run only in the sandbox behind
// the agent service, so their runs are proxied.

func savedCommandJSON(c db.SavedCommand, slug *string) api.SavedCommand {
	var params map[string]any
	if err := json.Unmarshal(c.Params, &params); err != nil || params == nil {
		params = map[string]any{}
	}
	kind := api.SavedCommandKind(c.Kind)
	shared, byAgent, runs := c.Shared, c.CreatedByAgent, int(c.RunCount)
	return api.SavedCommand{
		Id: ids.Encode(c.ID), Name: c.Name, Label: c.Label, Description: c.Description, Scope: api.SavedCommandScope(c.Scope),
		EventSlug: slug, Params: params, Shared: &shared, Kind: &kind, CreatedByAgent: &byAgent, RunCount: &runs,
	}
}

// ListSavedCommands lists the caller's own commands plus the ones shared in the event.
func (s *Server) ListSavedCommands(ctx context.Context, req api.ListSavedCommandsRequestObject) (api.ListSavedCommandsResponseObject, error) {
	p := auth.FromContext(ctx)
	if p.Anonymous() {
		return nil, apperr.Unauthorizedf("sign in or open an event as a guest first")
	}
	var eventID []byte
	if req.Params.EventSlug != nil && *req.Params.EventSlug != "" {
		row, err := s.eventBySlug(ctx, *req.Params.EventSlug)
		if err != nil {
			return nil, err
		}
		eventID = row.Event.ID
	}
	rows, err := s.Q.ListSavedCommands(ctx, db.ListSavedCommandsParams{Owner: p.Actor(), EventID: eventID})
	if err != nil {
		return nil, err
	}
	out := api.ListSavedCommands200JSONResponse{Commands: make([]api.SavedCommand, 0, len(rows))}
	for _, r := range rows {
		out.Commands = append(out.Commands, savedCommandJSON(r.SavedCommand, r.EventSlug))
	}
	return out, nil
}

// DeleteSavedCommand removes one of the caller's commands.
func (s *Server) DeleteSavedCommand(ctx context.Context, req api.DeleteSavedCommandRequestObject) (api.DeleteSavedCommandResponseObject, error) {
	p := auth.FromContext(ctx)
	if p.Anonymous() {
		return nil, apperr.Unauthorizedf("")
	}
	raw, err := ids.Decode(req.CommandId)
	if err != nil {
		return nil, apperr.NotFoundf("command not found")
	}
	n, err := s.Q.DeleteSavedCommand(ctx, db.DeleteSavedCommandParams{ID: raw, Owner: p.Actor()})
	if err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, apperr.NotFoundf("command not found")
	}
	return api.DeleteSavedCommand204Response{}, nil
}

// savedCommandFor loads a command the scope may run: the owner's own, or one shared and approved
// in an event of the scope.
func (s *Server) savedCommandFor(ctx context.Context, sc toolScope, id string) (db.GetSavedCommandRow, error) {
	raw, err := ids.Decode(id)
	if err != nil {
		return db.GetSavedCommandRow{}, apperr.NotFoundf("command not found")
	}
	row, err := s.Q.GetSavedCommand(ctx, raw)
	if err != nil {
		return row, apperr.NotFoundf("command not found")
	}
	c := row.SavedCommand
	if string(c.Owner) == string(sc.p.Actor()) {
		return row, nil
	}
	if c.Shared && c.ApprovedAt != nil && c.EventID != nil {
		for _, e := range sc.eventIDs {
			if string(e) == string(c.EventID) {
				return row, nil
			}
		}
	}
	return row, apperr.NotFoundf("command not found")
}

// runSavedCommand executes a sql or search command with bound parameters.
func (s *Server) runSavedCommand(ctx context.Context, sc toolScope, row db.GetSavedCommandRow, params map[string]any) (api.AgentResult, error) {
	c := row.SavedCommand
	if params == nil {
		params = map[string]any{}
	}
	switch c.Kind {
	case "sql":
		sql, args, err := agent.BindNamed(c.SqlTemplate, normalizeParams(params))
		if err != nil {
			return api.AgentResult{}, apperr.BadRequestf(err.Error())
		}
		if s.Exec == nil {
			return api.AgentResult{}, apperr.New(apperr.Internal, "run_query is not available on this server")
		}
		qr, err := s.Exec.Run(ctx, sc.p.Actor(), sc.eventID(), sql, args...)
		if err != nil {
			if errors.Is(err, agent.ErrSQLRejected) {
				return api.AgentResult{}, apperr.BadRequestf(err.Error())
			}
			return api.AgentResult{}, apperr.BadRequestf("query failed: " + err.Error())
		}
		return s.presentQuery(ctx, sc, c.Label, qr)
	case "search":
		var argsMap map[string]any
		if err := json.Unmarshal(c.SearchArgs, &argsMap); err != nil || argsMap == nil {
			argsMap = map[string]any{}
		}
		for k, v := range argsMap {
			if str, ok := v.(string); ok && strings.HasPrefix(str, ":") {
				if val, ok := params[str[1:]]; ok {
					argsMap[k] = val
				} else {
					delete(argsMap, k)
				}
			}
		}
		raw, _ := json.Marshal(argsMap)
		var in searchArgs
		if err := json.Unmarshal(raw, &in); err != nil {
			return api.AgentResult{}, apperr.BadRequestf("invalid parameters: " + err.Error())
		}
		idList, err := s.runSearch(ctx, sc, in)
		if err != nil {
			return api.AgentResult{}, apperr.BadRequestf(err.Error())
		}
		list := make([]string, 0, len(idList))
		for _, id := range idList {
			list = append(list, ids.Encode(id))
		}
		return s.mediaResult(ctx, sc, c.Label, list)
	default:
		return api.AgentResult{}, apperr.BadRequestf("python tools run through the agent service")
	}
}

// normalizeParams turns JSON numbers that are whole into int64 so they bind to integer columns.
func normalizeParams(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for k, v := range in {
		if f, ok := v.(float64); ok && f == float64(int64(f)) {
			out[k] = int64(f)
			continue
		}
		out[k] = v
	}
	return out
}

// RunSavedCommand runs a chip: sql and search here, python through the agent service.
func (s *Server) RunSavedCommand(ctx context.Context, req api.RunSavedCommandRequestObject) (api.RunSavedCommandResponseObject, error) {
	p := auth.FromContext(ctx)
	if p.Anonymous() {
		return nil, apperr.Unauthorizedf("sign in or open an event as a guest first")
	}
	slug := ""
	var params map[string]any
	if req.Body != nil {
		if req.Body.EventSlug != nil {
			slug = *req.Body.EventSlug
		}
		if req.Body.Params != nil {
			params = *req.Body.Params
		}
	}
	raw, err := ids.Decode(req.CommandId)
	if err != nil {
		return nil, apperr.NotFoundf("command not found")
	}
	row, err := s.Q.GetSavedCommand(ctx, raw)
	if err != nil {
		return nil, apperr.NotFoundf("command not found")
	}
	if slug == "" && row.EventSlug != nil {
		slug = *row.EventSlug
	}
	sc, err := s.toolScopeFor(ctx, p, slug)
	if err != nil {
		return nil, err
	}
	if _, err := s.savedCommandFor(ctx, sc, req.CommandId); err != nil {
		return nil, err
	}
	if row.SavedCommand.Kind == "python" {
		body := map[string]any{"params": params}
		if slug != "" {
			body["event_slug"] = slug
		}
		return s.proxyAgent(ctx, "/agent/commands/"+req.CommandId+"/run", body, slug)
	}
	started := time.Now()
	result, err := s.runSavedCommand(ctx, sc, row, params)
	if err != nil {
		return nil, err
	}
	logErr(ctx, "touch saved command", s.Q.TouchSavedCommand(ctx, row.SavedCommand.ID))

	// A chip run is a turn of its own so the UI can thread follow-ups and save-as works later.
	conv, err := s.Q.CreateConversation(ctx, db.CreateConversationParams{ID: ids.New(), Actor: p.Actor(), EventID: sc.eventID()})
	if err != nil {
		return nil, err
	}
	turnID := ids.New()
	finalCall, _ := json.Marshal(map[string]any{"name": "run_saved_command", "args": map[string]any{"command_id": req.CommandId, "params": params}})
	toolsUsed, _ := json.Marshal([]string{"run_saved_command"})
	latency := int32(time.Since(started).Milliseconds())
	understood := row.SavedCommand.Label
	if err := s.Q.InsertAgentTurn(ctx, db.InsertAgentTurnParams{
		ID: turnID, UserID: p.UserID(), GuestID: sc.v.guestID(), EventID: sc.eventID(), Input: "/" + row.SavedCommand.Name,
		ToolsUsed: toolsUsed, ResultKind: &result.Kind, LatencyMs: &latency, ConversationID: conv.ID, Understood: &understood, FinalCall: finalCall,
	}); err != nil {
		return nil, err
	}
	return api.RunSavedCommand200JSONResponse(api.AgentResponse{
		ConversationId: ids.Encode(conv.ID), TurnId: ids.Encode(turnID), Understood: understood, Result: result,
		Suggestions: []api.Chip{}, Saveable: false,
	}), nil
}
