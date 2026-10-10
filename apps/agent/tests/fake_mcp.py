"""Re-export of the fake MCP server so tests can import it from the tests directory."""

from yearbook_agent.testing.fake_mcp import (  # noqa: F401
    ALBUM,
    MEDIA,
    P_ANNA,
    P_ANNA2,
    P_BEN,
    P_ME,
    PERSONS,
    FakeMCPServer,
    Recorder,
    make_server,
)
