from fastapi.routing import APIRoute

from backend.main import app


def _api_routes(routes):
    """Flatten FastAPI routers across eager and deferred include versions."""

    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue

        included_router = getattr(route, "original_router", None)
        nested_routes = getattr(included_router, "routes", None)
        if nested_routes is not None:
            yield from _api_routes(nested_routes)


def _route(method: str, path: str) -> APIRoute:
    return next(
        route
        for route in _api_routes(app.routes)
        if route.path == path
        and method in route.methods
    )


def _dependency_names(route: APIRoute) -> set[str]:
    return {dependency.call.__name__ for dependency in route.dependant.dependencies}


def test_data_bearing_reads_require_a_clerk_user():
    protected_reads = {
        "/profiles/",
        "/api/dashboard/analytics",
        "/api/spy-signals",
        "/profiles/{username}/analysis",
        "/api/data-coverage",
        "/api/pair-dossier",
        "/api/signal-calendar",
        "/api/rewatch-echoes",
        "/api/taste-dna",
        "/api/taste-timeline",
        "/api/public-lists",
        "/api/watch-together",
        "/api/watch-provider-regions",
        "/api/recent-changes",
    }
    for path in protected_reads:
        assert "get_current_user" in _dependency_names(_route("GET", path)), path


def test_health_and_explicit_share_profile_remain_public():
    public_reads = {"/health", "/ready", "/health/rss", "/public/profile/{username}"}
    for path in public_reads:
        dependencies = _dependency_names(_route("GET", path))
        assert "get_current_user" not in dependencies
        assert "get_admin_user" not in dependencies


def test_existing_mutations_keep_admin_or_ingestion_auth():
    admin_routes = {
        ("POST", "/profiles/create"),
        ("PUT", "/profiles/{username}"),
        ("DELETE", "/profiles/{username}"),
        ("DELETE", "/profiles/{username}/data"),
    }
    for method, path in admin_routes:
        assert "get_admin_user" in _dependency_names(_route(method, path))
    assert "get_active_upload_user" in _dependency_names(_route("POST", "/upload/"))
