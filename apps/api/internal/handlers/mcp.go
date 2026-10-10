package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"yearbook/api/internal/apperr"
	"yearbook/api/internal/auth"
	"yearbook/api/internal/ids"
)

// MCPHandler serves the agent tools over streamable HTTP at /mcp (stateless, one server per
// request). Auth: `Authorization: Bearer <yb_session token or yb_guest id>`; `X-Event-Slug`
// scopes the tools to one event. The Python agent service and any MCP client use the same door.
func (s *Server) MCPHandler() http.Handler {
	inner := mcp.NewStreamableHTTPHandler(func(r *http.Request) *mcp.Server {
		p, ok := s.mcpPrincipal(r)
		if !ok {
			return nil
		}
		sc, err := s.toolScopeFor(r.Context(), p, r.Header.Get("X-Event-Slug"))
		if err != nil {
			return nil
		}
		return s.mcpServer(sc)
	}, &mcp.StreamableHTTPOptions{Stateless: true})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p, ok := s.mcpPrincipal(r)
		if !ok {
			apperr.Write(w, r, apperr.Unauthorizedf("bearer token required: a session token or a guest id"))
			return
		}
		if _, err := s.toolScopeFor(r.Context(), p, r.Header.Get("X-Event-Slug")); err != nil {
			apperr.Write(w, r, err)
			return
		}
		inner.ServeHTTP(w, r)
	})
}

// mcpPrincipal resolves the bearer token: a session token (user) or a guest cookie id.
func (s *Server) mcpPrincipal(r *http.Request) (auth.Principal, bool) {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(strings.ToLower(h), "bearer ") {
		return auth.Principal{}, false
	}
	token := strings.TrimSpace(h[7:])
	if token == "" {
		return auth.Principal{}, false
	}
	ctx := r.Context()
	if user, _, ok, err := auth.LookupSession(ctx, s.Q, token); err == nil && ok {
		return auth.Principal{User: &user, IP: r.RemoteAddr}, true
	}
	if id, err := ids.Decode(token); err == nil {
		if exists, err := s.Q.GuestCookieExists(ctx, id); err == nil && exists {
			return auth.Principal{CookieID: id, IP: r.RemoteAddr}, true
		}
	}
	return auth.Principal{}, false
}

// mcpServer binds every tool to sc.
func (s *Server) mcpServer(sc toolScope) *mcp.Server {
	srv := mcp.NewServer(&mcp.Implementation{Name: "yearbook", Title: "Yearbook photo tools", Version: s.Version}, nil)
	for _, spec := range s.toolSpecs() {
		name := spec.Name
		schema, _ := json.Marshal(spec.Schema)
		srv.AddTool(&mcp.Tool{Name: name, Description: spec.Description, InputSchema: json.RawMessage(schema)},
			func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				res, err := s.callTool(ctx, sc, name, req.Params.Arguments)
				if err != nil {
					return &mcp.CallToolResult{IsError: true, Content: []mcp.Content{&mcp.TextContent{Text: err.Error()}}}, nil
				}
				body, err := json.Marshal(res)
				if err != nil {
					return &mcp.CallToolResult{IsError: true, Content: []mcp.Content{&mcp.TextContent{Text: "unserialisable result"}}}, nil
				}
				return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: string(body)}}, StructuredContent: json.RawMessage(body)}, nil
			})
	}
	return srv
}
